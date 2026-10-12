#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""ADW SDLC — the full chain in its own worktree and branch, ending in a pull request.

Usage:
    uv run adws/adw_sdlc.py "<prompt or path/to/prompt.md>" [--config adws/adw_sssf_config/sssf.config.yaml] [--adw-id a1b2c3d4] [--base main] [--no-pr] [--reference path/to/file ...]

Phases: engineer(request) -> git(worktree) -> planner -> git(commit_plan)
        -> builder -> code(test) [-> builder(fix) -> code(test) ... bounded]
        -> code(ui_scope) [-> code(start_app) -> ui_tester [-> builder(ui_fix) -> ui_tester ... bounded]]
        -> reviewer [-> builder(revise) -> reviewer ... bounded]
        -> code(retest, only if a revision changed code)
        -> git(commit_build) -> code(changes) -> documenter -> git(commit_docs)
        -> git(push) -> gh(pull_request) -> git(cleanup)

adw_simple_sdlc, moved off the engineer's checkout. The run creates branch
`sssf/<adw_id>` off `--base` in a worktree at `adws/adw_data/worktrees/<adw_id>`,
and every agent, test and commit happens there — the engineer's own tree is
never touched, and two runs can go at once.

UI testing runs only when it can matter, and code decides: the planner's
`ui_impact` (intent) OR a changed file under quality.UI_APP.frontend_paths
(fact). Code starts the app on a free port; the ui_tester (Playwright, no
shell, no edits) screenshots a verdict per check, and failures go back to the
builder with the screenshot paths. With UI_APP unset the phase is skipped and
says so. Setup: cookbooks/setup_ui_testing.md.

Branching, committing, pushing and opening the PR are all code. Agents write
the words (each one's commit_message, the plan and review the PR body is built
from); git and gh do the work.

The run record stays in the main checkout (sessions, sssf.db), so the
dashboard shows worktree runs like any other.

`--reference` hands the agents files that are not in the repo (screenshots,
mockups, a PDF). Code copies them into the worktree under .sssf/reference/,
kept out of git, and appends their paths to the request.

