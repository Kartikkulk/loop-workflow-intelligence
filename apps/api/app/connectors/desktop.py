"""A connector that actually does something: activating macOS applications.

Every other live connector in `real_connectors.py` declares the API it would
call and refuses to run until it is configured. This one is implemented, and it
is the only connector in the project that can change the state of the machine
it runs on.

It is deliberately the smallest possible real capability. Bringing an
application to the front is observable, is what a recorded app-switching
workflow is actually made of, and cannot destroy anything: the worst outcome of
a wrong rule is a window you did not ask for. That is the right size for a first
executing connector.

Two independent brakes stand in front of it, and both are on by default:

  * `settings.enable_mock_connectors` — while true, the registry never hands
    this class out at all, so nothing here can run.
  * `settings.desktop_dry_run` — while true, a step reports the command it
    would have run and returns without running it.

Replay and shadow force the mock regardless of either, in the registry rather
than here, so this connector cannot forget to be safe during a practice run.
"""

from __future__ import annotations

import asyncio
import logging
import shutil

from app.config import settings
from app.connectors.base import Context, Step, StepResult

logger = logging.getLogger("loop.connectors.desktop")

#: Applications this connector is allowed to bring to the front. An automation
#: is assembled partly from model output, so the application name reaching
#: `open` is untrusted input and is checked against what was actually observed
#: rather than passed through.
_ALLOWED_APP_NAMES = frozenset(
    {
        "Google Chrome", "Safari", "Microsoft Edge", "Firefox", "Arc",
        "Mail", "Microsoft Outlook", "Slack", "Microsoft Excel", "Numbers",
        "Preview", "Adobe Acrobat", "Finder", "Terminal", "iTerm2",
        "Visual Studio Code", "Code", "Notes", "Calendar", "Reminders",
        "Messages", "Music", "System Settings",
    }
)

#: Step types this connector understands. Anything else is refused rather than
#: guessed at, because guessing at an unknown verb is how a connector acquires
#: an effect nobody reviewed.
_SUPPORTED_TYPES = frozenset({"navigate", "activate", "open", "read"})


def _app_name_for(step: Step, ctx: Context) -> str | None:
    """Recover the macOS application name this step refers to.

    The recorder stores it in the event payload as `app_name`, which survives
    into the flow definition. Falling back to the connector key would guess
    "browser" at a real application name, so it is not attempted.
    """
    for source in (step.inputs, ctx.available()):
        candidate = source.get("app_name") or source.get("application")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


class DesktopConnector:
    """Brings macOS applications to the front, for real."""

    name = "desktop"
    is_mock = False
    api = "macOS `open -a` — activates an application that is already installed"
    required_credentials: tuple[str, ...] = ()

    async def execute(self, step: Step, ctx: Context) -> StepResult:
        if step.type not in _SUPPORTED_TYPES:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=(
                    f"the desktop connector cannot perform '{step.type}'. It only "
                    f"activates applications ({', '.join(sorted(_SUPPORTED_TYPES))})."
                ),
                confidence=0.0,
            )

        app_name = _app_name_for(step, ctx)
        if app_name is None:
            return StepResult(
                step_id=step.id,
                status="failed",
                error="no application name available for this step",
                unresolved=["app_name"],
                confidence=0.0,
            )

        if app_name not in _ALLOWED_APP_NAMES:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=(
                    f"'{app_name}' is not in the list of applications this connector "
                    "may activate. Add it to _ALLOWED_APP_NAMES if that is intended."
                ),
                confidence=0.0,
            )

        command = ["open", "-a", app_name]

        if settings.desktop_dry_run:
            ctx.notes.append(f"would run: {' '.join(command)}")
            return StepResult(
                step_id=step.id,
                status="ok",
                outputs={"app_name": app_name, "activated": False},
                confidence=1.0,
                side_effect=f"desktop.activate {app_name} (dry run — nothing was opened)",
            )

        if shutil.which("open") is None:
            return StepResult(
                step_id=step.id,
                status="failed",
                error="`open` is not available; this connector requires macOS",
                confidence=0.0,
            )

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        except TimeoutError:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"activating {app_name} timed out",
                confidence=0.0,
            )
        except OSError as exc:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"could not activate {app_name}: {exc}",
                confidence=0.0,
            )

        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip() or f"exit {process.returncode}"
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"could not activate {app_name}: {detail}",
                confidence=0.0,
            )

        logger.info("desktop: activated %s", app_name)
        return StepResult(
            step_id=step.id,
            status="ok",
            outputs={"app_name": app_name, "activated": True},
            confidence=1.0,
            side_effect=f"desktop.activate {app_name}",
        )
