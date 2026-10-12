"""Putting a plan or write-up on record, with or without a commit.

`defaults.records` decides where records live:

  repo     the agent copies its record into specs/ or app_docs/, and the ADW
           commits it. The commit is the proof it existed before the code did.
  session  the record stays in the session's context_handoff/, and nothing but
           the product change is committed. The proof is a sha256 seal written
           to the trace when the record is accepted; `verify()` re-hashes it
           before code lands and before anything is pushed, so a record edited
           after the fact fails the run the way a rewritten commit would show.

Session runtime is always writable (see permissions.always_writable), which is
why the seal is needed: without it, a later agent could quietly rewrite the
plan it is being judged against.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import git_helper


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def keep(run, ph, envelope) -> None:
    """Commit the record (repo) or seal it in the trace (session)."""
    if run.cfg.defaults.records == "repo":
        message = envelope.commit_message or f"sssf({run.adw_id}): {envelope.summary}"
        ph.log(sha=git_helper.commit_all(message), message=message)
        return
    # A record-only agent has no business in the repo in session mode. Anything
    # it left there would ride into the next commit unannounced.
    stray = git_helper.changed_files()
    if stray:
        raise RuntimeError("records: session, but the agent changed repo files: "
                           + ", ".join(stray))
    sealed = {}
    for artifact in envelope.artifacts:
        path = Path(artifact)
        if path.is_absolute() and path.is_file():
            sealed[str(path)] = _sha256(path)
    if not sealed:
        raise RuntimeError("records: session, but the agent declared no record file to seal")
    run.seals.update(sealed)
    ph.log(sealed={Path(p).name: h[:12] for p, h in sealed.items()})


def verify(run, ph) -> None:
    """Fail if any sealed record changed or vanished since it was accepted."""
    if not run.seals:
        return
    broken = [p for p, h in run.seals.items()
              if not Path(p).is_file() or _sha256(Path(p)) != h]
    if broken:
        raise RuntimeError("sealed record(s) changed after they were accepted: "
                           + ", ".join(broken))
    ph.log(seals_verified=len(run.seals))
