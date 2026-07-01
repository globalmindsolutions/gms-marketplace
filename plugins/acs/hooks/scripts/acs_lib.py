"""acs_lib — shared, stdlib-only library for the acs plugin's hooks and helper scripts.

Python 3.9+, standard library only (no pip installs on consumer machines).

This module implements the deterministic half of the acs workflow:
  * settings resolution   (~/.acs/settings.json <- <repo>/.acs/settings.json <- settings.local.json)
  * workspace layout      (<workspace>/<repo>/<ticket-id>/ partitions + repo-level files)
  * ticket id resolution  (explicit argument -> per-checkout pointer file -> branch name)
  * state files           (append-only `runs`, last entry = current state)
  * pipeline ledger       (pipeline-state.json), tickets-index.json, counters.json, metrics.json
  * locking               (.lock per ticket partition, re-entrant per checkout)
  * pre-hook gating       (exit 2 = blocked) and post-hook persistence

Hook event binding (resolves the open question in docs/requirements/hooks.md):
  * pre-<skill>.py  runs via a PreToolUse hook matching the Skill tool (dispatch.py routes
    by skill name); exit code 2 blocks the skill before it runs.
  * post-<skill>.py is invoked by the skill's coordinator as its mandatory final step
    (it needs run data only the coordinator knows: status, findings, tokens, cost).
    The next skill's pre-hook gates on runs[-1].status, so a skipped post-hook can
    never unlock the pipeline.
  * A SessionEnd hook finalizes any run left `in_progress` by this checkout as
    `interrupted` and releases its lock, so abnormal endings still write state.
"""

import fnmatch
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PRODUCT_SKILLS = ["create-prd", "create-architecture", "create-project"]
WORKFLOW_SKILLS = ["create-ticket", "create-design", "create-spec", "code", "create-pr", "merge-pr"]
HOOKED_SKILLS = PRODUCT_SKILLS + WORKFLOW_SKILLS
UNHOOKED_SKILLS = ["init", "ship", "handoff", "update", "install-hooks", "metrics", "usage"]

RUN_STATUSES = ["in_progress", "completed", "failed", "interrupted", "handed_off"]
TICKET_TYPES = ["epic", "story", "task"]
TICKET_STATUSES = ["open", "in_progress", "in_review", "done"]
PRIORITIES = ["critical", "high", "medium", "low"]

PRODUCT_TICKET_TITLES = {
    "create-prd": "Product definition (PRD)",
    "create-architecture": "Product architecture doc set",
    "create-project": "Project scaffold",
}

# Placeholder vocabulary per inline format field (docs/requirements/configuration.md).
FORMAT_PLACEHOLDERS = {
    "branch_name": {"ticket_id", "type", "slug", "external_key"},
    "commit_message": {"ticket_id", "type", "summary", "external_key"},
    "pr_title": {"ticket_id", "type", "title", "summary", "external_key"},
    "ticket_title": {"ticket_id", "type", "title", "external_key"},
}

BUILTIN_TEMPLATES = {"pr-default", "epic-default", "story-default", "task-default"}


# ---------------------------------------------------------------------------
# Classification routing
# ---------------------------------------------------------------------------

def derive_lane(size, stakes, needs_design, ticket_type):
    """Deterministic lane routing: maps size x stakes axes + flags to a pipeline lane.

    Rule evaluation order (fixed, per design.md:553-565):
      Rule 1 (type override):     epic -> COMPLEX
      Rule 2 (size=large):        large -> COMPLEX
      Rule 3 (high-stakes floor): stakes=high -> STANDARD (size<=standard floor)
      Rule 4 (needs_design):      needs_design=True -> at least STANDARD
      Rule 5 (size dispatch):     standard->STANDARD, small->SMALL, trivial->TRIVIAL
      Rule 6 (default):           STANDARD (conservative fallback for absent/unknown)

    Returns one of: 'TRIVIAL', 'SMALL', 'STANDARD', 'COMPLEX'.
    Pure function; no side effects; stdlib only.
    """
    if ticket_type == "epic":
        return "COMPLEX"
    if size == "large":
        return "COMPLEX"
    if stakes == "high":
        return "STANDARD"
    if needs_design:
        return "STANDARD"
    if size == "standard":
        return "STANDARD"
    if size == "small":
        return "SMALL"
    if size == "trivial":
        return "TRIVIAL"
    return "STANDARD"  # conservative fallback for absent/unknown size


def verify_depth(lane, stakes):
    """Return "light" or "full" verify depth for the ticket's lane and stakes.

    Truth table (design.md D4 / C-9):
      lane=TRIVIAL,  stakes=low    -> "light"
      lane=TRIVIAL,  stakes=normal -> "light"
      lane=SMALL,    stakes=low    -> "light"
      lane=SMALL,    stakes=normal -> "light"
      lane=STANDARD, stakes=*      -> "full"
      lane=COMPLEX,  stakes=*      -> "full"
      any lane,      stakes=high   -> "full"  (stakes floor, AC-2)
      lane=None/unknown/absent     -> "full"  (conservative default, invariant c)

    Check stakes == "high" FIRST (floor cannot be bypassed by lane value).
    Only the exact string "high" triggers the floor; None and other strings do not.
    Only exact uppercase lane values TRIVIAL/SMALL/STANDARD/COMPLEX are recognized;
    any other string (including lowercase) is treated as unknown -> "full".

    Pure function; no I/O, no side effects; stdlib only.
    """
    # Stakes floor: high stakes always yields full regardless of lane (AC-2)
    if stakes == "high":
        return "full"
    # Lane dispatch: recognized fast-lane values
    if lane in ("TRIVIAL", "SMALL"):
        return "light"
    # Recognized full-lane values (conservative for absent/unknown lane too)
    return "full"


VERIFY_ITERATION_CAP: dict = {"light": 1, "full": 3}
"""Iteration cap keyed by verify depth (AC-3: light=1; AC-4: full=3).

Used by the /acs:code coordinator to bound the reflection loop:
  depth = verify_depth(ticket.lane, ticket.stakes)
  ceiling = VERIFY_ITERATION_CAP[depth]
"""


# ---------------------------------------------------------------------------
# Lane-rank primitives (MAR-57 / ADR 0030)
# ---------------------------------------------------------------------------

LANE_ORDER: list = ["TRIVIAL", "SMALL", "STANDARD", "COMPLEX"]
"""Canonical lane ordering from lowest to highest rigor (ADR 0030).

Index 0 = TRIVIAL (lowest) … index 3 = COMPLEX (highest).
Used by lane_rank() for comparisons only; never use this list to produce
a lane value — derive_lane() is the single authoritative producer (ADR 0030:56-61).
"""


def lane_rank(lane):
    """Return the integer rank of *lane* in LANE_ORDER (0=TRIVIAL … 3=COMPLEX).

    Rule evaluation order:
      - Recognized uppercase lane value ('TRIVIAL', 'SMALL', 'STANDARD', 'COMPLEX')
        -> its index in LANE_ORDER.
      - Absent (None), empty, or any unrecognized string (including lowercase)
        -> 2 (STANDARD rank, conservative floor — design.md invariant (c) / AC-7).

    This function is a *comparison helper* only: it never produces a lane value.
    The single authoritative producer remains derive_lane() (ADR 0030:56-61).
    Pure function; no I/O, no side effects; stdlib only.
    """
    try:
        return LANE_ORDER.index(lane)
    except (ValueError, TypeError):
        return LANE_ORDER.index("STANDARD")  # conservative floor for absent/unknown


def escalate_lane(current_lane, size, stakes, needs_design, ticket_type, settings=None):
    """Return the higher of (current_lane, candidate) as a (lane, depth, ceiling) triple.

    The candidate lane is computed exclusively via derive_lane(size, stakes,
    needs_design, ticket_type) — never hand-set (ADR 0030:56-61 / AC-4).

    Clamp semantics (upward-only, AC-1 / AC-3 / AC-7):
      - candidate rank > current rank -> escalate: return candidate lane.
      - candidate rank <= current rank -> hold: return current_lane unchanged.
      - current_lane is None/unknown -> treated as STANDARD rank (2) for comparison,
        conservative floor: a COMPLEX candidate still fires; TRIVIAL/SMALL do not.

    The returned triple is always consistent:
      lane    — the higher of current_lane or candidate (string)
      depth   — verify_depth(lane, stakes)
      ceiling — VERIFY_ITERATION_CAP[depth]

    Pure function: no file I/O, no state mutations, no side effects.
    Mirrors recommend_stakes() (acs_lib.py: "Pure function — never writes
    stakes to ticket.json or any state file").
    """
    candidate_lane = derive_lane(size, stakes, needs_design, ticket_type)
    if lane_rank(candidate_lane) > lane_rank(current_lane):
        result_lane = candidate_lane
    else:
        # Hold at current; for None/unknown current_lane fall back to the STANDARD
        # floor (the conservative default, not the candidate — AC-7 invariant (c)).
        result_lane = current_lane if current_lane in LANE_ORDER else "STANDARD"
    depth = verify_depth(result_lane, stakes)
    ceiling = VERIFY_ITERATION_CAP[depth]
    return result_lane, depth, ceiling


