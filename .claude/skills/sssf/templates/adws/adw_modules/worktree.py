"""Run isolation: one git worktree on one branch per run.

The run WORKS in the worktree — agents spawn there, quality runs there, every
git_helper call (which uses the process cwd) commits there. The run is
RECORDED in the main checkout: `anchor()` pins data_dir, the trace db and the
prompt files to absolute paths before the process moves, so sessions, the db
and the dashboard see a worktree run exactly like any other.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import git_helper
from .data_types import SSSFConfig


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def anchor(cfg: SSSFConfig, root: Path) -> None:
    """Make every runtime and prompt path absolute under the main checkout.

    Repo paths (`writes`, `protected_files`) stay relative: they describe the
    tree the agent works in, which is the worktree.
    """
    def pin(path: str) -> str:
        return path if Path(path).is_absolute() else str((root / path).resolve())

    cfg.defaults.data_dir = pin(cfg.defaults.data_dir)
    cfg.observability.db = pin(cfg.observability.db)
    for agent in cfg.agents:
        agent.prompt_engineering.system = pin(agent.prompt_engineering.system)
        agent.prompt_engineering.user = pin(agent.prompt_engineering.user)
        agent.harness_engineering = [pin(ext) for ext in agent.harness_engineering]


def create(root: Path, data_dir: str, adw_id: str, base: str) -> tuple[Path, str]:
    """Worktree at {data_dir}/worktrees/{adw_id} on branch sssf/{adw_id}, off `base`.

    Rejoining a run (--adw-id) reuses its worktree, or re-attaches its branch
    if the worktree was removed. Returns (path, branch).
    """
    branch = f"sssf/{adw_id}"
    path = Path(data_dir) / "worktrees" / adw_id
    if path.exists():
        return path, branch
    path.parent.mkdir(parents=True, exist_ok=True)
    if git_helper.ref_exists(branch):
        _git("worktree", "add", str(path), branch, cwd=root)
    else:
        _git("worktree", "add", "-b", branch, str(path), base, cwd=root)
    return path, branch


REFERENCE_DIR = ".sssf/reference"


def add_references(path: Path, files: list[str]) -> list[str]:
    """Copy reference files (screenshots, mockups, docs) into the worktree.

    Agents only read inside their worktree and session dir, so a file the
    engineer hands over must land in the worktree. It goes under .sssf/, which
    is added to git's local exclude list: agents can read it, nothing commits
    it, and the permission snapshot never sees it as a change.
    Returns the copies' paths relative to the worktree root.
    """
    if not files:
        return []
    exclude = Path(_git("rev-parse", "--path-format=absolute", "--git-path", "info/exclude", cwd=path))
    exclude.parent.mkdir(parents=True, exist_ok=True)
    lines = exclude.read_text().splitlines() if exclude.exists() else []
    if ".sssf/" not in lines:
        exclude.write_text("\n".join(lines + [".sssf/"]) + "\n")
    dest = path / REFERENCE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for f in files:
        src = Path(f)
        shutil.copy2(src, dest / src.name)
        copied.append(f"{REFERENCE_DIR}/{src.name}")
    return copied


def enter(run, path: Path) -> None:
    """Move the run into the worktree: cwd for git_helper, repo_root for agents."""
    os.chdir(path)
    run.repo_root = path.resolve()


def remove(run, root: Path, path: Path) -> None:
    """Step back into the main checkout and delete the worktree. The branch stays."""
    os.chdir(root)
    run.repo_root = root
    _git("worktree", "remove", str(path), cwd=root)
