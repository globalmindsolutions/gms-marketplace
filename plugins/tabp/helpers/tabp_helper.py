"""tabp_helper.py — stdlib-only deterministic helper for tabp .tabp/ workspace state.

Python >= 3.9, zero pip dependencies at runtime. Invoked via Bash by the
screen-cvs coordinator as:

    python3 plugins/tabp/helpers/tabp_helper.py <subcommand> [args]

Subcommands: run-start, state-write, decision-write, sign-off-write,
             run-finalize, run-status, validate, usage-read, settings-read.

Re-implements (does NOT import) acs_lib primitives in the tabp namespace.
No acs reference appears in this file.

Spec: MAR-2/specs/02-tabp-helper.md
Design: MAR-1/design.md sections 233-288, 423-442, 612-642, 717-731, 748-777.
"""

import json
import os
import socket
import sys
import tempfile
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Exit codes (tabp-specific)
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LOCK_BLOCKED = 2
EXIT_VALIDATION_FAILED = 3

# ---------------------------------------------------------------------------
# Module-level schema cache (avoid repeated I/O)
# ---------------------------------------------------------------------------

_SCHEMA_CACHE = {}

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class TabpLockError(Exception):
    """Raised when the tabp lock cannot be acquired."""


class TabpValidationError(Exception):
    """Raised when a record fails schema validation.

    Message names the record type and the field that failed.
    """


# ---------------------------------------------------------------------------
# ISO-8601 timestamps
# Pattern: now_iso / parse_iso (acs_lib lines 115-123, re-implemented here)
# ---------------------------------------------------------------------------


def _now_iso():
    """Return current UTC time as ISO-8601 string: YYYY-MM-DDTHH:MM:SSZ."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_stamp():
    """Timestamp for run identifiers, with microsecond precision.

    Distinct from _now_iso (second precision, used for human-facing
    timestamps): two runs started within the same wall-clock second must still
    receive unique run_ids, otherwise the second run would overwrite the
    first's run.json and append a duplicate-run_id history entry.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_iso(s):
    """Parse an ISO-8601 string (YYYY-MM-DDTHH:MM:SSZ) into an aware datetime.

    Returns None on TypeError or ValueError (conservative: treat as unparseable).
    """
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Atomic JSON I/O
# Pattern: write_json (acs_lib lines 143-155, re-implemented here)
# ---------------------------------------------------------------------------


