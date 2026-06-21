"""UI-triggered tracker refresh.

Runs the existing labpapers / labrepos pipelines in-process, writes their JSON
sidecars into ``reports/``, then ingests them into corpus_item. One background
worker thread at a time; module-level job state the API polls. A tracker or
network failure is captured into the job state and never crashes the server.
"""

from __future__ import annotations

import threading
import datetime as _dt
from typing import Callable, Dict, Optional

from . import ingest
from .db import utcnow

# Module-level job state, guarded by _lock.
_lock = threading.Lock()
_state: Dict[str, object] = {
    "status": "idle",        # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "message": "",
    "counts": {},
    "kind": None,
}
_thread: Optional[threading.Thread] = None


def status() -> Dict[str, object]:
    with _lock:
        return dict(_state)


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


# Indirection so tests can stub the heavy pipeline call.
def _run_tracker(kind: str, days: int, reports_dir: str) -> None:
    """Run one tracker pipeline and write its sidecar into reports_dir."""
    if kind == "repos":
        from labrepos.pipeline import Options as RepoOptions, run as repo_run
        from labrepos.report import write_reports as repo_write
        result = repo_run(RepoOptions(days=days, out_dir=reports_dir, fmt="json"))
        repo_write(result, reports_dir, fmt="json")
    else:
        from labpapers.pipeline import Options as PaperOptions, run as paper_run
        from labpapers.report import write_reports as paper_write
        result = paper_run(PaperOptions(days=days, out_dir=reports_dir, fmt="json"))
        paper_write(result, reports_dir, fmt="json")


def _worker(kind: str, days: int, reports_dir: str, conn_factory: Callable[[], object]) -> None:
    # Each tracker runs in isolation: a failing tracker (e.g. the repos
    # tracker hitting a GitHub rate-limit or a missing GITHUB_TOKEN) must
    # NOT abort the worker before ingest, or successfully-fetched sidecars
    # from the other trackers would never reach corpus_item. Collect any
    # per-tracker errors and always ingest whatever sidecars now exist.
    kinds = [kind] if kind in ("papers", "repos") else ["papers", "repos"]
    errors: Dict[str, str] = {}
    for k in kinds:
        _set(message="running {} tracker".format(k))
        try:
            _run_tracker(k, days, reports_dir)
        except Exception as exc:  # noqa: BLE001 — keep going, ingest the rest
            errors[k] = "{}: {}".format(type(exc).__name__, exc)

    err_note = ", ".join("{} failed: {}".format(k, m) for k, m in errors.items())
    try:
        _set(message="ingesting reports")
        conn = conn_factory()
        try:
            counts = ingest.ingest_latest(reports_dir, conn)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        msg = "done" if not err_note else "done ({})".format(err_note)
        _set(status="done", finished_at=utcnow(), message=msg, counts=counts)
        print("[refresh] {} | counts={}{}".format(
            msg, counts,
            "" if not err_note else " | " + err_note))
    except Exception as exc:  # noqa: BLE001 — ingest itself failed
        msg = "{}: {}".format(type(exc).__name__, exc)
        if err_note:
            msg = "{} (also {})".format(msg, err_note)
        _set(status="error", finished_at=utcnow(), message=msg)
        print("[refresh] ingest failed | {}".format(msg))


def run_refresh(kind: Optional[str], days: int, reports_dir: str,
                conn_factory: Callable[[], object]) -> Dict[str, object]:
    """Start a refresh job in the background. One at a time.

    ``conn_factory`` returns a fresh DB connection for the worker thread
    (SQLite connections are not shared across threads safely).
    Returns the current job state (``status`` already 'running' on success).
    """
    global _thread
    with _lock:
        if _state["status"] == "running":
            return dict(_state)
        _state.update({
            "status": "running",
            "started_at": utcnow(),
            "finished_at": None,
            "message": "starting",
            "counts": {},
            "kind": kind or "all",
        })
    _thread = threading.Thread(
        target=_worker, args=(kind or "all", days, reports_dir, conn_factory),
        daemon=True,
    )
    _thread.start()
    return status()


def join(timeout: Optional[float] = None) -> None:
    """Block until the running job finishes (used by tests)."""
    t = _thread
    if t is not None:
        t.join(timeout)


def reset() -> None:
    """Reset state to idle (tests)."""
    _set(status="idle", started_at=None, finished_at=None, message="", counts={}, kind=None)
