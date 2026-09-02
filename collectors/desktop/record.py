#!/usr/bin/env python3
"""Record real desktop app switching on macOS as a LOOP activity log.

Run this, then do the dull thing you keep doing — three or four times, the same
way you always do it. Every time the frontmost application changes, that is one
event. Stop with Ctrl-C and the log is written; pass --upload and it goes
straight to a running LOOP API, which re-runs detection over it.

What it can and cannot see, on purpose:

  * The name of the frontmost application needs no permission at all.
  * Window titles need macOS accessibility access, which this does not ask for
    and does not use.
  * Browser tab titles are readable, but they are the most revealing thing on
    the machine, so they are off unless you pass --titles.

Nothing leaves the laptop: the only network call is to the LOOP API you name,
which defaults to localhost.

    python3 collectors/desktop/record.py --upload
    python3 collectors/desktop/record.py --out ~/my-activity.jsonl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

#: macOS application names mapped onto LOOP's app vocabulary. Anything not
#: listed registers itself under a slugified version of its own name the first
#: time it is seen, which is why an unknown app is not an error.
APP_KEYS = {
    "Google Chrome": "browser",
    "Safari": "browser",
    "Microsoft Edge": "browser",
    "Firefox": "browser",
    "Arc": "browser",
    "Mail": "outlook",
    "Microsoft Outlook": "outlook",
    "Slack": "slack",
    "Microsoft Excel": "sheets",
    "Numbers": "sheets",
    "Preview": "pdf",
    "Adobe Acrobat": "pdf",
    "Finder": "drive",
    "Terminal": "terminal",
    "iTerm2": "terminal",
    "Code": "editor",
    "Visual Studio Code": "editor",
}

BROWSERS = {"Google Chrome", "Safari", "Microsoft Edge", "Arc"}

FRONTMOST_SCRIPT = (
    'tell application "System Events" to get name of '
    "first application process whose frontmost is true"
)


def _osascript(script: str, timeout: float = 3.0) -> str | None:
    """Run one AppleScript line, returning None rather than raising."""
    try:
        done = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    value = done.stdout.strip()
    return value or None


def frontmost_app() -> str | None:
    """The application the user is looking at right now."""
    return _osascript(FRONTMOST_SCRIPT)


def browser_tab_title(app_name: str) -> str | None:
    """The active tab's title, for browsers that expose one."""
    if app_name == "Safari":
        script = f'tell application "{app_name}" to get name of current tab of front window'
    else:
        script = f'tell application "{app_name}" to get title of active tab of front window'
    return _osascript(script)


def slugify(name: str) -> str:
    """An app key LOOP can group on: lowercase, no spaces."""
    cleaned = "".join(char if char.isalnum() else "_" for char in name.lower())
    return "_".join(part for part in cleaned.split("_") if part) or "unknown"


def object_type_for(app_name: str, title: str | None) -> str:
    """What was being worked on, at the coarsest useful grain.

    Detection groups on `app:action:object_type`, so this is what decides
    whether two visits to the same application look like the same step. A tab
    title is too specific to ever repeat, so it is reduced to the site.
    """
    if not title:
        return "window"
    if app_name in BROWSERS and " - " in title:
        site = title.rsplit(" - ", 1)[-1].strip()
        return slugify(site)[:40] or "page"
    return slugify(title)[:40] or "window"