def _read_json(path):
    """Tolerant read: returns None when the file is missing or corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write("tabp: warning: unreadable/corrupt JSON at %s (%s) — treated as absent\n"
                         % (path, exc))
        return None


def _write_json(path, data):
    """Atomic, pretty-printed JSON write via temp-file + os.replace.

    1. Create parent dirs (exist_ok=True).
    2. mkstemp with prefix '.tabp-tmp-' in the same directory.
    3. Write json.dumps(data, indent=2, ensure_ascii=False) + newline.
    4. os.replace(tmp, path) — atomic on POSIX.
    5. Unlink temp file in finally if it still exists (handles write errors).
    """
    dir_path = os.path.dirname(path) or "."
    os.makedirs(dir_path, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_path, prefix=".tabp-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Spin-lock — acquire, stale-report, release
# Pattern: acquire_lock / check_lock / lock_is_stale / release_lock
# (acs_lib lines 970-1030, re-implemented here in tabp namespace)
# ---------------------------------------------------------------------------


def _lock_path(tabp_dir):
    return os.path.join(tabp_dir, ".lock")


def _lock_is_ours(lock, run_id):
    """Return True if `lock` is held by us.

    The tabp helper runs as a series of short-lived subprocesses (one per
    subcommand), so the process that acquired the lock has already exited by
    the time a later subcommand (e.g. run-finalize) needs to release it. The
    live PID therefore cannot be the sole ownership key. Ownership holds when
    EITHER:

      - same process: hostname matches and the recorded PID is this process
        (covers a single process re-acquiring/releasing its own lock); or
      - same run: hostname matches and the recorded run_id equals `run_id`
        (the cross-process case — run-finalize releasing the lock that the
        prior run-start process acquired for this same run, and resume
        re-entrancy).

    A cross-host lock is never ours.
    """
    if lock.get("hostname") != socket.gethostname():
        return False
    if lock.get("pid") == os.getpid():
        return True
    if run_id is not None and lock.get("run_id") == run_id:
        return True
    return False


def _is_stale_lock(lock):
    """Determine whether a lock record is stale.

    Pattern: lock_is_stale (acs_lib line 974, re-implemented for tabp namespace).

    Same-host check: probe via os.kill(pid, 0).
      - ProcessLookupError -> stale (process gone).
      - PermissionError or OSError -> not stale (process exists, no permission).
    Cross-host fallback: age > 24 hours -> stale.
    Unparseable created_at -> conservative: not stale.
    """
    hostname = lock.get("hostname")
    pid = lock.get("pid")
    created_at_str = lock.get("created_at")

    if hostname == socket.gethostname() and isinstance(pid, int):
        try:
            os.kill(pid, 0)
            return False  # process exists and we have permission
        except ProcessLookupError:
            return True  # process is gone
        except (PermissionError, OSError):
            return False  # process exists, no permission to signal

    # Cross-host: fall back to age
    created = _parse_iso(created_at_str)
    if created is None:
        return False  # unparseable -> conservative: not stale
    age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600.0
    return age_hours > 24


def _acquire_lock(tabp_dir, run_id=None):
    """Acquire the tabp run lock.

    1. Read existing lock.
    2. If it is ours (same process PID, or same host + matching run_id):
       re-entrant -> return immediately.
    3. If stale: print REPORT to stderr, raise TabpLockError (REPORT-not-steal,
       design.md:729).
    4. If active foreign lock: raise TabpLockError naming the holder.
    5. If no lock: write new lock record (pid, hostname, created_at, run_id).
    """
    lpath = _lock_path(tabp_dir)
    lock = _read_json(lpath)
    if isinstance(lock, dict):
        # Re-entrant check: our own lock (same process, or same run_id resumed
        # in a later subprocess).
        if _lock_is_ours(lock, run_id):
            return  # re-entrant: already holding the lock

        if _is_stale_lock(lock):
            msg = (
                "tabp: warning: stale lock found (pid=%s, host=%s, created=%s); "
                "the holding process is gone. The lock will NOT be stolen. "
                "Remove %s manually if you are certain no other session is running."
                % (lock.get("pid"), lock.get("hostname"),
                   lock.get("created_at"), lpath)
            )
            sys.stderr.write(msg + "\n")
            raise TabpLockError(msg)

        raise TabpLockError(
            "tabp: lock held by pid=%s host=%s since %s; cannot acquire."
            % (lock.get("pid"), lock.get("hostname"), lock.get("created_at"))
        )

    # No lock (or unparseable): write our lock
    _write_json(lpath, {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at": _now_iso(),
        "run_id": run_id,
    })


def _release_lock(tabp_dir, run_id=None):
    """Release the tabp run lock, but only if we own it.

    Ownership uses the same cross-process rule as _acquire_lock (our live PID,
    or a matching run_id on this host), so run-finalize — which runs in a
    different process from run-start — can release the lock for its run.

    Suppresses FileNotFoundError (idempotent).
    Never releases a foreign lock (different run or different host).
    """
    lpath = _lock_path(tabp_dir)
    lock = _read_json(lpath)
    if isinstance(lock, dict) and not _lock_is_ours(lock, run_id):
        return  # not our lock; do not release
    try:
        os.unlink(lpath)
    except FileNotFoundError:
        pass  # idempotent


# ---------------------------------------------------------------------------
# Append-only history
# Pattern: append_in_progress_run / finalize_run / last_run
# (acs_lib lines 684-723, re-implemented here in tabp namespace)
# ---------------------------------------------------------------------------


def _read_history(history_path):
    """Read history.json; return {'runs': []} if absent or corrupt (never raises)."""
    data = _read_json(history_path)
    if isinstance(data, dict) and isinstance(data.get("runs"), list):
        return data
    return {"runs": []}


def _append_run_to_history(history_path, run_summary):
    """Append run_summary to history.json runs array.

    Never deletes existing entries (append-only invariant, design.md:725-731).
    """
    history = _read_history(history_path)
    history["runs"].append(run_summary)
    _write_json(history_path, history)


def _update_run_in_history(history_path, run_id, updates, fallback=None):
    """Update fields of the last entry in history.json whose run_id matches.

    If no matching entry exists, append a new entry (recovery path), seeded
    with `fallback` first (e.g. skill/started_at carried from run.json) so the
    recovered summary still satisfies history.schema.json's required fields
    (run_id, skill, started_at, status). Prior entries are never touched.
    """
    history = _read_history(history_path)
    runs = history["runs"]
    # Find the last matching entry
    matched_idx = None
    for i in range(len(runs) - 1, -1, -1):
        if runs[i].get("run_id") == run_id:
            matched_idx = i
            break
    if matched_idx is not None:
        runs[matched_idx].update(updates)
    else:
        # Recovery path: no matching entry found, append one
        entry = {"run_id": run_id}
        if fallback:
            entry.update(fallback)
        entry.update(updates)
        runs.append(entry)
    _write_json(history_path, history)


# ---------------------------------------------------------------------------
# Schema loader
# ---------------------------------------------------------------------------


def _load_schema(schema_name):
    """Load a JSON Schema from the schemas/ directory adjacent to this module.

    Caches loaded schemas in _SCHEMA_CACHE to avoid repeated I/O.
    Path: os.path.join(os.path.dirname(__file__), '..', 'schemas', schema_name + '.schema.json')
    """
    if schema_name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[schema_name]
    schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "schemas",
        schema_name + ".schema.json",
    )
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    _SCHEMA_CACHE[schema_name] = schema
    return schema


# ---------------------------------------------------------------------------
# Type-specific validators (hand-written stdlib walker, no jsonschema pip import)
# Pattern: validate_settings / validate_formats
# (acs_lib lines 276-351, re-implemented here in tabp namespace)
# ---------------------------------------------------------------------------


def _require(record, field, record_type):
    """Raise TabpValidationError if field is absent from record."""
    if field not in record:
        raise TabpValidationError(
            "tabp: validation error: %s record missing required field '%s'"
            % (record_type, field)
        )


def _require_enum(record, field, allowed, record_type):
    """Raise TabpValidationError if record[field] is not in the allowed enum."""
    _require(record, field, record_type)
    if record[field] not in allowed:
        raise TabpValidationError(
            "tabp: validation error: %s.%s value %r not in allowed set %r"
            % (record_type, field, record[field], allowed)
        )


def _validate_run(record):
    """Validate a run record (run.schema.json).

    Required: run_id, skill, started_at, status, state_write_mode, usage,
              candidates_screened, jd_slug.
    Enum: status in {in_progress, completed, failed, interrupted}.
    Enum: state_write_mode in {helper, instructed}.
    Enum: usage.usage_source in {cowork, claude-code, estimate, unavailable}.
    Optional: usage.cost_basis in {actual, estimate, unavailable} (absent = ok).
    MAR-38: widened from two-value to four-value usage_source enum; added
            optional cost_basis check.
    """
    for field in ("run_id", "skill", "started_at", "status",
                  "state_write_mode", "usage", "candidates_screened", "jd_slug"):
        _require(record, field, "run")

    _require_enum(record, "status",
                  {"in_progress", "completed", "failed", "interrupted"}, "run")
    _require_enum(record, "state_write_mode", {"helper", "instructed"}, "run")

    usage = record.get("usage")
    if not isinstance(usage, dict):
        raise TabpValidationError(
            "tabp: validation error: run.usage must be an object"
        )
    _require_enum(usage, "usage_source",
                  {"cowork", "claude-code", "estimate", "unavailable"},
                  "run.usage")
    if "cost_basis" in usage:
        _require_enum(usage, "cost_basis",
                      {"actual", "estimate", "unavailable"},
                      "run.usage")


def _validate_evidence(record):
    """Validate an evidence record (evidence.schema.json).

    Required top-level: run_id, candidate_id, candidate_name, requirements,
                        score, band, recommendation, must_have_gate,
                        fairness_check_passed.
    Per-requirement: requirement, category, judgment, evidence (non-empty string, AC-4).
    Enum: band in {Strong, Moderate, Weak}.
    Enum: recommendation in {Recommend, Hold, Reject}.
    Pattern: must_have_gate matches ^(OK|Missing:.+)$.
    Range: score in [0, 100].
    """
    for field in ("run_id", "candidate_id", "candidate_name", "requirements",
                  "score", "band", "recommendation", "must_have_gate",
                  "fairness_check_passed"):
        _require(record, field, "evidence")

    _require_enum(record, "band", {"Strong", "Moderate", "Weak"}, "evidence")
    _require_enum(record, "recommendation", {"Recommend", "Hold", "Reject"}, "evidence")

    score = record.get("score")
    if (isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not (0 <= score <= 100)):
        raise TabpValidationError(
            "tabp: validation error: evidence.score must be a number in [0, 100]"
        )

    gate = record.get("must_have_gate", "")
    if not isinstance(gate, str) or not (
        gate == "OK" or (gate.startswith("Missing:") and len(gate) > len("Missing:"))
    ):
        raise TabpValidationError(
            "tabp: validation error: evidence.must_have_gate must match ^(OK|Missing:.+)$"
        )

    requirements = record.get("requirements")
    if not isinstance(requirements, list):
        raise TabpValidationError(
            "tabp: validation error: evidence.requirements must be an array"
        )
    for i, req in enumerate(requirements):
        if not isinstance(req, dict):
            raise TabpValidationError(
                "tabp: validation error: evidence.requirements[%d] must be an object" % i
            )
        for sub_field in ("requirement", "category", "judgment", "evidence"):
            if sub_field not in req:
                raise TabpValidationError(
                    "tabp: validation error: evidence.requirements[%d] missing required field '%s'"
                    % (i, sub_field)
                )
        # AC-4 enforcement gate: evidence must be non-empty string
        ev = req.get("evidence")
        if not isinstance(ev, str) or len(ev) == 0:
            raise TabpValidationError(
                "tabp: validation error: evidence.requirements[%d].evidence "
                "must be a non-empty string (AC-4: every judgment must cite source evidence)"
                % i
            )


def _validate_decision(record):
    """Validate a decision record (decision.schema.json).

    Required: run_id, verification_passed, presented_at.
    verification_passed must be bool.
    If sign_off is present and not null: must be dict with recruiter and confirmed_at.
    """
    for field in ("run_id", "verification_passed", "presented_at"):
        _require(record, field, "decision")

    if not isinstance(record.get("verification_passed"), bool):
        raise TabpValidationError(
            "tabp: validation error: decision.verification_passed must be a boolean"
        )

    sign_off = record.get("sign_off")
    if sign_off is not None:
        if not isinstance(sign_off, dict):
            raise TabpValidationError(
                "tabp: validation error: decision.sign_off must be an object or null"
            )
        for sub_field in ("recruiter", "confirmed_at"):
            if sub_field not in sign_off:
                raise TabpValidationError(
                    "tabp: validation error: decision.sign_off missing required field '%s'"
                    % sub_field
                )


def _validate_history(record):
    """Validate a history record (history.schema.json).

    Required: runs (list).
    Per-run summary: run_id, skill, started_at, status.
    """
    _require(record, "runs", "history")
    runs = record.get("runs")
    if not isinstance(runs, list):
        raise TabpValidationError(
            "tabp: validation error: history.runs must be an array"
        )
    for i, run in enumerate(runs):
        if not isinstance(run, dict):
            raise TabpValidationError(
                "tabp: validation error: history.runs[%d] must be an object" % i
            )
        for sub_field in ("run_id", "skill", "started_at", "status"):
            if sub_field not in run:
                raise TabpValidationError(
                    "tabp: validation error: history.runs[%d] missing required field '%s'"
                    % (i, sub_field)
                )


def _validate_lock(record):
    """Validate a lock record (lock.schema.json).

    Required: pid (int, >= 1), hostname (str), created_at (str, non-empty).
    """
    _require(record, "pid", "lock")
    _require(record, "hostname", "lock")
    _require(record, "created_at", "lock")

    pid = record.get("pid")
    if not isinstance(pid, int) or pid < 1:
        raise TabpValidationError(
            "tabp: validation error: lock.pid must be an integer >= 1"
        )
    hostname = record.get("hostname")
    if not isinstance(hostname, str) or len(hostname) == 0:
        raise TabpValidationError(
            "tabp: validation error: lock.hostname must be a non-empty string"
        )
    created_at = record.get("created_at")
    if not isinstance(created_at, str) or len(created_at) == 0:
        raise TabpValidationError(
            "tabp: validation error: lock.created_at must be a non-empty string"
        )


def _validate_record(record, record_type):
    """Dispatch validation to the type-specific validator.

    record_type: 'run' | 'evidence' | 'decision' | 'history' | 'lock'
    Raises TabpValidationError on any validation failure.
    """
    dispatch = {
        "run": _validate_run,
        "evidence": _validate_evidence,
        "decision": _validate_decision,
        "history": _validate_history,
        "lock": _validate_lock,
    }
    if record_type not in dispatch:
        raise TabpValidationError(
            "tabp: validation error: unknown record_type '%s'" % record_type
        )
    dispatch[record_type](record)


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


def _tabp_dir_from_project(project_dir):
    """Return the .tabp/ directory path for a given project dir."""
    return os.path.join(project_dir, ".tabp")


def _run_dir(tabp_dir, run_id):
    """Return the runs/<run-id>/ directory path."""
    return os.path.join(tabp_dir, "runs", run_id)


def _cmd_run_start(args):
    """run-start subcommand.

    Args: --project-dir <path> --skill <name> [--jd-slug <slug>]
          [--state-write-mode <helper|instructed>]

    Allocates run_id = "run-" + _now_iso(), acquires lock, writes initial
    run.json (status=in_progress), appends summary to history.json.
    Prints run_id to stdout. Design ref: design.md:253, 754.
    """
    import argparse
    parser = argparse.ArgumentParser(prog="tabp_helper run-start")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--skill", required=True)
    parser.add_argument("--jd-slug", default="")
    parser.add_argument("--state-write-mode", default="helper",
                        choices=["helper", "instructed"])
    parsed = parser.parse_args(args)

    project_dir = parsed.project_dir
    tabp_dir = _tabp_dir_from_project(project_dir)
    os.makedirs(tabp_dir, exist_ok=True)

    run_id = "run-" + _run_stamp()

    # Acquire the lock BEFORE creating any run artifacts, so a run blocked by a
    # live foreign lock leaves no orphaned runs/<run-id>/ directory behind.
    _acquire_lock(tabp_dir, run_id)

    run_dir = _run_dir(tabp_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)

    started_at = _now_iso()
    run_record = {
        "run_id": run_id,
        "skill": parsed.skill,
        "started_at": started_at,
        "ended_at": None,
        "status": "in_progress",
        "stop_reason": None,
        "state_write_mode": parsed.state_write_mode,
        "usage": {
            "usage_source": "unavailable",
            "tokens_in": None,
            "tokens_out": None,
            "cost_usd": None,
            "duration_seconds": None,
        },
        "candidates_screened": 0,
        "jd_slug": parsed.jd_slug,
        "scorecard_file": None,
    }
    _write_json(os.path.join(run_dir, "run.json"), run_record)

    history_path = os.path.join(tabp_dir, "history.json")
    _append_run_to_history(history_path, {
        "run_id": run_id,
        "skill": parsed.skill,
        "started_at": started_at,
        "status": "in_progress",
        "candidates_screened": 0,
        "jd_slug": parsed.jd_slug,
    })

    sys.stdout.write(run_id + "\n")


def _cmd_state_write(args):
    """state-write subcommand.

    Args: --project-dir <path> --run-id <id> --file <dest-path>
          --data-file <json-file>

    Reads JSON from --data-file, validates with _validate_evidence, writes
    atomically to --file. Design ref: design.md:257, 759.
    """
    import argparse
    parser = argparse.ArgumentParser(prog="tabp_helper state-write")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--file", required=True, dest="dest_file")
    parser.add_argument("--data-file", required=True)
    parsed = parser.parse_args(args)

    with open(parsed.data_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    _validate_evidence(data)
    _write_json(parsed.dest_file, data)


def _cmd_decision_write(args):
    """decision-write subcommand.

    Args: --project-dir <path> --run-id <id>
          --verification-passed <true|false>
          [--verification-notes <text>]

    Writes decision.json with verification_passed, verification_notes,
    presented_at, sign_off=null. Validates with _validate_decision.
    Design ref: design.md:263, 769.
    """
    import argparse
    parser = argparse.ArgumentParser(prog="tabp_helper decision-write")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--verification-passed", required=True)
    parser.add_argument("--verification-notes", default=None)
    parsed = parser.parse_args(args)

    vp_str = parsed.verification_passed.lower()
    if vp_str == "true":
        verification_passed = True
    elif vp_str == "false":
        verification_passed = False
    else:
        sys.stderr.write("tabp: error: --verification-passed must be 'true' or 'false'\n")
        sys.exit(EXIT_ERROR)

    tabp_dir = _tabp_dir_from_project(parsed.project_dir)
    run_dir = _run_dir(tabp_dir, parsed.run_id)
    os.makedirs(run_dir, exist_ok=True)

    decision_record = {
        "run_id": parsed.run_id,
        "verification_passed": verification_passed,
        "verification_notes": parsed.verification_notes,
        "presented_at": _now_iso(),
        "sign_off": None,
    }
    _validate_decision(decision_record)
    _write_json(os.path.join(run_dir, "decision.json"), decision_record)


def _cmd_sign_off_write(args):
    """sign-off-write subcommand.

    Args: --project-dir <path> --run-id <id> --recruiter <name>
          [--notes <text>]

    Reads existing decision.json, populates sign_off block
    (recruiter, confirmed_at, optional notes), writes back atomically.
    Design ref: design.md:263, 773.
    """
    import argparse
    parser = argparse.ArgumentParser(prog="tabp_helper sign-off-write")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--recruiter", required=True)
    parser.add_argument("--notes", default=None)
    parsed = parser.parse_args(args)

    tabp_dir = _tabp_dir_from_project(parsed.project_dir)
    decision_path = os.path.join(_run_dir(tabp_dir, parsed.run_id), "decision.json")

    decision = _read_json(decision_path)
    if not isinstance(decision, dict):
        sys.stderr.write(
            "tabp: error: decision.json not found at %s\n" % decision_path
        )
        sys.exit(EXIT_ERROR)

    sign_off = {
        "recruiter": parsed.recruiter,
        "confirmed_at": _now_iso(),
    }
    if parsed.notes is not None:
        sign_off["notes"] = parsed.notes

    decision["sign_off"] = sign_off
    _write_json(decision_path, decision)


def _cmd_run_finalize(args):
    """run-finalize subcommand.

    Args: --project-dir <path> --run-id <id>
          --status <completed|failed|interrupted>
          [--candidates-screened <n>]
          [--usage-source <cowork|claude-code|estimate|unavailable>]
          [--tokens-in <int>]
          [--tokens-out <int>]
          [--cost-basis <actual|estimate|unavailable>]
          [--stop-reason <text>]

    Updates run.json (status, ended_at, optional fields), updates matching
    history entry, releases lock. Validates run.json with _validate_run.
    MAR-38: widened --usage-source to four values; added --tokens-in/out/cost-basis.
    Design ref: design.md:263, 775.
    """
    import argparse
    parser = argparse.ArgumentParser(prog="tabp_helper run-finalize")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--status", required=True,
                        choices=["completed", "failed", "interrupted"])
    parser.add_argument("--candidates-screened", type=int, default=None)
    parser.add_argument("--usage-source", default=None,
                        choices=["cowork", "claude-code", "estimate", "unavailable"])
    parser.add_argument("--tokens-in", type=int, default=None,
                        dest="tokens_in")
    parser.add_argument("--tokens-out", type=int, default=None,
                        dest="tokens_out")
    parser.add_argument("--cost-basis", default=None,
                        choices=["actual", "estimate", "unavailable"],
                        dest="cost_basis")
    parser.add_argument("--stop-reason", default=None)
    parsed = parser.parse_args(args)

    tabp_dir = _tabp_dir_from_project(parsed.project_dir)
    run_dir = _run_dir(tabp_dir, parsed.run_id)
    run_path = os.path.join(run_dir, "run.json")

    run_record = _read_json(run_path)
    if not isinstance(run_record, dict):
        sys.stderr.write(
            "tabp: error: run.json not found at %s\n" % run_path
        )
        sys.exit(EXIT_ERROR)

    ended_at = _now_iso()
    run_record["status"] = parsed.status
    run_record["ended_at"] = ended_at
    if parsed.stop_reason is not None:
        run_record["stop_reason"] = parsed.stop_reason
    if parsed.candidates_screened is not None:
        run_record["candidates_screened"] = parsed.candidates_screened
    if parsed.usage_source is not None:
        run_record.setdefault("usage", {})["usage_source"] = parsed.usage_source
    if parsed.tokens_in is not None:
        run_record.setdefault("usage", {})["tokens_in"] = parsed.tokens_in
    if parsed.tokens_out is not None:
        run_record.setdefault("usage", {})["tokens_out"] = parsed.tokens_out
    if parsed.cost_basis is not None:
        run_record.setdefault("usage", {})["cost_basis"] = parsed.cost_basis

    _validate_run(run_record)
    _write_json(run_path, run_record)

    history_path = os.path.join(tabp_dir, "history.json")
    history_updates = {
        "status": parsed.status,
        "ended_at": ended_at,
    }
    if parsed.candidates_screened is not None:
        history_updates["candidates_screened"] = parsed.candidates_screened
    if parsed.usage_source is not None:
        history_updates["usage_source"] = parsed.usage_source
    _update_run_in_history(
        history_path, parsed.run_id, history_updates,
        fallback={
            "skill": run_record.get("skill"),
            "started_at": run_record.get("started_at"),
        },
    )

    _release_lock(tabp_dir, parsed.run_id)


def _cmd_run_status(args):
    """run-status subcommand.

    Args: --project-dir <path>

    Reads history.json, finds latest entry with status=in_progress (i.e.
    runs[-1] if its status is in_progress). Prints resume context JSON to
    stdout: run_id, started_at, candidates_screened, evidence file list.
    Exit 0 if found; exit 1 if no in_progress run.
    Design ref: design.md:263, 800-802.
    """
    import argparse
    parser = argparse.ArgumentParser(prog="tabp_helper run-status")
    parser.add_argument("--project-dir", required=True)
    parsed = parser.parse_args(args)

    tabp_dir = _tabp_dir_from_project(parsed.project_dir)
    history_path = os.path.join(tabp_dir, "history.json")
    history = _read_history(history_path)
    runs = history.get("runs", [])

    # Check runs[-1] first; if it is in_progress, that is the current run.
    in_progress = None
    if runs and runs[-1].get("status") == "in_progress":
        in_progress = runs[-1]

    if in_progress is None:
        sys.stderr.write("tabp: no in_progress run found in history.json\n")
        sys.exit(EXIT_ERROR)

    run_id = in_progress.get("run_id", "")
    run_evidence_dir = os.path.join(tabp_dir, "runs", run_id)
    evidence_files = []
    if os.path.isdir(run_evidence_dir):
        for fname in sorted(os.listdir(run_evidence_dir)):
            if fname.startswith("evidence-") and fname.endswith(".json"):
                evidence_files.append(os.path.join(run_evidence_dir, fname))

    result = {
        "run_id": run_id,
        "started_at": in_progress.get("started_at"),
        "candidates_screened": in_progress.get("candidates_screened", 0),
        "evidence_files": evidence_files,
    }
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


def _cmd_validate(args):
    """validate subcommand.

    Args: --project-dir <path> --run-id <id>
          --type <run|evidence|decision|history|lock> --file <path>

    Reads JSON from --file, runs _validate_record, prints {"ok": true} on
    success or exits non-zero with {"ok": false, "error": "<msg>"} on failure.
    Design ref: design.md:241, 275.
    """
    import argparse
    parser = argparse.ArgumentParser(prog="tabp_helper validate")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--type", required=True, dest="record_type",
                        choices=["run", "evidence", "decision", "history", "lock"])
    parser.add_argument("--file", required=True)
    parsed = parser.parse_args(args)

    with open(parsed.file, "r", encoding="utf-8") as fh:
        record = json.load(fh)

    try:
        _validate_record(record, parsed.record_type)
        sys.stdout.write(json.dumps({"ok": True}) + "\n")
    except TabpValidationError as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}) + "\n")
        sys.exit(EXIT_VALIDATION_FAILED)


def _cmd_usage_read(args):
    """usage-read subcommand — real aggregation (MAR-38).

    Args: --project-dir <path> [--run-id <id>|all]

    Reads history.json and per-run run.json records; aggregates token counts,
    cost, and candidate totals. Emits the documented output shape to stdout.
    Read-only: no _write_json calls, no history mutations, no transcript writes.

    Output shape: total_runs, completed_runs, failed_runs,
    total_candidates_screened, total_duration_seconds, total_tokens_in,
    total_tokens_out, total_cost_usd, cost_basis, pricing_snapshot_date,
    usage_note, runs[].

    Design ref: design.md:307-348, :456-491. MAR-38 replaces the MAR-6 stub.
    """
    import argparse
    parser = argparse.ArgumentParser(prog="tabp_helper usage-read")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--run-id", default=None, dest="run_id")
    parsed = parser.parse_args(args)

    project_dir = parsed.project_dir
    tabp_dir = _tabp_dir_from_project(project_dir)

    # Step 1: Read settings + resolve pricing
    settings_path = os.path.join(tabp_dir, "settings.json")
    file_settings = _read_json(settings_path)
    settings = dict(_SETTINGS_DEFAULTS)
    if isinstance(file_settings, dict):
        for key in _SETTINGS_DEFAULTS:
            if key in file_settings:
                settings[key] = file_settings[key]
        if "model_pricing" in file_settings:
            settings["model_pricing"] = file_settings["model_pricing"]
    pricing, snapshot_date = _resolve_pricing(settings)

    # Step 2: Read history
    history_path = os.path.join(tabp_dir, "history.json")
    history = _read_history(history_path)
    all_runs = history.get("runs", [])

    # Step 3: Filter runs
    run_id_filter = parsed.run_id
    if run_id_filter and run_id_filter != "all":
        filtered_runs = [r for r in all_runs if r.get("run_id") == run_id_filter]
    else:
        filtered_runs = all_runs

    # Step 4: Determine transcript root (injectable via TABP_TRANSCRIPT_ROOT env)
    transcript_root = os.environ.get(
        "TABP_TRANSCRIPT_ROOT",
        os.path.expanduser("~/.claude/projects")
    )
    cwd_slug = _cwd_slug(project_dir)

    # Step 5: Process each run
    runs_output = []
    agg_total_runs = 0
    agg_completed = 0
    agg_failed = 0
    agg_candidates = 0
    agg_duration = 0.0
    agg_tokens_in = 0
    agg_tokens_out = 0
    agg_cost = 0.0
    cost_basis_flags = set()  # tracks which cost_basis values appear in non-unavailable runs

    for hist_entry in filtered_runs:
        run_id = hist_entry.get("run_id", "")
        run_dir = _run_dir(tabp_dir, run_id)
        run_path = os.path.join(run_dir, "run.json")

        run_record = _read_json(run_path)
        if not isinstance(run_record, dict):
            # Missing or corrupt run.json — skip entirely (design.md step 5b)
            continue

        usage = run_record.get("usage") or {}
        usage_source = usage.get("usage_source", "unavailable")
        cost_basis = usage.get("cost_basis", "unavailable")
        status = run_record.get("status", "")
        candidates = run_record.get("candidates_screened", 0) or 0
        duration = usage.get("duration_seconds")
        started_at = run_record.get("started_at")
        ended_at = run_record.get("ended_at")

        # Per-source dispatch (design.md step 5e)
        tokens_in = None
        tokens_out = None
        cost_usd = None
        run_note = ""

        if usage_source == "claude-code":
            # Read actuals from Claude Code transcript (injectable root, privacy-safe)
            t_in, t_out, model = _read_transcript_tokens(
                transcript_root, cwd_slug, started_at, ended_at
            )
            if t_in > 0 or t_out > 0:
                tokens_in = t_in
                tokens_out = t_out
            else:
                # Transcript dir absent or empty — fall back to run.json tokens
                tokens_in = usage.get("tokens_in")
                tokens_out = usage.get("tokens_out")
                model = None
            cost_usd = _derive_cost(tokens_in, tokens_out, model, pricing)
            cost_basis = "estimate"  # always derived, never self-reported (AC-2)
            run_note = "Tokens: actuals from Claude Code transcript. Cost: derived estimate."

        elif usage_source == "estimate":
            tokens_in = usage.get("tokens_in")
            tokens_out = usage.get("tokens_out")
            model = None
            cost_usd = _derive_cost(tokens_in, tokens_out, model, pricing)
            cost_basis = "estimate"
            run_note = "Token estimate; cost derived via pricing snapshot."

        elif usage_source == "cowork":
            tokens_in = usage.get("tokens_in")
            tokens_out = usage.get("tokens_out")
            cost_usd = usage.get("cost_usd")
            cost_basis = "actual"  # self-reported by runtime (forward hook)
            run_note = "Cowork self-reported usage."

        else:  # unavailable
            tokens_in = None
            tokens_out = None
            cost_usd = None
            cost_basis = "unavailable"
            run_note = "Usage data unavailable for this run."

        # Build per-run row (always included in runs[])
        run_row = {
            "run_id": run_id,
            "started_at": started_at,
            "status": status,
            "candidates_screened": candidates,
            "duration_seconds": duration,
            "usage_source": usage_source,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "cost_basis": cost_basis,
            "usage_note": run_note,
        }
        runs_output.append(run_row)

        # Aggregate totals (counters)
        agg_total_runs += 1
        if status == "completed":
            agg_completed += 1
        elif status in ("failed", "interrupted"):
            agg_failed += 1
        agg_candidates += candidates
        agg_duration += (duration or 0.0)

        # Omit unavailable from token/cost totals (design.md:344)
        if usage_source != "unavailable":
            agg_tokens_in += (tokens_in or 0)
            agg_tokens_out += (tokens_out or 0)
            agg_cost += (cost_usd or 0.0)
            cost_basis_flags.add(cost_basis)

    # Step 6: Aggregate cost_basis determination
    if "actual" in cost_basis_flags:
        agg_cost_basis = "actual"
    elif "estimate" in cost_basis_flags:
        agg_cost_basis = "estimate"
    else:
        agg_cost_basis = "unavailable"

    # Step 7: Build usage_note
    usage_note = (
        "Cost is a derived estimate (tokens x pricing table snapshot %s). "
        "Token counts are actuals from Claude Code transcript where available; "
        "estimate otherwise. Unavailable runs excluded from totals."
        % snapshot_date
    )

    # Step 8: Emit output (read-only — no _write_json calls)
    output = {
        "total_runs": agg_total_runs,
        "completed_runs": agg_completed,
        "failed_runs": agg_failed,
        "total_candidates_screened": agg_candidates,
        "total_duration_seconds": agg_duration,
        "total_tokens_in": agg_tokens_in,
        "total_tokens_out": agg_tokens_out,
        "total_cost_usd": agg_cost,
        "cost_basis": agg_cost_basis,
        "pricing_snapshot_date": snapshot_date,
        "usage_note": usage_note,
        "runs": runs_output,
    }
    sys.stdout.write(json.dumps(output, indent=2, ensure_ascii=False) + "\n")


# Documented tabp settings defaults. Mirrors the screen-cvs SKILL.md step-1
# fallback values so settings-read and the skill agree on the defaults.
_SETTINGS_DEFAULTS = {
    "screening_model": "sonnet",
    "synthesis_model": "opus",
    "cv_folder": "./cvs",
    "jd_folder": "./jds",
    "state_write_mode": "helper",
}

# ---------------------------------------------------------------------------
# Pricing snapshot (Spec 02 — MAR-38)
# Built-in dated pricing table; settings model_pricing may override per model.
# Privacy: pricing holds ONLY model names + numeric prices. No credentials.
# ---------------------------------------------------------------------------

_PRICING_SNAPSHOT_DATE = "2025-08-01"
"""Date of the built-in pricing snapshot (YYYY-MM-DD). Surfaced in usage-read."""

_MODEL_PRICING = {
    "claude-opus-4-8":   {"input_per_mtok": 15.00, "output_per_mtok": 75.00},
    "claude-sonnet-4-6": {"input_per_mtok":  3.00, "output_per_mtok": 15.00},
}
"""Built-in pricing snapshot (USD per million tokens). Override via settings.json."""


def _resolve_pricing(settings):
    """Resolve the effective pricing dict and snapshot date.

    Args:
        settings (dict): resolved settings dict (may contain 'model_pricing').

    Returns:
        (pricing_dict, snapshot_date) where pricing_dict is a copy of
        _MODEL_PRICING with any valid settings overrides applied.

    Layering: settings model_pricing entries override the snapshot, per model.
    Malformed or non-numeric entries are silently skipped (R5 additive safety).
    The snapshot_date is always _PRICING_SNAPSHOT_DATE regardless of overrides.
    Privacy: only numeric prices and string model names are ever stored.
    """
    import copy as _copy
    pricing = _copy.deepcopy(_MODEL_PRICING)
    model_pricing = settings.get("model_pricing") if isinstance(settings, dict) else None
    if isinstance(model_pricing, dict):
        for model, entry in model_pricing.items():
            if not isinstance(entry, dict):
                continue  # skip malformed entries
            in_p = entry.get("input_per_mtok")
            out_p = entry.get("output_per_mtok")
            if not isinstance(in_p, (int, float)) or isinstance(in_p, bool):
                continue  # non-numeric — silently skip
            if not isinstance(out_p, (int, float)) or isinstance(out_p, bool):
                continue  # non-numeric — silently skip
            pricing[model] = {"input_per_mtok": float(in_p), "output_per_mtok": float(out_p)}
    return pricing, _PRICING_SNAPSHOT_DATE


def _cwd_slug(project_dir):
    """Convert a project directory absolute path to a Claude Code cwd slug.

    The cwd slug format used in ~/.claude/projects/ replaces '/' with '-'
    and strips a leading '-'. Example: '/Users/bob/myapp' -> 'Users-bob-myapp'.

    Privacy: returns a path-derived string only — no content, no credentials.
    """
    slug = project_dir.replace("/", "-")
    if slug.startswith("-"):
        slug = slug[1:]
    return slug


def _read_transcript_tokens(transcript_root, cwd_slug, started_at=None, ended_at=None):
    """Read token counts from Claude Code JSONL transcript files.

    Scans *.jsonl files in transcript_root/<cwd_slug>/ and accumulates
    message.usage.input_tokens and message.usage.output_tokens (integers only).
    Also tracks the last non-None message.model seen.

    Privacy guarantee (design.md:50): reads ONLY integer token counts and
    the model name string. Never reads message.content, prompt text, CV
    content, or response body. Returns ONLY (int, int, str|None).

    Args:
        transcript_root (str): path to the Claude Code projects root
            (injectable — tests NEVER use the real ~/.claude path).
        cwd_slug (str): cwd slug for the project (e.g. 'Users-bob-myapp').
        started_at (str|None): ISO-8601 start time for filtering (not yet used).
        ended_at (str|None): ISO-8601 end time for filtering (not yet used).

    Returns:
        (total_in, total_out, model_name_or_None)
        Returns (0, 0, None) when the transcript directory does not exist
        (auto-detect: directory presence signals whether Claude Code path applies).
    """
    import glob as _glob
    transcript_dir = os.path.join(transcript_root, cwd_slug)
    if not os.path.isdir(transcript_dir):
        return (0, 0, None)

    total_in = 0
    total_out = 0
    last_model = None

    for jsonl_path in sorted(_glob.glob(os.path.join(transcript_dir, "*.jsonl"))):
        try:
            with open(jsonl_path, "r", encoding="utf-8") as fh:
                for raw_line in fh:
                    try:
                        obj = json.loads(raw_line)
                    except (json.JSONDecodeError, ValueError):
                        continue  # corrupt line — skip
                    message = obj.get("message")
                    if not isinstance(message, dict):
                        continue
                    usage = message.get("usage")
                    if not isinstance(usage, dict):
                        continue
                    # Privacy: ONLY read integer token counts
                    in_tok = usage.get("input_tokens", 0)
                    out_tok = usage.get("output_tokens", 0)
                    if isinstance(in_tok, int) and not isinstance(in_tok, bool):
                        total_in += in_tok
                    if isinstance(out_tok, int) and not isinstance(out_tok, bool):
                        total_out += out_tok
                    # Track last non-None model name
                    model_name = message.get("model")
                    if model_name is not None:
                        last_model = model_name
        except OSError:
            continue  # unreadable file — skip

    return (total_in, total_out, last_model)


def _derive_cost(tokens_in, tokens_out, model, pricing):
    """Compute derived cost in USD from token counts and pricing table.

    Args:
        tokens_in (int|None): input token count.
        tokens_out (int|None): output token count.
        model (str|None): model name (e.g. 'claude-opus-4-8').
        pricing (dict): pricing dict from _resolve_pricing.

    Returns:
        float: derived cost in USD, or None if model is unknown or tokens are None.

    Cost is ALWAYS derived (tokens x pricing) — never self-reported.
    Unknown model returns None; caller labels cost_basis accordingly.
    """
    if tokens_in is None or tokens_out is None:
        return None
    if model not in pricing:
        return None
    entry = pricing[model]
    return (tokens_in / 1_000_000) * entry["input_per_mtok"]          + (tokens_out / 1_000_000) * entry["output_per_mtok"]


def _cmd_settings_read(args):
    """settings-read subcommand.

    Args: --project-dir <path>

    Resolves tabp settings from <project>/.tabp/settings.json layered over the
    documented defaults (_SETTINGS_DEFAULTS), and prints the resolved settings
    as JSON to stdout. A missing or corrupt settings file falls back to the
    defaults (never raises), so the screen-cvs coordinator always gets a usable
    settings object. Only known keys are honoured. This is the foundation
    reader; the writable settings surface is owned by the tabp upgrade epic.
    """
    import argparse
    parser = argparse.ArgumentParser(prog="tabp_helper settings-read")
    parser.add_argument("--project-dir", required=True)
    parsed = parser.parse_args(args)

    tabp_dir = _tabp_dir_from_project(parsed.project_dir)
    settings_path = os.path.join(tabp_dir, "settings.json")

    resolved = dict(_SETTINGS_DEFAULTS)
    file_settings = _read_json(settings_path)
    if isinstance(file_settings, dict):
        for key in _SETTINGS_DEFAULTS:
            if key in file_settings:
                resolved[key] = file_settings[key]
        # MAR-38: pass through model_pricing if present (runtime-read-only; no schema file, DEV-1)
        if "model_pricing" in file_settings:
            resolved["model_pricing"] = file_settings["model_pricing"]

    sys.stdout.write(json.dumps(resolved, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    """Dispatch on sys.argv[1] to the appropriate subcommand."""
    if len(sys.argv) < 2:
        sys.stderr.write(
            "tabp_helper: usage: tabp_helper.py <subcommand> [args]\n"
            "Subcommands: run-start, state-write, decision-write, sign-off-write, "
            "run-finalize, run-status, validate, usage-read, settings-read\n"
        )
        sys.exit(EXIT_ERROR)

    subcommand = sys.argv[1]
    rest = sys.argv[2:]

    try:
        if subcommand == "run-start":
            _cmd_run_start(rest)
        elif subcommand == "state-write":
            _cmd_state_write(rest)
        elif subcommand == "decision-write":
            _cmd_decision_write(rest)
        elif subcommand == "sign-off-write":
            _cmd_sign_off_write(rest)
        elif subcommand == "run-finalize":
            _cmd_run_finalize(rest)
        elif subcommand == "run-status":
            _cmd_run_status(rest)
        elif subcommand == "validate":
            _cmd_validate(rest)
        elif subcommand == "usage-read":
            _cmd_usage_read(rest)
        elif subcommand == "settings-read":
            _cmd_settings_read(rest)
        else:
            sys.stderr.write(
                "tabp_helper: unknown subcommand '%s'\n" % subcommand
            )
            sys.exit(EXIT_ERROR)
    except TabpLockError as exc:
        sys.stderr.write("%s\n" % exc)
        sys.exit(EXIT_LOCK_BLOCKED)
    except TabpValidationError as exc:
        sys.stderr.write("%s\n" % exc)
        sys.exit(EXIT_VALIDATION_FAILED)
    except SystemExit:
        raise
    except Exception as exc:
        sys.stderr.write("tabp_helper: error: %s\n" % exc)
        sys.exit(EXIT_ERROR)


if __name__ == "__main__":
    main()