# Axis ordering for guard_axes (MAR-57 Spec 03 / design.md:29 invariant (e)).
_SIZE_ORDER: list = ["trivial", "small", "standard", "large"]
_STAKES_ORDER: list = ["low", "normal", "high"]


def guard_axes(current_size, current_stakes, proposed_size, proposed_stakes):
    """Return (effective_size, effective_stakes) taking the higher of each axis.

    Axis orderings (from lowest to highest rigor):
      size:   trivial < small < standard < large
      stakes: low < normal < high

    Rules (axis-level realization of design.md:29 invariant (e)):
      - None current  -> treated as the lowest known rank; any explicit proposed wins.
      - None proposed -> effective = current (absent signal leaves current unchanged).
      - Unrecognized string -> treated as the lowest known rank for that axis
        (conservative: never block an upward proposal due to an unknown value).
      - effective rank >= current rank for both axes (upward-only, never lower).

    This function is the axis-guard step in the in-loop escalation sequence:
    it must be called BEFORE escalate_lane so the axis values passed in are
    already monotone-clamped.  No automatic/unattended code path may write a
    size or stakes value that is strictly lower than the current confirmed value
    without first passing through guard_axes.

    Pure function: no I/O, no side effects; stdlib only.
    """
    def _rank(value, order):
        try:
            return order.index(value)
        except (ValueError, TypeError):
            return -1  # None / unrecognized -> below the lowest recognized value

    def _pick_higher(current, proposed, order):
        if proposed is None:
            # No new signal: leave current unchanged (or fall back to lowest if
            # current is also unknown, since there is nothing to preserve).
            return current if current is not None else order[0]
        c_rank = _rank(current, order)
        p_rank = _rank(proposed, order)
        if p_rank > c_rank:
            return proposed
        # current rank >= proposed rank (or current is None/-1): return whichever
        # is a recognized value; prefer current when both are known.
        if current is None or c_rank < 0:
            # current unknown: proposed is known and >= current rank (both -1), take it
            return proposed
        return current

    eff_size = _pick_higher(current_size, proposed_size, _SIZE_ORDER)
    eff_stakes = _pick_higher(current_stakes, proposed_stakes, _STAKES_ORDER)
    return eff_size, eff_stakes


def recommend_stakes(paths, settings):
    """Match a collection of file paths against high_stakes_paths globs from settings.

    Returns 'high' if any path matches any glob; returns 'normal' otherwise.
    Pure function — never writes stakes to ticket.json or any state file.

    Arguments:
      paths    -- iterable of file path strings (changed files, owned paths, surveyed paths).
                  Empty collection -> 'normal'.
      settings -- the merged settings dict; high_stakes_paths resolved from it
                  (falls back to DEFAULT_SETTINGS seed list if absent or settings is None).

    Returns 'high' or 'normal'. This is a RECOMMENDATION only; the caller (SKILL.md planner)
    presents it to the user. The function never silently floors a previously-confirmed value.
    """
    globs = (settings or {}).get("high_stakes_paths", DEFAULT_SETTINGS["high_stakes_paths"])
    for path in (paths or []):
        for pattern in globs:
            if fnmatch.fnmatch(path, pattern):
                return "high"
    return "normal"


DEFAULT_SETTINGS = {
    "test_coverage_percent": 90,
    "merge_strategy": "squash",
    "high_stakes_paths": [
        "auth/**",
        "payments/**",
        "migrations/**",
        "public-api/**",
        "security/**",
    ],
    "prd_path": "docs/product",
    "architecture_path": "docs/architecture",
    "requirements_path": "docs/requirements",
    "adr_path": "docs/adr",
    "tracker": {"provider": "local"},
    "models": {},
    "formats": {
        "branch_name": "{type}/{ticket_id}-{slug}",
        "commit_message": "{ticket_id} {summary}",
        "pr_title": "[{ticket_id}] {title}",
        "pr_description_template": "pr-default",
        "tickets": {
            "epic": {"title": "[EPIC] {title}", "description_template": "epic-default"},
            "story": {"title": "{title}", "description_template": "story-default"},
            "task": {"title": "{title}", "description_template": "task-default"},
        },
    },
}

# Enforcement defaults — mirror schemas/settings.schema.json + the consumer-side
# templates/ci/check-conventions.py, used only when a key is absent from settings
# so /acs:merge-pr --pr behaves predictably on a repo with no enforcement block.
ENFORCEMENT_DEFAULTS = {
    "exempt_branches": ["release/*", "dependabot/*", "renovate/*"],
    "exempt_label": "acs-exempt",
    "require_label": "ACS",
}


def enforcement_value(settings, key):
    """Resolve enforcement.<key> from settings, defaulting per ENFORCEMENT_DEFAULTS."""
    return ((settings or {}).get("enforcement") or {}).get(key, ENFORCEMENT_DEFAULTS[key])


TICKET_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]*-\d+)\b")


class GateError(Exception):
    """Raised when a pre-hook gate fails; message is user-facing (stderr, exit 2)."""


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value):
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def slugify(text, max_len=40):
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:max_len].rstrip("-") or "change"


def read_json(path):
    """Tolerant read: returns None when the file is missing or corrupt (reported, never raises)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write("acs: warning: unreadable/corrupt JSON at %s (%s) — treated as absent\n" % (path, exc))
        return None


def write_json(path, data):
    """Atomic, pretty-printed write (the workspace doubles as a human-readable audit trail)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".acs-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def deep_merge(base, override):
    """Recursive per-key merge; override wins on leaves."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _git(args, cwd):
    try:
        proc = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


# ---------------------------------------------------------------------------
# Repo identity & checkout identity
# ---------------------------------------------------------------------------

def checkout_root(cwd):
    """Root of the current checkout/worktree."""
    return _git(["rev-parse", "--show-toplevel"], cwd)


def main_repo_root(cwd):
    """Root of the *main* repository, even when cwd is inside a linked worktree."""
    common = _git(["rev-parse", "--git-common-dir"], cwd)
    if not common:
        return None
    if not os.path.isabs(common):
        common = os.path.join(cwd, common)
    common = os.path.normpath(common)
    if os.path.basename(common) == ".git":
        return os.path.dirname(common)
    return common  # bare-ish layouts; best effort


def repo_partition_id(cwd):
    """Stable per-repo identifier: derived from the git remote (owner-name), so every
    worktree of a repo resolves to the same partition; falls back to the main repo
    directory name when there is no remote."""
    remote = _git(["config", "--get", "remote.origin.url"], cwd)
    if remote:
        path = remote
        path = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", path)   # scheme
        path = re.sub(r"^[^/@]+@", "", path)                       # user@
        path = path.replace(":", "/")
        path = re.sub(r"\.git/?$", "", path)
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 2:
            raw = "%s-%s" % (segments[-2], segments[-1])
        elif segments:
            raw = segments[-1]
        else:
            raw = None
        if raw:
            return re.sub(r"[^A-Za-z0-9._-]+", "-", raw)
    root = main_repo_root(cwd) or checkout_root(cwd)
    if root:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(root))
    return None


def checkout_id(cwd):
    """Stable per-checkout/worktree identifier (one pointer file per parallel session)."""
    root = checkout_root(cwd) or os.path.abspath(cwd)
    digest = hashlib.sha1(os.path.abspath(root).encode("utf-8")).hexdigest()[:8]
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(root))
    return "%s-%s" % (base, digest)


def current_branch(cwd):
    return _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def settings_files(cwd):
    """Candidate settings files, least -> most specific. settings.local.json is
    machine-specific and gitignored; a linked worktree may not have its own copy,
    so the main checkout's local settings are also consulted."""
    candidates = []
    user = os.path.join(os.path.expanduser("~"), ".acs", "settings.json")
    candidates.append(user)
    main_root = main_repo_root(cwd)
    top = checkout_root(cwd)
    roots = []
    for root in (main_root, top):
        if root and root not in roots:
            roots.append(root)
    for root in roots:
        candidates.append(os.path.join(root, ".acs", "settings.json"))
    for root in roots:
        candidates.append(os.path.join(root, ".acs", "settings.local.json"))
    return candidates


def load_settings(cwd):
    """Per-key merge across scopes: settings.local.json -> project settings.json -> user."""
    merged = dict(DEFAULT_SETTINGS)
    found = []
    for path in settings_files(cwd):
        data = read_json(path)
        if isinstance(data, dict):
            merged = deep_merge(merged, data)
            found.append(path)
    return merged, found


