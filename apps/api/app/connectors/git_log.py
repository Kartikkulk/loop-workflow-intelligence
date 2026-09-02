"""A live connector that reads a repository's recent commits.

Read-only by construction: the only command it runs is `git log`, assembled
here rather than taken from the flow definition. A generated flow supplies the
repository path and the window, never the command, so there is no way for a
model-written step to turn this into a `git push` or a `git clean`.

The path is checked against `settings.git_repos` for the same reason the files
connector checks its root — a step's inputs are partly model-generated and must
not be able to point at an arbitrary directory.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.config import settings
from app.connectors.base import Context, Step, StepResult

logger = logging.getLogger("loop.connectors.git")

_MAX_COMMITS = 200


def _allowed_repos() -> list[Path]:
    return [
        Path(part.strip()).expanduser().resolve()
        for part in settings.git_repos.split(",")
        if part.strip()
    ]


class GitConnector:
    """Runs `git log` against an allow-listed repository."""

    name = "git"
    is_mock = False
    api = "local `git log` — read-only, no network, no credentials"
    required_credentials: tuple[str, ...] = ()

    async def execute(self, step: Step, ctx: Context) -> StepResult:
        if step.type not in ("read", "search", "extract"):
            return StepResult(
                step_id=step.id,
                status="failed",
                error=(
                    f"the git connector cannot perform '{step.type}'. It reads the "
                    "commit log and nothing else."
                ),
                confidence=0.0,
            )

        allowed = _allowed_repos()
        if not allowed:
            return StepResult(
                step_id=step.id,
                status="failed",
                error=(
                    "No repository is allow-listed. Set LOOP_GIT_REPOS in .env to a "
                    "comma-separated list of paths this may read."
                ),
                confidence=0.0,
            )

        available = ctx.available()
        wanted = step.inputs.get("repo_path") or available.get("repo_path")
        if isinstance(wanted, str) and wanted.strip():
            candidate = Path(wanted.strip()).expanduser().resolve()
            if candidate not in allowed:
                return StepResult(
                    step_id=step.id,
                    status="failed",
                    error=f"{candidate} is not in LOOP_GIT_REPOS; refusing to read it",
                    confidence=0.0,
                )
            repo = candidate
        else:
            repo = allowed[0]

        since = str(available.get("since") or "1.day")
        command = [
            "git", "-C", str(repo), "log",
            f"--since={since}",
            f"--max-count={_MAX_COMMITS}",
            "--pretty=format:%h\t%an\t%s",
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        except TimeoutError:
            return StepResult(
                step_id=step.id, status="failed", error="git log timed out", confidence=0.0
            )
        except OSError as exc:
            return StepResult(
                step_id=step.id, status="failed", error=f"could not run git: {exc}", confidence=0.0
            )

        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip()[:200]
            return StepResult(
                step_id=step.id,
                status="failed",
                error=f"git log failed in {repo}: {detail}",
                confidence=0.0,
            )

        lines = [line for line in stdout.decode(errors="replace").splitlines() if line.strip()]
        commits: list[dict[str, Any]] = []
        authors: set[str] = set()
        for line in lines:
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            commits.append({"sha": parts[0], "author": parts[1], "subject": parts[2]})
            authors.add(parts[1])

        logger.info("git: %d commit(s) in %s since %s", len(commits), repo.name, since)
        return StepResult(
            step_id=step.id,
            status="ok",
            outputs={
                "repo": repo.name,
                "repo_path": str(repo),
                "commit_count": len(commits),
                "authors": sorted(authors),
                "commits": commits,
                "summary": "\n".join(
                    f"{c['sha']}  {c['author']}: {c['subject']}" for c in commits
                ),
            },
            confidence=1.0 if commits else 0.5,
        )
