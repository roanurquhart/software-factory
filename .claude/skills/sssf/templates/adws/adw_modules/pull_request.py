"""Push a run's branch and open its pull request — a known command, so code does it.

`preflight()` runs before any agent does: a run that cannot open its PR should
fail in a second, not after it has paid for a plan, a build and a review.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .data_types import PrParts, PullRequest


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed: {result.stderr.strip()[-800:]}")
    return result.stdout.strip()


def preflight() -> None:
    """There is an `origin` to push to, and gh is installed and logged in."""
    if "origin" not in _run(["git", "remote"]).split():
        raise RuntimeError("no `origin` remote to push to — add one, or pass --no-pr")
    if not shutil.which("gh"):
        raise RuntimeError("gh CLI not found — install it (brew install gh), or pass --no-pr")
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode != 0:
        raise RuntimeError("gh is not logged in — run `gh auth login`, or pass --no-pr")


def push(branch: str) -> None:
    _run(["git", "push", "-u", "origin", branch])


def body(parts: PrParts) -> str:
    """The PR description, assembled from what the agents reported — nothing invented."""
    plan, review, document, ui = parts.plan, parts.review, parts.document, parts.ui
    lines = ["## Summary", "", plan.summary, "", "## Review", "", review.summary, ""]
    lines += [f"- [{'x' if f.met else ' '}] {f.requirement} — {f.evidence}"
              for f in review.findings]
    lines += ["", "## UI test", ""]
    if ui:
        lines += [ui.summary, ""]
        lines += [f"- [{'x' if c.passed else ' '}] {c.check} — {c.observed}" for c in ui.checks]
    else:
        lines += [parts.ui_note or "Not run."]
    docs = [path for path in [*plan.artifacts, document.document_path]
            if path and not Path(path).is_absolute()]
    if docs:
        lines += ["", "## Spec and docs", ""] + [f"- `{path}`" for path in dict.fromkeys(docs)]
    lines += ["", "---", f"SSSF run `{parts.adw_id}`"]
    return "\n".join(lines) + "\n"


def open_pr(pr: PullRequest, body_path: Path) -> str:
    """`gh pr create` from a body file; returns the PR url."""
    body_path.write_text(pr.body)
    out = _run(["gh", "pr", "create", "--base", pr.base, "--head", pr.branch,
                "--title", pr.title, "--body-file", str(body_path)])
    return out.splitlines()[-1] if out else ""