def validate_settings(settings, cwd, require_workspace=True):
    """Shared baseline validation used by every pre-hook. Raises GateError."""
    workspace = settings.get("workspace_path")
    if require_workspace:
        if not workspace:
            raise GateError(
                "acs is not initialized for this repo: workspace_path is not configured. Run /acs:init first."
            )
        workspace = os.path.abspath(os.path.expanduser(str(workspace)))
        for root in (main_repo_root(cwd), checkout_root(cwd)):
            if root:
                try:
                    if os.path.commonpath([workspace, os.path.abspath(root)]) == os.path.abspath(root):
                        raise GateError(
                            "workspace_path (%s) is inside the repository (%s); it must live outside the "
                            "consumer repo so worktrees and parallel tickets work. Re-run /acs:init." % (workspace, root)
                        )
                except ValueError:
                    pass  # different drives (Windows) — necessarily outside
    prefix = settings.get("ticket_prefix")
    if require_workspace:
        if not prefix or not re.fullmatch(r"[A-Z][A-Z0-9]*", str(prefix)):
            raise GateError(
                "ticket_prefix is missing or invalid (must be a non-empty uppercase identifier, e.g. SHOP). "
                "Run /acs:init."
            )
    coverage = settings.get("test_coverage_percent", 90)
    if not isinstance(coverage, (int, float)) or not (0 < coverage <= 100):
        raise GateError("test_coverage_percent must be a number in (0, 100]; got %r." % (coverage,))
    strategy = settings.get("merge_strategy", "squash")
    if strategy not in ("squash", "merge", "rebase"):
        raise GateError("merge_strategy must be one of squash|merge|rebase; got %r." % (strategy,))
    e2e = settings.get("e2e")
    if e2e is not None:
        if not isinstance(e2e, dict) or not isinstance(e2e.get("command"), str) or not e2e["command"].strip():
            raise GateError("e2e must be an object with a non-empty 'command' (plus optional setup/teardown/per_iteration).")
        for key in ("setup", "teardown"):
            if key in e2e and (not isinstance(e2e[key], str) or not e2e[key].strip()):
                raise GateError("e2e.%s must be a non-empty string when set." % key)
        if "per_iteration" in e2e and not isinstance(e2e["per_iteration"], bool):
            raise GateError("e2e.per_iteration must be a boolean.")
    validate_formats(settings.get("formats", {}))
    validate_models(settings.get("models", {}))
    return workspace if require_workspace else None


def validate_formats(formats):
    def check(field, template, vocab_key):
        if not isinstance(template, str) or not template.strip():
            raise GateError("formats.%s must be a non-empty string." % field)
        used = set(re.findall(r"\{([a-z_]+)\}", template))
        unknown = used - FORMAT_PLACEHOLDERS[vocab_key]
        if unknown:
            raise GateError(
                "formats.%s uses unknown placeholder(s) %s; allowed: %s."
                % (field, ", ".join("{%s}" % p for p in sorted(unknown)),
                   ", ".join("{%s}" % p for p in sorted(FORMAT_PLACEHOLDERS[vocab_key])))
            )

    if "branch_name" in formats:
        check("branch_name", formats["branch_name"], "branch_name")
        if "{ticket_id}" not in formats["branch_name"]:
            raise GateError("formats.branch_name must embed {ticket_id} — ticket detection from branch names depends on it.")
    if "commit_message" in formats:
        check("commit_message", formats["commit_message"], "commit_message")
    if "pr_title" in formats:
        check("pr_title", formats["pr_title"], "pr_title")
    tickets = formats.get("tickets", {})
    if not isinstance(tickets, dict):
        raise GateError("formats.tickets must be an object keyed by ticket type.")
    for ttype, conf in tickets.items():
        if ttype not in TICKET_TYPES:
            raise GateError("formats.tickets.%s: unknown ticket type (epic|story|task)." % ttype)
        if isinstance(conf, dict) and "title" in conf:
            check("tickets.%s.title" % ttype, conf["title"], "ticket_title")


def validate_models(models):
    if not isinstance(models, dict):
        raise GateError("models must be an object.")

    def check_role(path, value):
        if isinstance(value, str):
            if not value.strip():
                raise GateError("models.%s must be a non-empty model string or a {model, effort} object." % path)
            return
        if isinstance(value, dict):
            extra = set(value) - {"model", "effort"}
            if extra:
                raise GateError("models.%s: unknown key(s) %s (allowed: model, effort)." % (path, ", ".join(sorted(extra))))
            return
        raise GateError("models.%s must be a model string or a {model, effort} object." % path)

    for role in ("planner", "executor", "verifier", "coordinator"):
        if role in models:
            check_role(role, models[role])
    for skill, roles in models.get("overrides", {}).items():
        if not isinstance(roles, dict):
            raise GateError("models.overrides.%s must be an object of role -> model." % skill)
        for role, value in roles.items():
            check_role("overrides.%s.%s" % (skill, role), value)


def resolve_role_model(settings, skill, role):
    """Per-field resolution: overrides.<skill>.<role> -> models.<role> -> inherit."""
    models = settings.get("models", {}) or {}

    def as_obj(value):
        if isinstance(value, str):
            return {"model": value}
        return dict(value or {})

    resolved = {}
    for source in (models.get(role), (models.get("overrides", {}) or {}).get(skill, {}).get(role)):
        if source:
            for key, value in as_obj(source).items():
                if value and value != "inherit":
                    resolved[key] = value
    return {"model": resolved.get("model", "inherit"), "effort": resolved.get("effort", "inherit")}


def render_format(template, mapping):
    return re.sub(r"\{([a-z_]+)\}", lambda m: str(mapping.get(m.group(1), "")), template)


def resolve_template(value, repo_root, plugin_root):
    """Built-in name -> plugin templates/; else <repo>/.acs/templates/<value>.md; else absolute path."""
    if value in BUILTIN_TEMPLATES:
        return os.path.join(plugin_root, "templates", "%s.md" % value)
    candidate = os.path.join(repo_root or "", ".acs", "templates", "%s.md" % value)
    if repo_root and os.path.isfile(candidate):
        return candidate
    if os.path.isabs(value) and os.path.isfile(value):
        return value
    return None


def plugin_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Workspace layout
# ---------------------------------------------------------------------------

def repo_dir(workspace, repo_id):
    return os.path.join(workspace, repo_id)


def ticket_dir(workspace, repo_id, ticket_id):
    return os.path.join(workspace, repo_id, ticket_id)


def archive_dir(workspace, repo_id):
    return os.path.join(workspace, repo_id, "archive")


def sessions_dir(workspace, repo_id):
    return os.path.join(workspace, repo_id, "sessions")


def pointer_path(workspace, repo_id, ckid):
    return os.path.join(sessions_dir(workspace, repo_id), "%s.json" % ckid)


def state_path(tdir, skill):
    return os.path.join(tdir, "%s-state.json" % skill)


def lock_path(tdir):
    return os.path.join(tdir, ".lock")


def find_ticket_partition(workspace, repo_id, ticket_id):
    """Active partition first, then archive/."""
    active = ticket_dir(workspace, repo_id, ticket_id)
    if os.path.isdir(active):
        return active, False
    archived = os.path.join(archive_dir(workspace, repo_id), ticket_id)
    if os.path.isdir(archived):
        return archived, True
    return active, False


# ---------------------------------------------------------------------------
# Ticket id resolution (deterministic: argument -> pointer file -> branch name)
# ---------------------------------------------------------------------------

def ticket_id_from_text(text, prefix=None):
    if not text:
        return None
    if prefix:
        match = re.search(r"\b(%s-\d+)\b" % re.escape(prefix), text)
        if match:
            return match.group(1)
        return None
    match = TICKET_ID_RE.search(text)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# CLAUDE.md managed-block helpers (written/refreshed by /acs:init). Pure string
# functions so the splice and the placeholder substitution are unit-testable.
# The markers MUST match templates/CLAUDE.acs.md exactly.
# ---------------------------------------------------------------------------

ACS_BLOCK_BEGIN = "<!-- BEGIN acs-managed (do not edit inside this block) -->"
ACS_BLOCK_END = "<!-- END acs-managed -->"


def render_managed_block(template_text, ticket_prefix, exempt_label):
    """Substitute the {ticket_prefix} and {exempt_label} placeholders in the
    CLAUDE.acs.md template text. Pure str.replace so a literal '{' elsewhere in
    the template is never treated as a format field."""
    return (template_text
            .replace("{ticket_prefix}", ticket_prefix or "")
            .replace("{exempt_label}", exempt_label or ""))


def _managed_body(text):
    """Reduce *text* to the guidance body that belongs INSIDE a managed block.

    The writer (upsert_managed_block) owns the markers, so a body must never
    carry its own — otherwise wrapping doubles them. This reducer makes that
    impossible regardless of what the caller/template supplies:
      * if a full BEGIN..END pair is present, take the slice strictly between the
        FIRST begin and the LAST end (dropping any maintainer header above BEGIN
        and the markers themselves);
      * then remove any stray marker strings that survived (unpaired or nested);
      * finally trim surrounding blank lines so wrapping is deterministic.
    Pure function; no I/O."""
    begin = text.find(ACS_BLOCK_BEGIN)
    end = text.rfind(ACS_BLOCK_END)
    if begin != -1 and end != -1 and end > begin:
        text = text[begin + len(ACS_BLOCK_BEGIN):end]
    text = text.replace(ACS_BLOCK_BEGIN, "").replace(ACS_BLOCK_END, "")
    return text.strip("\n")


def managed_body_from_template(template_text, ticket_prefix, exempt_label):
    """Render CLAUDE.acs.md down to the guidance BODY only, ready to wrap.

    Substitutes the two placeholders (render_managed_block) and then extracts the
    text strictly between the template's own ACS_BLOCK_BEGIN/END markers — the
    maintainer header and the markers themselves are dropped, so upsert_managed_block
    injects exactly one clean marker pair around just the guidance. A template with
    no markers degrades gracefully to the whole (substituted) text. Pure function."""
    return _managed_body(render_managed_block(template_text, ticket_prefix, exempt_label))