class Recorder:
    """Samples the frontmost app and emits one event per switch."""

    def __init__(self, *, user_id: str, team: str, capture_titles: bool, idle_gap: float):
        self.user_id = user_id
        self.team = team
        self.capture_titles = capture_titles
        self.idle_gap = idle_gap
        self.events: list[dict] = []
        self.session_id = f"ses_{uuid.uuid4().hex[:12]}"
        self._current: str | None = None
        self._since: float = 0.0
        self._title: str | None = None
        self._last_event_at: float = 0.0

    def _flush(self, now: float) -> None:
        """Close off the app the user just left, as one event."""
        if self._current is None:
            return
        duration_ms = int((now - self._since) * 1000)
        # Sub-second glances are the Cmd-Tab passing through an app, not work.
        if duration_ms < 1000:
            return

        # A long silence means the previous run of work ended; a new session
        # keeps unrelated activity from being sessionised into one instance.
        if self._last_event_at and (now - self._last_event_at) > self.idle_gap:
            self.session_id = f"ses_{uuid.uuid4().hex[:12]}"

        app_name = self._current
        payload: dict[str, str] = {"app_name": app_name}
        if self._title:
            payload["title"] = self._title

        self.events.append(
            {
                "id": f"evt_{uuid.uuid4().hex[:12]}",
                "user_id": self.user_id,
                "team": self.team,
                "timestamp": datetime.fromtimestamp(self._since, tz=UTC).isoformat(),
                "app": APP_KEYS.get(app_name, slugify(app_name)),
                "action": "navigate",
                "object_type": object_type_for(app_name, self._title),
                "object_id": f"obj_{uuid.uuid4().hex[:12]}",
                "duration_ms": duration_ms,
                "session_id": self.session_id,
                "payload": payload,
            }
        )
        self._last_event_at = now
        seconds = duration_ms / 1000
        print(f"  {app_name:<24} {seconds:6.1f}s", file=sys.stderr)

    def sample(self) -> None:
        """One poll. Emits an event only when the frontmost app has changed."""
        now = time.time()
        app_name = frontmost_app()
        if app_name is None or app_name == self._current:
            return
        self._flush(now)
        self._current = app_name
        self._since = now
        self._title = (
            browser_tab_title(app_name)
            if self.capture_titles and app_name in BROWSERS
            else None
        )

    def finish(self) -> None:
        self._flush(time.time())


def upload(events: list[dict], api: str) -> None:
    """POST the log to a running LOOP API as a JSONL upload."""
    body = "\n".join(json.dumps(event) for event in events).encode()
    boundary = f"----loop{uuid.uuid4().hex}"
    parts = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="desktop-activity.jsonl"\r\n'
        "Content-Type: application/x-ndjson\r\n\r\n"
    ).encode() + body + f"\r\n--{boundary}--\r\n".encode()

    request = urllib.request.Request(
        f"{api.rstrip('/')}/api/v1/ingest/upload?run_detection_after=true",
        data=parts,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
    except urllib.error.URLError as exc:
        raise SystemExit(f"could not reach the LOOP API at {api}: {exc}") from exc

    print(
        f"uploaded {result.get('events_ingested', 0)} events; "
        f"{result.get('clusters_detected', 0)} workflow(s) detected",
        file=sys.stderr,
    )
    for warning in result.get("warnings") or []:
        print(f"  warning: {warning}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Write the log here as JSONL.")
    parser.add_argument("--upload", action="store_true", help="Send it to the LOOP API.")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="LOOP API base URL.")
    parser.add_argument("--user", default="u_me", help="Who is being recorded.")
    parser.add_argument("--team", default="desktop", help="Team label for the events.")
    parser.add_argument(
        "--titles",
        action="store_true",
        help="Also record browser tab titles. Off by default: they are revealing.",
    )
    parser.add_argument("--interval", type=float, default=0.7, help="Seconds between polls.")
    parser.add_argument(
        "--duration",
        type=float,
        help="Stop automatically after this many seconds instead of waiting for Ctrl-C.",
    )
    parser.add_argument(
        "--idle-gap",
        type=float,
        default=120.0,
        help="A pause longer than this starts a new session.",
    )
    args = parser.parse_args()

    if sys.platform != "darwin":
        parser.error("this recorder uses AppleScript and only runs on macOS")
    if frontmost_app() is None:
        parser.error(
            "could not read the frontmost application. Grant your terminal "
            "Automation access under System Settings > Privacy & Security."
        )
    if not args.out and not args.upload:
        parser.error("nothing to do: pass --out, --upload, or both")

    recorder = Recorder(
        user_id=args.user,
        team=args.team,
        capture_titles=args.titles,
        idle_gap=args.idle_gap,
    )

    stop = f"for {args.duration:.0f}s" if args.duration else "until Ctrl-C"
    print(f"Recording {stop}. Do the repetitive thing a few times.", file=sys.stderr)
    if not args.titles:
        print("Tab titles are not being recorded (pass --titles to include them).", file=sys.stderr)
    print("", file=sys.stderr)

    deadline = time.time() + args.duration if args.duration else None
    try:
        while deadline is None or time.time() < deadline:
            recorder.sample()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass

    recorder.finish()
    events = recorder.events
    print(f"\nrecorded {len(events)} app switches", file=sys.stderr)
    if not events:
        print("nothing to save — no app switch lasted longer than a second", file=sys.stderr)
        return 1

    if args.out:
        args.out.write_text("\n".join(json.dumps(event) for event in events) + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    if args.upload:
        upload(events, args.api)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
