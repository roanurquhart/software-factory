#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""ADW design-heavy SDLC — adw_sdlc with the builder on Opus.

Usage:
    uv run adws/adw_design_heavy_sdlc.py "<prompt or path/to/prompt.md>" [same flags as adw_sdlc]

Phases: identical to adw_sdlc (worktree, plan, build, test, UI test, review,
docs, push, PR). The only difference is the roster: the builder runs on
DESIGN_MODELS["builder"] instead of the config's builder model. Every builder
call takes it, so the UI-fix and review-revision loops do too.

Use it when the build itself needs judgement: visual design, layout,
animation, a UI rebuilt from references. A cheap builder follows a plan well,
but it guesses at taste and stalls on fiddly CSS. Everything else (planner,
reviewer, documenter, ui_tester) keeps its configured model.

Needs a Claude Code roster (sssf.claude.config.yaml); the model id is an
Anthropic one.
"""

import sys

import adw_sdlc
from adw_modules import agents

DESIGN_MODELS = {"builder": "anthropic/claude-opus-5-5"}


def main(prompt: str, config: str, adw_id, flow) -> int:
    cfg = agents.load_config(config)
    agents.override_models(cfg, DESIGN_MODELS)
    return adw_sdlc.run_chain(cfg, prompt, adw_id, flow)


if __name__ == "__main__":
    sys.exit(main(*adw_sdlc.parse_args(__doc__)))