def _strip_stray_markers(text):
    """Remove any lone acs marker LINES from *text* (belt-and-suspenders for the
    content SURROUNDING the managed span in upsert_managed_block).

    The acs markers are acs-owned — user-authored CLAUDE.md content is never
    expected to contain them — so this only ever deletes stray markers a prior
    buggy write left OUTSIDE the span (an orphaned END before the block, a lone
    BEGIN after it). Returns *text* unchanged byte-for-byte when it holds no
    marker, so well-formed surrounding content is never perturbed. Pure."""
    if ACS_BLOCK_BEGIN not in text and ACS_BLOCK_END not in text:
        return text
    kept = [ln for ln in text.split("\n")
            if ln.strip() != ACS_BLOCK_BEGIN and ln.strip() != ACS_BLOCK_END]
    text = "\n".join(kept)
    # scrub any inline residue (a marker not alone on its line) as well
    return text.replace(ACS_BLOCK_BEGIN, "").replace(ACS_BLOCK_END, "")


def upsert_managed_block(existing_text, block_body):
    """Return existing_text with the acs-managed block inserted or replaced.

    The block is ACS_BLOCK_BEGIN + newline + block_body + newline + ACS_BLOCK_END,
    where block_body is first reduced via _managed_body so it can never re-introduce
    a marker (no caller — however buggy — can cause doubling).

    When markers are already present, replace the inclusive span from the FIRST
    BEGIN to the LAST END (rfind), preserving everything before and after byte for
    byte. Using rfind self-heals a legacy DOUBLED block: the whole nested mess
    collapses to one clean pair rather than leaving an orphaned outer END, and any
    stray marker left in the surrounding text (an orphan END before the span or a
    lone BEGIN after it) is scrubbed via _strip_stray_markers so no orphan can
    survive a heal. When no markers are present, append the block separated by
    exactly one blank line; an empty (or marker-only) existing_text yields just the
    block. Idempotent: a second call with the same block_body yields output
    byte-identical to the first (and self-healing is itself idempotent)."""
    block = "%s\n%s\n%s" % (ACS_BLOCK_BEGIN, _managed_body(block_body), ACS_BLOCK_END)
    begin = existing_text.find(ACS_BLOCK_BEGIN)
    end = existing_text.rfind(ACS_BLOCK_END)
    if begin != -1 and end != -1 and end > begin:
        before = _strip_stray_markers(existing_text[:begin])
        after = _strip_stray_markers(existing_text[end + len(ACS_BLOCK_END):])
        return before + block + after
    # No full pair: drop any lone orphan marker, then append after existing content.
    stripped = _strip_stray_markers(existing_text)
    if not stripped.strip():
        return block
    # Append, separated from preceding content by exactly one blank line.
    return stripped.rstrip("\n") + "\n\n" + block


def managed_block_is_malformed(text):
    """True when *text* does NOT contain exactly one acs-managed marker pair.

    Pure detector used by /acs:init Step 7e to decide whether the consumer
    CLAUDE.md needs REPAIR before the refresh: a doubled block (2+ BEGIN and/or
    END) or an orphaned marker (unequal counts, a lone BEGIN or END) all read as
    malformed. Note a file with NO markers is likewise "not exactly one pair" and
    so reports True — callers distinguish an ABSENT block (a normal first write)
    from a CORRUPTED one by additionally checking that at least one marker is
    present (Step 7e only reports a repair when a marker was already there)."""
    return text.count(ACS_BLOCK_BEGIN) != 1 or text.count(ACS_BLOCK_END) != 1


# ---------------------------------------------------------------------------
# Exempt non-ticket /acs:merge-pr argument classifier (MAR-9, clarification C-3).
# Pure: given the raw arg string it decides ticket-backed vs exempt-pr and parses
# the PR ref for the exempt case. The caller supplies ticket_resolves (whether a
# pointer/branch already yields a ticket) to disambiguate a bare integer.
# ---------------------------------------------------------------------------

_PR_URL_RE = re.compile(r"/pull/(\d+)\b")
_PR_FLAG_RE = re.compile(r"--pr[=\s]+(\d+)\b")
_PR_HASH_RE = re.compile(r"#(\d+)\b")
_BARE_INT_RE = re.compile(r"^\s*(\d+)\s*$")


def classify_merge_pr_arg(args_text, ticket_prefix=None, ticket_resolves=False):
    """Classify a /acs:merge-pr argument string.

    Returns (kind, pr_ref):
      ("exempt-pr", "<n>") for the non-ticket merge forms — an explicit
        --pr <n> flag, a #<n> token, a PR URL (.../pull/<n>), or a bare integer
        that is NOT a ticket id AND no ticket already resolves from pointer/branch.
      ("ticket", None) for a ticket-id-shaped token (the ticket gate always wins),
        a bare integer when a ticket resolves (prefer ticket when ambiguous), and
        any empty/unrecognized input (let the existing ticket gate produce its
        existing error). Per clarification C-3."""
    text = args_text or ""
    # A ticket-id-shaped token always wins — preserves AC-8.
    if ticket_id_from_text(text, ticket_prefix):
        return ("ticket", None)
    # Explicit forms are ALWAYS exempt (C-3), regardless of ticket_resolves.
    m = _PR_FLAG_RE.search(text)
    if m:
        return ("exempt-pr", m.group(1))
    m = _PR_URL_RE.search(text)
    if m:
        return ("exempt-pr", m.group(1))
    m = _PR_HASH_RE.search(text)
    if m:
        return ("exempt-pr", m.group(1))
    # A bare integer is exempt only when no ticket resolves (C-3: prefer ticket).
    m = _BARE_INT_RE.match(text)
    if m and not ticket_resolves:
        return ("exempt-pr", m.group(1))
    return ("ticket", None)


def _pr_labels(pr):
    """gh pr view --json labels yields [{"name": ...}, ...]; normalize to names."""
    out = []
    for label in pr.get("labels") or []:
        if isinstance(label, dict) and label.get("name"):
            out.append(label["name"])
        elif isinstance(label, str):
            out.append(label)
    return out


def validate_exempt_pr(pr, settings):
    """Validate a PR (the parsed `gh pr view` JSON object) for the exempt-pr merge
    path. Returns (ok, message): ok True means the PR is a sanctioned exempt PR;
    ok False means refuse, and `message` is the user-facing reason (already
    carrying the /acs:merge-pr <ticket> redirect when the PR looks ticket-backed).
    Mirrors templates/ci/check-conventions.py is_exempt (label first, then branch
    glob) and the C-3 ticket-backed refusal."""
    branch = pr.get("headRefName") or ""
    labels = _pr_labels(pr)
    exempt_label = enforcement_value(settings, "exempt_label")
    require_label = enforcement_value(settings, "require_label")
    exempt_branches = enforcement_value(settings, "exempt_branches") or []
    prefix = (settings or {}).get("ticket_prefix")

    # OPEN + not draft.
    state = (pr.get("state") or "").upper()
    if state != "OPEN":
        return (False, "PR #%s is %s, not OPEN — only an open PR can be merged."
                % (pr.get("number"), state or "in an unknown state"))
    if pr.get("isDraft"):
        return (False, "PR #%s is a draft — mark it ready for review before merging."
                % pr.get("number"))

    # Ticket-backed → refuse + redirect (C-3). Checked before the exempt grant so
    # a PR that is BOTH ticket-labelled and exempt-labelled still routes to the
    # ticket path.
    embedded = ticket_id_from_text(branch, prefix)
    if require_label in labels or embedded:
        target = embedded or "<TICKET-ID>"
        return (False,
                "PR #%s looks ticket-backed (%s) — merge it through the ticket "
                "path: /acs:merge-pr %s, not the exempt --pr path."
                % (pr.get("number"),
                   "carries the '%s' label" % require_label if require_label in labels
                   else "branch '%s' embeds %s" % (branch, embedded),
                   target))

    # Exempt grant: label first, then branch glob.
    if exempt_label and exempt_label in labels:
        return (True, "label '%s' present" % exempt_label)
    for pattern in exempt_branches:
        if branch and fnmatch.fnmatch(branch, pattern):
            return (True, "branch matches exempt pattern '%s'" % pattern)

    return (False,
            "PR #%s is not a sanctioned exempt PR — label it '%s' (or use an "
            "exempt branch) for the --pr path, or merge it through a ticket: "
            "/acs:merge-pr <TICKET-ID>." % (pr.get("number"), exempt_label))


def run_post_exempt_pr(cwd):
    """Metrics-only post-hook for /acs:merge-pr --pr: bump the repo pr_merged
    metric via the existing update_metrics pr_merged path and touch nothing else —
    no ticket state, index write, pipeline, archive, lock, or pointer. Returns the
    confirmation dict; raises GateError if the context cannot be built."""
    ctx = build_context(cwd)
    update_metrics(ctx["workspace"], ctx["repo_id"], pr_merged=True)
    return {"ok": True, "mode": "exempt-pr", "pr_merged": True}