A run that is not accepted — red suite or rejected review — stops before the
push: nothing leaves the machine, and the worktree stays for the engineer to
inspect. An accepted run pushes, opens the PR, and removes its worktree; the
branch remains. `--no-pr` keeps everything local: same branch and commits, no
push, no PR.
"""

import argparse
import sys
from pathlib import Path

from adw_modules import (agents, changes, gates, git_helper, pull_request,
                         quality, session, ui, utils, worktree)
from adw_modules.data_types import (AgentCall, BuildOutput, ChangeCapture,
                                    DocumentOutput, PhaseParams, PlanOutput,
                                    PrParts, PullRequest, ReviewOutput,
                                    UiTestOutput, BranchFlow)

REQUIRED_AGENTS = ["planner", "builder", "reviewer", "documenter"]
MAX_FIX_LOOPS = 3
MAX_REVISION_LOOPS = 2
MAX_UI_LOOPS = 3

DOCUMENT_NOTES = ("Read diff_path in full before writing. Document only what the "
                  "diff shows, then copy the write-up into app_docs/ as your task "
                  "describes.")


def main(prompt: str, config: str = "adws/adw_sssf_config/sssf.config.yaml",
         adw_id: str | None = None, flow: BranchFlow = BranchFlow()) -> int:
    base, open_pr = flow.base, flow.open_pr
    cfg = agents.load_config(config)
    root = git_helper.repo_root()
    worktree.anchor(cfg, root)            # the run record stays in this checkout
    # ui_tester is only required once UI testing is set up in quality.UI_APP.
    agents.validate(cfg, REQUIRED_AGENTS + (["ui_tester"] if ui.configured() else []))
    run = session.ensure(cfg, adw_id)

    def commit(ph, envelope) -> None:
        """Commit what the preceding phase produced, in that agent's own words."""
        message = envelope.commit_message or f"sssf({run.adw_id}): {envelope.summary}"
        ph.log(sha=git_helper.commit_all(message), message=message)

    def record(ph, result) -> None:
        """Log a deterministic block's verdict — the same shape every ADW uses."""
        passed = sum(1 for check in result.checks if check.passed)
        ph.log(passed=result.passed, checks=f"{passed}/{len(result.checks)}",
               artifacts=", ".join(result.artifacts))

    with run.phase(PhaseParams(name="request", kind="engineer", owner=run.engineer,
                               description="Capture the incoming ask")) as ph:
        ph.log(input=prompt, base=base, pull_request=open_pr)

    with run.phase(PhaseParams(name="worktree", kind="code", owner="git",
                               description="Isolate the run on its own branch so the engineer's "
                                           "checkout is never touched")) as ph:
        if not git_helper.ref_exists(base):
            raise RuntimeError(f"base ref {base!r} does not exist — pass --base")
        if open_pr:
            pull_request.preflight()      # fail now, not after paying for the chain
        baseline = git_helper.rev(base)
        path, branch = worktree.create(root, cfg.defaults.data_dir, run.adw_id, base)
        worktree.enter(run, path)
        references = worktree.add_references(path, flow.references)
        if references:
            prompt += ("\n\n## Reference files\n\nThe engineer attached these files. They are in "
                       "the worktree, kept out of git; open them with your Read tool:\n"
                       + "\n".join(f"- `{r}`" for r in references))
        ph.log(branch=branch, path=str(path), baseline=git_helper.short_sha(baseline),
               references=references)

    with run.phase(PhaseParams(name="plan", kind="agent", owner="planner",
                               description="Turn the request into an implementable plan")) as ph:
        plan = ph.call(AgentCall(output_type=PlanOutput, prompt=prompt,
                                 gates=[gates.artifacts_exist, gates.files_non_empty]))

    with run.phase(PhaseParams(name="commit_plan", kind="code", owner="git",
                               description="Put the spec on record before any code exists to blur it")) as ph:
        commit(ph, plan)

    with run.phase(PhaseParams(name="build", kind="agent", owner="builder",
                               description="Implement the plan exactly")) as ph:
        build = ph.call(AgentCall(output_type=BuildOutput, prompt=prompt, previous=plan,
                                  gates=[gates.diff_matches_claims]))

    test = None
    for i in range(1, MAX_FIX_LOOPS + 1):
        with run.phase(PhaseParams(name=f"test_{i}", kind="code", owner="quality",
                                   description="Run the suite — a known command, so code runs "
                                               "it and no agent has to rediscover it")) as ph:
            test = quality.run_tests(run)
            record(ph, test)

        if test.passed:
            break

        with run.phase(PhaseParams(name=f"fix_{i}", kind="agent", owner="builder", retries=1,
                                   description="Repair what the suite reported, from its "
                                               "verbatim output")) as ph:
            build = ph.call(AgentCall(output_type=BuildOutput, prompt=prompt,
                                      previous=quality.as_envelope(test, "tests"),
                                      gates=[gates.diff_matches_claims]))

    uitest = None
    ui_fixed = False
    with run.phase(PhaseParams(name="ui_scope", kind="code", owner="ui",
                               description="Decide from the plan and the real diff whether a "
                                           "browser test can tell us anything")) as ph:
        touched, ui_note = ui.touched(plan, ui.changed_since(baseline))
        if touched and not ui.configured():
            ui_note = (f"{ui_note}, but quality.UI_APP is not set up — UI test skipped "
                       "(cookbooks/setup_ui_testing.md)")
        ph.log(run_ui_test=touched and ui.configured(), reason=ui_note)

    if touched and ui.configured():
        with run.phase(PhaseParams(name="start_app", kind="code", owner="ui",
                                   description="Serve the app on a free port so the tester gets "
                                               "a URL, not a setup job")) as ph:
            app = ui.start(run)
            ph.log(url=app.url, pid=app.pid, log=str(app.log_path))
        try:
            for i in range(1, MAX_UI_LOOPS + 1):
                with run.phase(PhaseParams(name=f"ui_test_{i}", kind="agent", owner="ui_tester",
                                           description="Use the app in a real browser and "
                                                       "screenshot a verdict for every check")) as ph:
                    uitest = ph.call(AgentCall(
                        output_type=UiTestOutput, prompt=prompt,
                        previous=ui.brief(plan, app, run, ui.changed_since(baseline)),
                        gates=[gates.ui_evidence, gates.ui_verdict_consistent]))

                if uitest.passed or i == MAX_UI_LOOPS:
                    break

                with run.phase(PhaseParams(name=f"ui_fix_{i}", kind="agent", owner="builder",
                                           retries=1,
                                           description="Fix what the browser showed, from the "
                                                       "tester's words and screenshots")) as ph:
                    build = ph.call(AgentCall(output_type=BuildOutput, prompt=prompt,
                                              previous=ui.as_fix_request(uitest),
                                              gates=[gates.diff_matches_claims]))
                    ui_fixed = True
        finally:
            ui.stop(run, app)             # always — a leaked dev server outlives the run

    review = None
    revised = False
    for i in range(1, MAX_REVISION_LOOPS + 1):
        with run.phase(PhaseParams(name=f"review_{i}", kind="agent", owner="reviewer",
                                   description="Confirm the build matches the plan")) as ph:
            review = ph.call(AgentCall(output_type=ReviewOutput, prompt=prompt, previous=build,
                                       gates=[gates.artifacts_exist, gates.verdict_consistent]))

        if review.approved or i == MAX_REVISION_LOOPS:
            break

        with run.phase(PhaseParams(name=f"revise_{i}", kind="agent", owner="builder", retries=1,
                                   description="Close the reviewer's blocking findings")) as ph:
            build = ph.call(AgentCall(output_type=BuildOutput, prompt=prompt, previous=review,
                                      gates=[gates.diff_matches_claims]))
            revised = True

    if (revised or ui_fixed) and review is not None and review.approved:
        with run.phase(PhaseParams(name="retest", kind="code", owner="quality",
                                   description="Re-run the suite — a UI fix or revision changed "
                                               "code after the last green result")) as ph:
            test = quality.run_tests(run)
            record(ph, test)

    # Not verified: stop here. Nothing is pushed, and the worktree stays put
    # with the uncommitted code in it for the engineer to look at.
    verified = (test is not None and test.passed
                and review is not None and review.approved
                and (uitest is None or uitest.passed))
    if verified:
        with run.phase(PhaseParams(name="commit_build", kind="code", owner="git",
                                   description="Land the code only now: green suite, approved review")) as ph:
            commit(ph, build)

        with run.phase(PhaseParams(name="changes", kind="code", owner="git",
                                   description="Diff the whole branch against its base, for the documenter")) as ph:
            changeset = changes.capture(run, ChangeCapture(base=baseline))
            ph.log(base=f"{changeset.base.label} @ {changeset.base.commit[:7]}",
                   files=len(changeset.files) + len(changeset.untracked),
                   lines=f"+{changeset.insertions} -{changeset.deletions}",
                   diff=changeset.diff_path)
            if changeset.empty:
                raise RuntimeError(f"nothing changed since {base} — there is nothing to document.")

        with run.phase(PhaseParams(name="document", kind="agent", owner="documenter", retries=1,
                                   description="Write up the completed change")) as ph:
            document = ph.call(AgentCall(output_type=DocumentOutput, prompt=prompt,
                                         previous=changes.as_envelope(changeset, DOCUMENT_NOTES),
                                         gates=[gates.artifacts_exist, gates.files_non_empty]))

        with run.phase(PhaseParams(name="commit_docs", kind="code", owner="git",
                                   description="Ship the write-up in its own commit, beside the code it describes")) as ph:
            commit(ph, document)

        if open_pr:
            with run.phase(PhaseParams(name="push", kind="code", owner="git",
                                       description="Publish the verified branch — only accepted work leaves the machine")) as ph:
                pull_request.push(branch)
                ph.log(branch=branch, remote="origin")

            with run.phase(PhaseParams(name="pull_request", kind="code", owner="gh",
                                       description="Open the PR with a body built from the plan, "
                                                   "review and docs the agents reported")) as ph:
                pr = PullRequest(branch=branch, base=base,
                                 title=build.commit_message or plan.summary,
                                 body=pull_request.body(PrParts(
                                     plan=plan, review=review, document=document,
                                     ui=uitest, ui_note=ui_note, adw_id=run.adw_id)))
                url = pull_request.open_pr(pr, run.session_dir / "pull_request.md")
                ph.log(url=url, title=pr.title)

        with run.phase(PhaseParams(name="cleanup", kind="code", owner="git",
                                   description="Remove the worktree; the branch keeps every commit")) as ph:
            worktree.remove(run, root, path)
            ph.log(removed=str(path), branch=branch)

    return run.finish(accepted=verified,
                      reason="the suite, the UI test or the review never came back clean — "
                             f"worktree kept at {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="inline text or a path to a prompt file")
    parser.add_argument("--config", default="adws/adw_sssf_config/sssf.config.yaml")
    parser.add_argument("--adw-id", default=None, help="join or pin an existing session")
    parser.add_argument("--base", default="main", help="branch to fork from and open the PR against")
    parser.add_argument("--no-pr", action="store_true", help="branch and commit only; no push, no PR")
    parser.add_argument("--reference", action="append", default=[], metavar="FILE",
                        help="a file for the agents to read (image, doc); repeatable")
    args = parser.parse_args()
    missing = [f for f in args.reference if not Path(f).is_file()]
    if missing:
        parser.error(f"--reference file(s) not found: {', '.join(missing)}")
    sys.exit(main(utils.resolve_prompt(args.prompt), args.config, args.adw_id,
                  BranchFlow(base=args.base, open_pr=not args.no_pr,
                             references=[str(Path(f).resolve()) for f in args.reference])))
