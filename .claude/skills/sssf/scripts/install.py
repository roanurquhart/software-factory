#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///
"""/install — stamp the SSSF factory from the skill into the cwd. Idempotent.

Usage:
    uv run <skill>/scripts/install.py [--force] [--local]

Stamps: adws/ (modules + starter ADWs), adws/adw_data/prompt_engineering/
(4 starter agents), adws/adw_sssf_config/sssf.config.yaml, .env.sample,
.gitignore entries.
Existing files are skipped unless --force.

--local keeps the factory out of the repo's history entirely: instead of
.gitignore entries (which are themselves committed), the factory, its runtime
and .sssf/ go into .git/info/exclude, which is per clone and never committed;
and both configs are set to `records: session`, so plans and write-ups stay in
the run's session instead of being committed under specs/ and app_docs/. The
only thing a run commits is the product change.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

GITIGNORE_ENTRIES = [
    "adws/adw_data/sessions/",
    "adws/adw_data/sssf.db*",
    "adws/adw_data/worktrees/",     # adw_sdlc runs each request in its own worktree here
    ".env",
    # The ADWs are Python, so importing adw_modules writes bytecode next to it.
    # Chains that end in a commit phase call `git add -A`, so without this a
    # stamped repo commits its own .pyc files — 15 of them showed up in the
    # first repo that was ever installed into from scratch.
    "__pycache__/",
    "*.pyc",
]


# --local: everything the factory adds to a repo, excluded per clone.
LOCAL_EXCLUDE_ENTRIES = [
    "adws/",
    "justfile",
    ".env.sample",
    ".env",
    ".sssf/",                       # adw_sdlc --reference files, inside each worktree
    "__pycache__/",
    "*.pyc",
]

CONFIGS = ["adws/adw_sssf_config/sssf.config.yaml",
           "adws/adw_sssf_config/sssf.claude.config.yaml"]


def stamp(src: Path, dest: Path, force: bool, stamped: list, skipped: list) -> None:
    if src.is_dir():
        for child in sorted(src.iterdir()):
            if child.name == "__pycache__":
                continue
            stamp(child, dest / child.name, force, stamped, skipped)
        return
    if dest.exists() and not force:
        skipped.append(str(dest))
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    stamped.append(str(dest))


def ensure_gitignore(root: Path, stamped: list) -> None:
    gitignore = root / ".gitignore"
    existing = gitignore.read_text().splitlines() if gitignore.exists() else []
    missing = [e for e in GITIGNORE_ENTRIES if e not in existing]
    if missing:
        with gitignore.open("a") as f:
            f.write("\n# sssf runtime\n" + "\n".join(missing) + "\n")
        stamped.append(f"{gitignore} (+{len(missing)} entries)")


def ensure_local_exclude(root: Path, stamped: list) -> list[str]:
    """Write the factory's paths to .git/info/exclude. Returns any already tracked."""
    out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-path",
                          "info/exclude"], cwd=root, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("--local needs a git repository (run `git init` first)")
    exclude = Path(out.stdout.strip())
    entries = list(LOCAL_EXCLUDE_ENTRIES)
    skill = root / ".claude" / "skills" / "sssf"
    if skill.is_dir():
        entries.append(".claude/skills/sssf/")
    existing = exclude.read_text().splitlines() if exclude.exists() else []
    missing = [e for e in entries if e not in existing]
    if missing:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a") as f:
            f.write("\n# sssf (installed with --local)\n" + "\n".join(missing) + "\n")
        stamped.append(f"{exclude} (+{len(missing)} entries)")
    # Excluding a path does not untrack it. Name anything already committed.
    tracked = subprocess.run(["git", "ls-files", "--", *[e.rstrip("/") for e in entries
                                                         if "*" not in e]],
                             cwd=root, capture_output=True, text=True).stdout.split()
    return tracked


def set_records(config: Path, value: str, stamped: list) -> None:
    """Set defaults.records in a config, adding the key if an older config lacks it."""
    if not config.exists():
        return
    text = config.read_text()
    if re.search(r"^  records: \S+", text, re.M):
        new = re.sub(r"^  records: \S+", f"  records: {value}", text, count=1, flags=re.M)
    else:
        new = re.sub(r"^(  data_dir: .*\n)", rf"\1  records: {value}\n", text, count=1, flags=re.M)
    if new != text:
        config.write_text(new)
        stamped.append(f"{config} (records: {value})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("--local", action="store_true",
                        help="keep the factory and its records out of the repo's history")
    args = parser.parse_args()

    root = Path.cwd()
    stamped, skipped = [], []

    stamp(TEMPLATES / "adws", root / "adws", args.force, stamped, skipped)
    stamp(TEMPLATES / "prompt_engineering",
          root / "adws" / "adw_data" / "prompt_engineering", args.force, stamped, skipped)
    stamp(TEMPLATES / "harness_engineering",
          root / "adws" / "adw_data" / "harness_engineering", args.force, stamped, skipped)
    stamp(TEMPLATES / "sssf.config.yaml",
          root / "adws" / "adw_sssf_config" / "sssf.config.yaml",
          args.force, stamped, skipped)
    stamp(TEMPLATES / "sssf.claude.config.yaml",
          root / "adws" / "adw_sssf_config" / "sssf.claude.config.yaml",
          args.force, stamped, skipped)
    stamp(TEMPLATES / "env.sample", root / ".env.sample", args.force, stamped, skipped)
    # The recipes are part of the operating experience, and several cookbooks
    # plus the run banner tell you to use them, so a stamped repo has to have
    # them. Skipped like any other file if the repo already has a justfile.
    stamp(TEMPLATES / "justfile", root / "justfile", args.force, stamped, skipped)
    tracked = []
    if args.local:
        tracked = ensure_local_exclude(root, stamped)
        for config in CONFIGS:
            set_records(root / config, "session", stamped)
    else:
        ensure_gitignore(root, stamped)

    print(f"sssf installed into {root}")
    print(f"  stamped: {len(stamped)} file(s)")
    for s in stamped:
        print(f"    + {s}")
    if skipped:
        print(f"  skipped (already exist, use --force to overwrite): {len(skipped)}")
    if tracked:
        print(f"\n  already committed, so --local cannot hide them ({len(tracked)}):")
        for t in tracked[:20]:
            print(f"    ! {t}")
        print("  untrack with `git rm -r --cached <path>` and commit, if they should not be there")
    print("\nnext steps:")
    print("  1. cp .env.sample .env   # then set the key(s) your roster needs")
    print("  2. just demo             # two cheap read-only runs, end to end")
    print("  3. just sessions         # what just happened")
    print("  4. just obs              # the trace UI, needs bun")
    print("\n  no just? the raw form of step 2 is:")
    print("     uv run adws/adw_prompt.py \"say hello\" --agent scout")
    return 0


if __name__ == "__main__":
    sys.exit(main())