def resolve_ticket_id(cwd, settings, workspace, repo_id, explicit=None, args_text=None):
    prefix = settings.get("ticket_prefix")
    if explicit:
        return explicit.strip(), "argument"
    from_args = ticket_id_from_text(args_text, prefix)
    if from_args:
        return from_args, "argument"
    pointer = read_json(pointer_path(workspace, repo_id, checkout_id(cwd)))
    if isinstance(pointer, dict) and pointer.get("ticket_id"):
        return pointer["ticket_id"], "pointer"
    from_branch = ticket_id_from_text(current_branch(cwd), prefix)
    if from_branch:
        return from_branch, "branch"
    return None, None


# ---------------------------------------------------------------------------
# State files (append-only runs; last entry = current state)
# ---------------------------------------------------------------------------

def empty_state(skill, ticket_id):
    return {"skill": skill, "ticket_id": ticket_id, "states": {}, "findings": [], "errors": [], "runs": []}


def load_state(tdir, skill, ticket_id=None):
    state = read_json(state_path(tdir, skill))
    if not isinstance(state, dict) or not isinstance(state.get("runs"), list):
        return empty_state(skill, ticket_id or os.path.basename(tdir))
    return state


def last_run(state):
    runs = state.get("runs") or []
    return runs[-1] if runs else None


def last_run_status(tdir, skill):
    state = read_json(state_path(tdir, skill))
    if not isinstance(state, dict):
        return None
    runs = state.get("runs")
    if not isinstance(runs, list) or not runs:
        return None
    entry = runs[-1]
    return entry.get("status") if isinstance(entry, dict) else None


def skill_completed(tdir, skill):
    return last_run_status(tdir, skill) == "completed"


def append_in_progress_run(tdir, skill, ticket_id):
    state = load_state(tdir, skill, ticket_id)
    state["runs"].append({
        "started_at": now_iso(),
        "ended_at": None,
        "tokens": {"input": 0, "output": 0},
        "cost_usd": 0.0,
        "status": "in_progress",
        "stop_reason": None,
    })
    write_json(state_path(tdir, skill), state)
    return state


def finalize_run(tdir, skill, ticket_id, result):
    """Finalize runs[-1] (or append, if the coordinator never registered the run)."""
    state = load_state(tdir, skill, ticket_id)
    status = result.get("status", "completed")
    if status not in RUN_STATUSES or status == "in_progress":
        raise ValueError("invalid final run status: %r" % status)
    entry = last_run(state)
    if not entry or entry.get("status") != "in_progress":
        entry = {"started_at": now_iso(), "tokens": {"input": 0, "output": 0}, "cost_usd": 0.0}
        state["runs"].append(entry)
    entry["ended_at"] = now_iso()
    entry["status"] = status
    entry["stop_reason"] = result.get("stop_reason")
    tokens = result.get("tokens") or {}
    entry["tokens"] = {"input": int(tokens.get("input", 0) or 0), "output": int(tokens.get("output", 0) or 0)}
    entry["cost_usd"] = float(result.get("cost_usd", 0.0) or 0.0)
    if status == "handed_off":
        entry["handoff_summary"] = result.get("handoff_summary") or result.get("stop_reason") or ""
    if isinstance(result.get("states"), dict):
        state["states"].update(result["states"])
    if isinstance(result.get("findings"), list):
        state["findings"] = result["findings"]
    if isinstance(result.get("errors"), list):
        state["errors"] = result["errors"]
    write_json(state_path(tdir, skill), state)
    return state, entry


def run_seconds(entry):
    start, end = parse_iso(entry.get("started_at")), parse_iso(entry.get("ended_at"))
    if start and end and end >= start:
        return int((end - start).total_seconds())
    return 0


# ---------------------------------------------------------------------------
# Pipeline ledger (pipeline-state.json)
# ---------------------------------------------------------------------------

def load_pipeline(tdir, ticket_id, flow="ticket"):
    data = read_json(os.path.join(tdir, "pipeline-state.json"))
    if not isinstance(data, dict):
        data = {"ticket_id": ticket_id, "flow": flow, "steps": {}, "totals": {}}
    data.setdefault("steps", {})
    data.setdefault("totals", {})
    return data


def update_pipeline(tdir, ticket_id, skill, status, summary=None, flow=None, lane=None):
    data = load_pipeline(tdir, ticket_id, flow or ("product" if skill in PRODUCT_SKILLS else "ticket"))
    if flow:
        data["flow"] = flow
    step = data["steps"].setdefault(skill, {})
    if status == "in_progress" and not step.get("started_at"):
        step["started_at"] = now_iso()
    if status != "in_progress":
        step["ended_at"] = now_iso()
    step["status"] = status
    if summary is not None:
        step["summary"] = summary
    if lane is not None:
        data["lane"] = lane
    data["totals"] = compute_ticket_totals(tdir)
    write_json(os.path.join(tdir, "pipeline-state.json"), data)
    return data


def compute_ticket_totals(tdir):
    """Roll up time/tokens/cost across every skill state file in the partition."""
    totals = {"runs": 0, "working_seconds": 0, "tokens": {"input": 0, "output": 0}, "cost_usd": 0.0}
    for skill in HOOKED_SKILLS:
        state = read_json(state_path(tdir, skill))
        if not isinstance(state, dict):
            continue
        for entry in state.get("runs") or []:
            if not isinstance(entry, dict):
                continue
            totals["runs"] += 1
            totals["working_seconds"] += run_seconds(entry)
            tokens = entry.get("tokens") or {}
            totals["tokens"]["input"] += int(tokens.get("input", 0) or 0)
            totals["tokens"]["output"] += int(tokens.get("output", 0) or 0)
            totals["cost_usd"] += float(entry.get("cost_usd", 0.0) or 0.0)
    totals["cost_usd"] = round(totals["cost_usd"], 4)
    return totals


# ---------------------------------------------------------------------------
# Tickets, index, counters, metrics
# ---------------------------------------------------------------------------

def load_ticket(tdir):
    return read_json(os.path.join(tdir, "ticket.json"))


def save_ticket(tdir, ticket):
    ticket["updated_at"] = now_iso()
    write_json(os.path.join(tdir, "ticket.json"), ticket)


def new_ticket_doc(ticket_id, title, ttype, **kw):
    return {
        "id": ticket_id,
        "title": title,
        "type": ttype,
        "description": kw.get("description", ""),
        "acceptance_criteria": kw.get("acceptance_criteria", []),
        "priority": kw.get("priority", "medium"),
        "parent": kw.get("parent"),
        "children": kw.get("children", []),
        "status": kw.get("status", "open"),
        "external": kw.get("external"),
        "assignee": kw.get("assignee"),
        "story_points": kw.get("story_points"),
        "needs_design": kw.get("needs_design", ttype == "epic"),
        "docs_only": kw.get("docs_only", False),
        "size":   kw.get("size",   "standard"),
        "stakes": kw.get("stakes", "normal"),
        "lane":   derive_lane(
                      kw.get("size",   "standard"),
                      kw.get("stakes", "normal"),
                      kw.get("needs_design", ttype == "epic"),
                      ttype
                  ),
        "due_date": kw.get("due_date"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def allocate_ticket_id(workspace, repo_id, prefix):
    """Allocate the next <prefix>-<n> id; counter guarded by an O_EXCL spin lock so
    parallel worktree sessions never collide."""
    rdir = repo_dir(workspace, repo_id)
    os.makedirs(rdir, exist_ok=True)
    guard = os.path.join(rdir, "counters.json.lock")
    acquired = False
    for _ in range(200):
        try:
            fd = os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            try:
                if os.path.getmtime(guard) < datetime.now(timezone.utc).timestamp() - 30:
                    os.unlink(guard)  # stale guard from a crashed allocation
                    continue
            except OSError:
                pass
            import time
            time.sleep(0.05)
    try:
        counters = read_json(os.path.join(rdir, "counters.json")) or {}
        next_n = int(counters.get("next", 1))
        counters["next"] = next_n + 1
        write_json(os.path.join(rdir, "counters.json"), counters)
        return "%s-%d" % (prefix, next_n)
    finally:
        if acquired:
            try:
                os.unlink(guard)
            except OSError:
                pass


def index_path(workspace, repo_id):
    return os.path.join(repo_dir(workspace, repo_id), "tickets-index.json")


def update_index(workspace, repo_id, ticket, archived=None):
    path = index_path(workspace, repo_id)
    data = read_json(path) or {"tickets": {}}
    data.setdefault("tickets", {})
    entry = data["tickets"].setdefault(ticket["id"], {})
    entry.update({
        "id": ticket["id"],
        "title": ticket.get("title"),
        "type": ticket.get("type"),
        "status": ticket.get("status"),
        "parent": ticket.get("parent"),
        "children": ticket.get("children", []),
        "needs_design": ticket.get("needs_design"),
        "lane": ticket.get("lane"),
        "external": ticket.get("external"),
        "due_date": ticket.get("due_date"),
        "updated_at": now_iso(),
    })
    if archived is not None:
        entry["archived"] = archived
    write_json(path, data)
    return data


def metrics_path(workspace, repo_id):
    return os.path.join(repo_dir(workspace, repo_id), "metrics.json")


def update_metrics(workspace, repo_id, run_entry=None, pr_created=False, pr_merged=False, pr_number=None):
    """Repo-level aggregates: ticket counts recomputed from the index (idempotent),
    PR counts and run totals accumulated incrementally."""
    path = metrics_path(workspace, repo_id)
    data = read_json(path) or {}
    data.setdefault("tickets", {})
    data.setdefault("prs", {"created": 0, "merged": 0, "created_pr_numbers": []})
    data.setdefault("totals", {"runs": 0, "working_seconds": 0, "tokens": {"input": 0, "output": 0}, "cost_usd": 0.0})

    index = read_json(index_path(workspace, repo_id)) or {"tickets": {}}
    by_status = {}
    by_type = {}
    for ticket in index.get("tickets", {}).values():
        by_status[ticket.get("status") or "unknown"] = by_status.get(ticket.get("status") or "unknown", 0) + 1
        by_type[ticket.get("type") or "unknown"] = by_type.get(ticket.get("type") or "unknown", 0) + 1
    data["tickets"] = {"total": len(index.get("tickets", {})), "by_status": by_status, "by_type": by_type}

    if pr_created:
        numbers = data["prs"].setdefault("created_pr_numbers", [])
        if isinstance(pr_number, int) and pr_number > 0 and pr_number not in numbers:
            numbers.append(pr_number)
            numbers.sort()
            data["prs"]["created"] = len(numbers)
        # else: leave both created and created_pr_numbers unchanged (idempotent)
    if pr_merged:
        data["prs"]["merged"] = int(data["prs"].get("merged", 0)) + 1
    if run_entry:
        totals = data["totals"]
        totals["runs"] = int(totals.get("runs", 0)) + 1
        totals["working_seconds"] = int(totals.get("working_seconds", 0)) + run_seconds(run_entry)
        tokens = run_entry.get("tokens") or {}
        totals.setdefault("tokens", {"input": 0, "output": 0})
        totals["tokens"]["input"] = int(totals["tokens"].get("input", 0)) + int(tokens.get("input", 0) or 0)
        totals["tokens"]["output"] = int(totals["tokens"].get("output", 0)) + int(tokens.get("output", 0) or 0)
        totals["cost_usd"] = round(float(totals.get("cost_usd", 0.0)) + float(run_entry.get("cost_usd", 0.0) or 0.0), 4)
    data["updated_at"] = now_iso()
    write_json(path, data)
    return data



def backfill_distinct_pr_count(workspace, repo_id):
    """One-time idempotent recompute of prs.created_pr_numbers from distinct
    positive states.pr.number values across all active and archive/ ticket
    partitions.  Sets prs.created = len(created_pr_numbers).

    Read-only except the single metrics.json write.  Safe to re-run: the result
    is always the recoverable distinct set from the current partition state; a
    second run with unchanged partitions produces the identical output.

    Per clarification C-1 (MAR-13 / MAR-8 design A1): pre-fix history without
    a retained PR number is unrecoverable and accepted -- this is not a defect.
    """
    # Gather all ticket IDs from the index
    idx = read_json(index_path(workspace, repo_id)) or {"tickets": {}}
    ticket_ids = list(idx.get("tickets", {}).keys())

    distinct_numbers = set()
    for tid in ticket_ids:
        tdir, _archived = find_ticket_partition(workspace, repo_id, tid)
        sp = state_path(tdir, "create-pr")
        state = read_json(sp)
        if not isinstance(state, dict):
            continue
        pr_num = (state.get("states") or {}).get("pr", {})
        if isinstance(pr_num, dict):
            pr_num = pr_num.get("number")
        if isinstance(pr_num, int) and pr_num > 0:
            distinct_numbers.add(pr_num)

    # Write back -- overwrite is what makes this idempotent
    mpath = metrics_path(workspace, repo_id)
    data = read_json(mpath) or {}
    data.setdefault("prs", {"created": 0, "merged": 0, "created_pr_numbers": []})
    recovered = sorted(distinct_numbers)
    data["prs"]["created_pr_numbers"] = recovered
    data["prs"]["created"] = len(recovered)
    write_json(mpath, data)
    return data


# ---------------------------------------------------------------------------
# Locking (.lock per ticket partition; re-entrant per checkout)
# ---------------------------------------------------------------------------

def read_lock(tdir):
    return read_json(lock_path(tdir))


def lock_is_stale(lock):
    """A lock is stale when its process is gone (same host) or it is very old."""
    created = parse_iso(lock.get("created_at"))
    age_h = None
    if created:
        age_h = (datetime.now(timezone.utc) - created).total_seconds() / 3600.0
    if lock.get("hostname") == socket.gethostname() and isinstance(lock.get("pid"), int):
        try:
            os.kill(lock["pid"], 0)
            return False
        except ProcessLookupError:
            return True
        except (PermissionError, OSError):
            return False
    return age_h is not None and age_h > 24


def check_lock(tdir, ckid):
    """Returns (ok, message). ok=False means another session holds the lock."""
    lock = read_lock(tdir)
    if not isinstance(lock, dict):
        return True, None
    if lock.get("checkout_id") == ckid:
        return True, None  # re-entrant for the same checkout
    holder = lock.get("checkout_path") or lock.get("checkout_id") or "another session"
    if lock_is_stale(lock):
        return False, (
            "ticket is locked by %s but the lock looks stale (no live process / very old). "
            "If you are sure no other session is working this ticket, remove %s manually and retry."
            % (holder, lock_path(tdir))
        )
    return False, "ticket is locked by another session (%s, since %s)." % (holder, lock.get("created_at"))


def acquire_lock(tdir, cwd):
    ckid = checkout_id(cwd)
    ok, msg = check_lock(tdir, ckid)
    if not ok:
        raise GateError(msg)
    write_json(lock_path(tdir), {
        "checkout_id": ckid,
        "checkout_path": checkout_root(cwd) or os.path.abspath(cwd),
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "created_at": now_iso(),
    })


def release_lock(tdir, cwd=None):
    lock = read_lock(tdir)
    if lock and cwd is not None and lock.get("checkout_id") != checkout_id(cwd):
        return False  # never release someone else's lock
    try:
        os.unlink(lock_path(tdir))
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Context resolution shared by hooks & helper scripts
# ---------------------------------------------------------------------------

def build_context(cwd, require_workspace=True):
    """Resolve everything deterministic about where we are. Raises GateError."""
    if not checkout_root(cwd):
        raise GateError("acs requires a git repository; %s is not inside one." % cwd)
    settings, sources = load_settings(cwd)
    if require_workspace and not sources:
        raise GateError("no .acs/settings.json found (user or project scope). Run /acs:init first.")
    workspace = validate_settings(settings, cwd, require_workspace=require_workspace)
    repo_id = repo_partition_id(cwd)
    if not repo_id:
        raise GateError("could not derive a repo identity (git remote or directory name).")
    return {
        "cwd": cwd,
        "settings": settings,
        "settings_sources": sources,
        "workspace": workspace,
        "repo_id": repo_id,
        "checkout_id": checkout_id(cwd),
        "checkout_root": checkout_root(cwd),
        "main_repo_root": main_repo_root(cwd),
        "plugin_root": plugin_root(),
    }


def parent_epic_dir(ctx, ticket):
    parent = (ticket or {}).get("parent")
    if not parent:
        return None, None
    pdir, _archived = find_ticket_partition(ctx["workspace"], ctx["repo_id"], parent)
    return parent, (pdir if os.path.isdir(pdir) else None)


def design_requirement(ctx, tdir, ticket):
    """Returns (required, design_dir, source) — the partition whose design.md applies:
    the ticket's own when it needs design, else the parent epic's when that needs design."""
    if ticket.get("needs_design"):
        return True, tdir, "own"
    parent, pdir = parent_epic_dir(ctx, ticket)
    if parent and pdir:
        parent_ticket = load_ticket(pdir)
        if parent_ticket and parent_ticket.get("needs_design"):
            return True, pdir, "parent"
    return False, None, None


# ---------------------------------------------------------------------------
# Pre-hook gates
# ---------------------------------------------------------------------------

def _require_completed(tdir, skill, ticket_id, hint):
    if not skill_completed(tdir, skill):
        status = last_run_status(tdir, skill)
        if status == "in_progress":
            detail = "/%s is recorded as in_progress for %s (crashed or still running elsewhere); re-run it to reconcile" % (skill, ticket_id)
        elif status:
            detail = "/%s last ended with status '%s' for %s" % (skill, status, ticket_id)
        else:
            detail = "/%s has not run for %s" % (skill, ticket_id)
        raise GateError("%s — %s." % (detail, hint))


def gate_create_prd(ctx, payload):
    return None


def gate_create_architecture(ctx, payload):
    root = ctx["checkout_root"]
    prd = os.path.join(root, ctx["settings"].get("prd_path", "docs/product"), "prd.md")
    if not os.path.isfile(prd):
        raise GateError("no PRD found at %s — run /acs:create-prd first (it also baselines existing products)." % prd)
    return None


def gate_create_project(ctx, payload):
    root = ctx["checkout_root"]
    arch = os.path.join(root, ctx["settings"].get("architecture_path", "docs/architecture"))
    tech_stack = os.path.join(arch, "hld", "tech-stack.md")
    if not os.path.isfile(tech_stack):
        raise GateError(
            "no architecture doc set found at %s (expected hld/tech-stack.md) — run /acs:create-architecture first." % arch
        )
    return None


def gate_create_ticket(ctx, payload):
    return None


def _resolve_ticket_for_gate(ctx, payload, skill):
    args_text = ""
    tool_input = payload.get("tool_input") or {}
    for key in ("args", "arguments", "argument"):
        if isinstance(tool_input.get(key), str):
            args_text = tool_input[key]
            break
    ticket_id, source = resolve_ticket_id(ctx["cwd"], ctx["settings"], ctx["workspace"], ctx["repo_id"], args_text=args_text)
    if not ticket_id:
        raise GateError(
            "could not resolve a ticket id for /%s (no argument, no session pointer, no ticket in the branch name). "
            "Pass it explicitly, e.g. /acs:%s %s-123." % (skill, skill, ctx["settings"].get("ticket_prefix", "SHOP"))
        )
    tdir, archived = find_ticket_partition(ctx["workspace"], ctx["repo_id"], ticket_id)
    if archived:
        raise GateError("ticket %s is done and archived (%s); nothing left to run." % (ticket_id, tdir))
    if not os.path.isdir(tdir):
        raise GateError("no workspace partition for %s (expected %s) — run /acs:create-ticket first." % (ticket_id, tdir))
    ticket = load_ticket(tdir)
    if not ticket:
        raise GateError("ticket file missing or corrupt at %s/ticket.json — treat as not created; run /acs:create-ticket." % tdir)
    ok, msg = check_lock(tdir, ctx["checkout_id"])
    if not ok:
        raise GateError(msg)
    return ticket_id, tdir, ticket


def gate_create_design(ctx, payload):
    ticket_id, tdir, ticket = _resolve_ticket_for_gate(ctx, payload, "create-design")
    _require_completed(tdir, "create-ticket", ticket_id, "run /acs:create-ticket first")
    if not ticket.get("needs_design"):
        raise GateError(
            "ticket %s is not flagged needs_design — /create-design only runs for design-significant tickets; "
            "go straight to /acs:create-spec %s." % (ticket_id, ticket_id)
        )
    return ticket_id


def gate_create_spec(ctx, payload):
    ticket_id, tdir, ticket = _resolve_ticket_for_gate(ctx, payload, "create-spec")
    _require_completed(tdir, "create-ticket", ticket_id, "run /acs:create-ticket first")
    required, ddir, source = design_requirement(ctx, tdir, ticket)
    if required:
        owner = ticket_id if source == "own" else (ticket.get("parent") or "parent epic")
        if ddir is None:
            raise GateError("ticket %s requires a design but its parent epic's partition was not found." % ticket_id)
        if not os.path.isfile(os.path.join(ddir, "design.md")):
            raise GateError("design.md is missing for %s — run /acs:create-design %s first." % (owner, owner))
        _require_completed(ddir, "create-design", owner, "run /acs:create-design %s first" % owner)
    return ticket_id


def gate_code(ctx, payload):
    ticket_id, tdir, ticket = _resolve_ticket_for_gate(ctx, payload, "code")
    recognized_lanes = ("TRIVIAL", "SMALL", "STANDARD", "COMPLEX")
    lane = ticket.get("lane")
    if lane not in recognized_lanes:
        lane = derive_lane(ticket.get("size"), ticket.get("stakes"), ticket.get("needs_design"), ticket.get("type"))
    if lane in ("TRIVIAL", "SMALL"):
        return ticket_id
    _require_completed(tdir, "create-spec", ticket_id, "run /acs:create-spec %s first" % ticket_id)
    specs = os.path.join(tdir, "specs")
    if not os.path.isdir(specs) or not [f for f in os.listdir(specs) if f.endswith(".md")]:
        raise GateError("no specs found in %s — run /acs:create-spec %s first." % (specs, ticket_id))
    return ticket_id


def gate_create_pr(ctx, payload):
    ticket_id, tdir, _ticket = _resolve_ticket_for_gate(ctx, payload, "create-pr")
    _require_completed(tdir, "code", ticket_id, "run /acs:code %s first" % ticket_id)
    state = load_state(tdir, "code", ticket_id)
    if state["states"].get("verifier_passed") is not True:
        raise GateError(
            "/code completed but its verifier did not pass for %s (verifier_passed != true in code-state.json); "
            "re-run /acs:code %s until the review loop reports zero findings." % (ticket_id, ticket_id)
        )
    return ticket_id


def _merge_pr_arg_text(payload):
    """Raw arg string the same way _resolve_ticket_for_gate reads it."""
    tool_input = payload.get("tool_input") or {}
    for key in ("args", "arguments", "argument"):
        if isinstance(tool_input.get(key), str):
            return tool_input[key]
    return ""


def gate_merge_pr(ctx, payload):
    # MAR-9 (C-3): the exempt non-ticket PR forms (--pr N / #N / PR URL / a bare
    # integer that is not a ticket id and no ticket resolves) short-circuit to
    # pass-through BEFORE the ticket gate runs. Every other input falls through to
    # the existing ticket gate verbatim (AC-8). The pre-hook dispatcher treats a
    # plain return (no GateError) as "allow", so returning None here = allow.
    args_text = _merge_pr_arg_text(payload)
    _resolved, _src = resolve_ticket_id(ctx["cwd"], ctx["settings"], ctx["workspace"],
                                        ctx["repo_id"], args_text=args_text)
    ticket_resolves = _src in ("pointer", "branch")
    kind, _pr_ref = classify_merge_pr_arg(
        args_text, ctx["settings"].get("ticket_prefix"), ticket_resolves=ticket_resolves)
    if kind == "exempt-pr":
        return None
    ticket_id, tdir, _ticket = _resolve_ticket_for_gate(ctx, payload, "merge-pr")
    pipeline = load_pipeline(tdir, ticket_id)
    candidates = ["create-pr"] + PRODUCT_SKILLS if pipeline.get("flow") != "product" else PRODUCT_SKILLS + ["create-pr"]
    for skill in candidates:
        state = read_json(state_path(tdir, skill))
        if isinstance(state, dict):
            pr = (state.get("states") or {}).get("pr") or {}
            if pr.get("url") or pr.get("number"):
                if last_run_status(tdir, skill) == "completed":
                    return ticket_id
    raise GateError(
        "no PR reference recorded for %s — /acs:create-pr (or the product-level skill) must complete first." % ticket_id
    )


GATES = {
    "create-prd": gate_create_prd,
    "create-architecture": gate_create_architecture,
    "create-project": gate_create_project,
    "create-ticket": gate_create_ticket,
    "create-design": gate_create_design,
    "create-spec": gate_create_spec,
    "code": gate_code,
    "create-pr": gate_create_pr,
    "merge-pr": gate_merge_pr,
}


def tracker_cli_warning(settings):
    provider = (settings.get("tracker") or {}).get("provider", "local")
    if provider == "github" and not shutil.which("gh"):
        return "tracker.provider is 'github' but the gh CLI is not installed — tracker sync will fail."
    if provider == "jira" and not shutil.which("acli"):
        return "tracker.provider is 'jira' but the acli CLI is not installed — tracker sync will fail."
    return None


# Every external tool the full acs workflow touches. kind: required (no pipeline
# without it), recommended (a major capability needs it), optional (graceful
# fallback). gh/acli are bumped to required by tracker provider. /init's Step 0b
# preflight reports these and offers to install the missing ones.
TOOLCHAIN = [
    {"name": "git", "kind": "required",
     "why": "version control — every skill operates on the repo and its branches",
     "install": {"macos": "xcode-select --install", "debian": "apt-get install -y git"}},
    {"name": "python3", "kind": "required",
     "why": "runs the hooks, gates, convention checker, and helper CLIs (stdlib only)",
     "install": {"macos": "brew install python", "debian": "apt-get install -y python3"}},
    {"name": "gh", "kind": "recommended",
     "why": "create-pr / merge-pr, labels, branch protection; required for github tracker sync",
     "install": {"macos": "brew install gh",
                 "debian": "see https://github.com/cli/cli/blob/trunk/docs/install_linux.md"}},
    {"name": "pre-commit", "kind": "recommended",
     "why": "shared, tracked local convention hooks (commit-msg + pre-push)",
     "install": {"macos": "brew install pre-commit",
                 "any": "pipx install pre-commit   # or: pip install --user pre-commit"}},
    {"name": "xmllint", "kind": "optional",
     "why": "full XSD validation of acs XML messages (structural fallback otherwise)",
     "install": {"macos": "preinstalled with libxml2", "debian": "apt-get install -y libxml2-utils"}},
    {"name": "acli", "kind": "optional",
     "why": "Jira tracker sync (only when tracker.provider = jira)",
     "install": {"any": "see https://developer.atlassian.com/cloud/acli/"}},
]


def _tool_version(name):
    """Best-effort one-line version string for an installed tool, or None."""
    try:
        out = subprocess.run([name, "--version"], capture_output=True, text=True, timeout=5)
        lines = (out.stdout or out.stderr or "").splitlines()
        return lines[0].strip() if lines else None
    except (OSError, subprocess.SubprocessError):
        return None


def check_toolchain(settings=None):
    """Status of every tool the full acs workflow uses (for /init's preflight).

    Returns a list of dicts: name, kind (required|recommended|optional), present
    (bool), version (str|None), why, install (platform -> command). A tool's kind
    is bumped to 'required' when settings make it mandatory (tracker provider).
    """
    provider = ((settings or {}).get("tracker") or {}).get("provider", "local")
    rows = []
    for spec in TOOLCHAIN:
        kind = spec["kind"]
        if spec["name"] == "gh" and provider == "github":
            kind = "required"
        if spec["name"] == "acli" and provider == "jira":
            kind = "required"
        present = shutil.which(spec["name"]) is not None
        rows.append({
            "name": spec["name"], "kind": kind, "present": present,
            "version": _tool_version(spec["name"]) if present else None,
            "why": spec["why"], "install": spec["install"],
        })
    return rows


def missing_tools(settings=None, kinds=("required", "recommended")):
    """Names of not-present tools in the given kinds — what /init should offer to install."""
    return [r["name"] for r in check_toolchain(settings)
            if r["kind"] in kinds and not r["present"]]


def run_pre(skill):
    """Entry point for pre-<skill>.py: read the hook payload from stdin, gate, exit 0/2."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()
    try:
        ctx = build_context(cwd)
        warn = tracker_cli_warning(ctx["settings"])
        if warn:
            sys.stderr.write("acs: warning: %s\n" % warn)
        GATES[skill](ctx, payload)
    except GateError as exc:
        sys.stderr.write("acs pre-%s: blocked — %s\n" % (skill, exc))
        sys.exit(2)
    except Exception as exc:  # fail closed: a gating system must not fail open
        sys.stderr.write("acs pre-%s: blocked — unexpected error in gate: %r\n" % (skill, exc))
        sys.exit(2)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Post-hook persistence
# ---------------------------------------------------------------------------

def _read_result_from_argv():
    """post-<skill>.py CLI: --result-file <path> | JSON on stdin, plus convenience flags."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-file", help="path to a JSON result document")
    parser.add_argument("--ticket", help="ticket id (overrides pointer/branch resolution)")
    parser.add_argument("--status", choices=[s for s in RUN_STATUSES if s != "in_progress"])
    parser.add_argument("--stop-reason")
    args = parser.parse_args()
    result = {}
    if args.result_file:
        data = read_json(args.result_file)
        if not isinstance(data, dict):
            sys.stderr.write("acs: result file %s is missing or not a JSON object\n" % args.result_file)
            sys.exit(1)
        result = data
    elif not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            try:
                result = json.loads(raw)
            except json.JSONDecodeError as exc:
                sys.stderr.write("acs: invalid JSON result on stdin: %s\n" % exc)
                sys.exit(1)
    if args.status:
        result["status"] = args.status
    if args.stop_reason:
        result["stop_reason"] = args.stop_reason
    result.setdefault("status", "completed")
    return result, args.ticket


def _epic_auto_done(ctx, ticket):
    """When the merged ticket is the last open child of an epic, mark the epic done."""
    parent_id, pdir = parent_epic_dir(ctx, ticket)
    if not parent_id or not pdir:
        return None
    index = read_json(index_path(ctx["workspace"], ctx["repo_id"])) or {"tickets": {}}
    parent_ticket = load_ticket(pdir)
    children = (parent_ticket or {}).get("children") or (index["tickets"].get(parent_id, {}).get("children")) or []
    if not children:
        return None
    for child in children:
        if child == ticket["id"]:
            continue
        entry = index["tickets"].get(child)
        if not entry or entry.get("status") != "done":
            return None
    if parent_ticket:
        parent_ticket["status"] = "done"
        save_ticket(pdir, parent_ticket)
        update_index(ctx["workspace"], ctx["repo_id"], parent_ticket)
        return parent_id
    return None


def _archive_partition(ctx, tdir, ticket_id):
    dest_root = archive_dir(ctx["workspace"], ctx["repo_id"])
    os.makedirs(dest_root, exist_ok=True)
    dest = os.path.join(dest_root, ticket_id)
    if os.path.isdir(dest):
        dest = os.path.join(dest_root, "%s-%s" % (ticket_id, now_iso().replace(":", "")))
    shutil.move(tdir, dest)
    return dest


def _clear_pointers_for_ticket(ctx, ticket_id):
    sdir = sessions_dir(ctx["workspace"], ctx["repo_id"])
    if not os.path.isdir(sdir):
        return
    for name in os.listdir(sdir):
        if not name.endswith(".json"):
            continue
        pointer = read_json(os.path.join(sdir, name))
        if isinstance(pointer, dict) and pointer.get("ticket_id") == ticket_id:
            try:
                os.unlink(os.path.join(sdir, name))
            except OSError:
                pass


def run_post(skill):
    """Entry point for post-<skill>.py."""
    result, explicit_ticket = _read_result_from_argv()
    cwd = os.getcwd()
    try:
        ctx = build_context(cwd)
    except GateError as exc:
        sys.stderr.write("acs post-%s: %s\n" % (skill, exc))
        sys.exit(1)

    ticket_id, _src = resolve_ticket_id(cwd, ctx["settings"], ctx["workspace"], ctx["repo_id"], explicit=explicit_ticket)
    if not ticket_id:
        sys.stderr.write("acs post-%s: could not resolve the ticket id (pass --ticket).\n" % skill)
        sys.exit(1)
    tdir, archived = find_ticket_partition(ctx["workspace"], ctx["repo_id"], ticket_id)
    if archived or not os.path.isdir(tdir):
        sys.stderr.write("acs post-%s: no active partition for %s.\n" % (skill, ticket_id))
        sys.exit(1)

    status = result.get("status", "completed")
    state, entry = finalize_run(tdir, skill, ticket_id, result)
    flow = "product" if skill in PRODUCT_SKILLS else "ticket"
    summary = result.get("handoff_summary") or result.get("stop_reason")
    update_pipeline(tdir, ticket_id, skill, status, summary=summary, flow=flow)

    ticket = load_ticket(tdir)
    epic_done = None
    archived_to = None
    if ticket:
        if status == "completed":
            if skill == "create-pr" and ticket.get("status") != "done":
                ticket["status"] = "in_review"
                save_ticket(tdir, ticket)
            if skill in PRODUCT_SKILLS and (result.get("states") or {}).get("pr") and ticket.get("status") != "done":
                ticket["status"] = "in_review"
                save_ticket(tdir, ticket)
            if skill == "merge-pr":
                ticket["status"] = "done"
                save_ticket(tdir, ticket)
        update_index(ctx["workspace"], ctx["repo_id"], ticket)

    pr_number = ((result.get("states") or {}).get("pr") or {}).get("number")
    update_metrics(
        ctx["workspace"], ctx["repo_id"], run_entry=entry,
        pr_created=(status == "completed" and bool((result.get("states") or {}).get("pr"))
                    and skill in (["create-pr"] + PRODUCT_SKILLS)),
        pr_merged=(skill == "merge-pr" and status == "completed"),
        pr_number=pr_number,
    )

    release_lock(tdir, cwd)

    if skill == "merge-pr" and status == "completed" and ticket:
        epic_done = _epic_auto_done(ctx, ticket)
        update_index(ctx["workspace"], ctx["repo_id"], ticket, archived=True)
        _clear_pointers_for_ticket(ctx, ticket_id)
        archived_to = _archive_partition(ctx, tdir, ticket_id)

    out = {"ok": True, "skill": skill, "ticket_id": ticket_id, "status": status}
    if archived_to:
        out["archived_to"] = archived_to
    if epic_done:
        out["epic_marked_done"] = epic_done
    print(json.dumps(out, indent=2))
    sys.exit(0)


# ---------------------------------------------------------------------------
# SessionEnd safety net
# ---------------------------------------------------------------------------

def session_end(payload):
    """Finalize any run this checkout left in_progress as `interrupted` and release
    its lock — abnormal endings must still write state (docs/requirements/hooks.md)."""
    cwd = payload.get("cwd") or os.getcwd()
    try:
        ctx = build_context(cwd)
    except GateError:
        return  # uninitialized repo: nothing to clean up
    pointer = read_json(pointer_path(ctx["workspace"], ctx["repo_id"], ctx["checkout_id"]))
    if not isinstance(pointer, dict) or not pointer.get("ticket_id"):
        return
    ticket_id = pointer["ticket_id"]
    tdir, archived = find_ticket_partition(ctx["workspace"], ctx["repo_id"], ticket_id)
    if archived or not os.path.isdir(tdir):
        return
    lock = read_lock(tdir)
    if not (isinstance(lock, dict) and lock.get("checkout_id") == ctx["checkout_id"]):
        return  # not our session's ticket anymore
    for skill in HOOKED_SKILLS:
        state = read_json(state_path(tdir, skill))
        if not isinstance(state, dict):
            continue
        runs = state.get("runs") or []
        if runs and isinstance(runs[-1], dict) and runs[-1].get("status") == "in_progress":
            _state, entry = finalize_run(tdir, skill, ticket_id, {
                "status": "interrupted",
                "stop_reason": "session ended while the skill was in progress",
            })
            update_pipeline(tdir, ticket_id, skill, "interrupted",
                            summary="session ended mid-skill",
                            flow="product" if skill in PRODUCT_SKILLS else "ticket")
            # keep repo-level metrics consistent with the ticket ledger:
            # an interrupted run still spent time/tokens
            update_metrics(ctx["workspace"], ctx["repo_id"], run_entry=entry)
    release_lock(tdir, cwd)
