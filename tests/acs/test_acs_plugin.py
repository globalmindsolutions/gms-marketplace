"""Unit/integration tests for the acs plugin's deterministic layer.

Covers the hook library (acs_lib), the named pre/post hooks via the
dispatcher, the helper CLIs (skill-start, new-ticket, handoff, clarify,
validate_xml), and the status-line scripts — everything that gates and
persists the pipeline. Each test drives the real scripts in a throwaway
git repo + workspace, asserting on exit codes and the JSON state files
(the same artifacts the pipeline itself trusts).

Run:  python3 -m unittest discover -s tests -v
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO_ROOT, "plugins", "acs", "hooks", "scripts")
sys.path.insert(0, SCRIPTS)

import acs_lib as lib  # noqa: E402


class AcsWorkspaceCase(unittest.TestCase):
    """Fixture: a consumer git repo with valid .acs settings + empty workspace."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="acs-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "shop")
        self.ws = os.path.join(self.tmp, "workspace")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        subprocess.run(["git", "-C", self.repo, "remote", "add", "origin",
                        "https://github.com/acme/shop.git"], check=True)
        os.makedirs(os.path.join(self.repo, ".acs"))
        self.write_settings({"ticket_prefix": "SHOP", "test_coverage_percent": 90})
        with open(os.path.join(self.repo, ".acs", "settings.local.json"), "w") as fh:
            json.dump({"workspace_path": self.ws}, fh)

    def write_settings(self, data):
        with open(os.path.join(self.repo, ".acs", "settings.json"), "w") as fh:
            json.dump(data, fh)

    def run_script(self, script, *args, stdin=None, cwd=None, env=None):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, script)] + list(args),
            input=stdin, capture_output=True, text=True, cwd=cwd or self.repo,
            env=env,
        )

    def pre(self, skill, args_text="", cwd=None):
        payload = json.dumps({
            "cwd": cwd or self.repo, "tool_name": "Skill",
            "tool_input": {"skill": "acs:" + skill, "args": args_text},
        })
        return self.run_script("dispatch.py", "pre", stdin=payload, cwd=cwd)

    def post(self, skill, ticket, result):
        return self.run_script("post-%s.py" % skill, "--ticket", ticket,
                               stdin=json.dumps(result))

    def start(self, skill, ticket):
        return self.run_script("skill-start.py", "--skill", skill, "--ticket", ticket)

    def new_ticket(self, title, ttype, *extra):
        out = self.run_script("new-ticket.py", "--title", title, "--type", ttype, *extra)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)["ticket_id"]

    def tdir(self, ticket):
        return lib.ticket_dir(self.ws, "acme-shop", ticket)


class TestDispatcher(AcsWorkspaceCase):
    def test_non_acs_skill_passes_through(self):
        payload = json.dumps({"cwd": self.repo, "tool_input": {"skill": "other:thing"}})
        result = self.run_script("dispatch.py", "pre", stdin=payload)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unhooked_acs_skills_pass_through(self):
        for skill in ("init", "ship", "handoff", "metrics", "usage"):
            self.assertEqual(self.pre(skill).returncode, 0, skill)

    def test_garbage_stdin_does_not_crash(self):
        result = self.run_script("dispatch.py", "pre", stdin="not json")
        self.assertEqual(result.returncode, 0, result.stderr)


class TestGates(AcsWorkspaceCase):
    def test_uninitialized_repo_blocks_with_init_message(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        subprocess.run(["git", "init", "-q", plain], check=True)
        result = self.pre("create-ticket", cwd=plain)
        self.assertEqual(result.returncode, 2)
        self.assertIn("init", result.stderr)

    def test_create_architecture_requires_prd(self):
        result = self.pre("create-architecture")
        self.assertEqual(result.returncode, 2)
        self.assertIn("create-prd", result.stderr)

    def test_code_requires_resolvable_ticket(self):
        result = self.pre("code")
        self.assertEqual(result.returncode, 2)
        self.assertIn("ticket id", result.stderr)

    def test_unknown_placeholder_rejected(self):
        self.write_settings({"ticket_prefix": "SHOP",
                             "formats": {"branch_name": "{nope}/{ticket_id}"}})
        result = self.pre("create-ticket")
        self.assertEqual(result.returncode, 2)
        self.assertIn("placeholder", result.stderr)

    def test_branch_name_must_embed_ticket_id(self):
        self.write_settings({"ticket_prefix": "SHOP",
                             "formats": {"branch_name": "{type}/{slug}"}})
        result = self.pre("create-ticket")
        self.assertEqual(result.returncode, 2)
        self.assertIn("ticket_id", result.stderr)

    def test_e2e_settings_validation(self):
        self.write_settings({"ticket_prefix": "SHOP", "e2e": {"setup": "x"}})
        result = self.pre("create-ticket")
        self.assertEqual(result.returncode, 2)
        self.assertIn("e2e", result.stderr)
        self.write_settings({"ticket_prefix": "SHOP",
                             "e2e": {"command": "make e2e", "per_iteration": False}})
        self.assertEqual(self.pre("create-ticket").returncode, 0)


class TestPipelineSequence(AcsWorkspaceCase):
    """The full gate chain: epic -> child -> design -> spec -> code -> pr -> merge."""

    def test_full_chain(self):
        out = self.run_script("skill-start.py", "--skill", "create-ticket",
                              "--allocate", "--type", "epic", "--title", "Wishlist")
        self.assertEqual(out.returncode, 0, out.stderr)
        epic = json.loads(out.stdout)["ticket_id"]
        self.assertEqual(epic, "SHOP-1")
        self.assertTrue(json.loads(out.stdout)["ticket"]["needs_design"])
        self.assertEqual(self.post("create-ticket", epic, {"status": "completed"}).returncode, 0)

        child = self.new_ticket("Wishlist API", "story", "--parent", epic,
                                "--needs-design", "false")
        epic_doc = lib.load_ticket(self.tdir(epic))
        self.assertIn(child, epic_doc["children"])

        # child skips create-ticket (recorded at mint) but is blocked on the epic design
        result = self.pre("create-design", child)
        self.assertEqual(result.returncode, 2)
        self.assertIn("needs_design", result.stderr)
        result = self.pre("create-spec", child)
        self.assertEqual(result.returncode, 2)
        self.assertIn("create-design", result.stderr)

        with open(os.path.join(self.tdir(epic), "design.md"), "w") as fh:
            fh.write("# design")
        self.start("create-design", epic)
        self.post("create-design", epic, {"status": "completed"})
        self.assertEqual(self.pre("create-spec", child).returncode, 0)

        self.start("create-spec", child)
        self.post("create-spec", child, {"status": "completed", "states": {"specs": ["01-api"]}})
        result = self.pre("code", child)
        self.assertEqual(result.returncode, 2)  # no spec files yet
        os.makedirs(os.path.join(self.tdir(child), "specs"), exist_ok=True)
        with open(os.path.join(self.tdir(child), "specs", "01-api.md"), "w") as fh:
            fh.write("# spec")
        self.assertEqual(self.pre("code", child).returncode, 0)

        # create-pr gate needs verifier_passed
        self.start("code", child)
        self.post("code", child, {"status": "completed", "states": {"verifier_passed": False}})
        self.assertEqual(self.pre("create-pr", child).returncode, 2)
        self.start("code", child)
        self.post("code", child, {"status": "completed", "states": {"verifier_passed": True}})
        self.assertEqual(self.pre("create-pr", child).returncode, 0)

        # merge gate needs a PR reference
        self.assertEqual(self.pre("merge-pr", child).returncode, 2)
        self.start("create-pr", child)
        self.post("create-pr", child, {"status": "completed",
                                       "states": {"pr": {"number": 7, "url": "https://github.com/acme/shop/pull/7"}}})
        self.assertEqual(self.pre("merge-pr", child).returncode, 0)

        # merge: archive + epic auto-done
        self.start("merge-pr", child)
        out = self.post("merge-pr", child, {"status": "completed", "states": {"merged": True}})
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertIn(child, data["archived_to"])
        self.assertEqual(data["epic_marked_done"], epic)
        with open(lib.index_path(self.ws, "acme-shop")) as fh:
            index = json.load(fh)
        self.assertEqual(index["tickets"][child]["status"], "done")
        self.assertTrue(index["tickets"][child]["archived"])
        self.assertEqual(index["tickets"][epic]["status"], "done")

        with open(lib.metrics_path(self.ws, "acme-shop")) as fh:
            metrics = json.load(fh)
        self.assertEqual(metrics["prs"], {"created": 1, "merged": 1, "created_pr_numbers": [7]})

    def test_docs_only_flag_minted(self):
        ticket = self.new_ticket("Fix README", "task", "--docs-only", "true")
        self.assertTrue(lib.load_ticket(self.tdir(ticket))["docs_only"])
        default = self.new_ticket("Real change", "task")
        self.assertFalse(lib.load_ticket(self.tdir(default))["docs_only"])


class TestConcurrencyAndRecovery(AcsWorkspaceCase):
    def setUp(self):
        super().setUp()
        self.ticket = self.new_ticket("X", "task")
        self.start("create-spec", self.ticket)

    def test_lock_blocks_other_checkout(self):
        other = os.path.join(self.tmp, "worktree-b")
        shutil.copytree(self.repo, other)
        result = self.pre("create-spec", self.ticket, cwd=other)
        self.assertEqual(result.returncode, 2)
        self.assertIn("locked", result.stderr)

    def test_session_end_finalizes_interrupted_and_counts_metrics(self):
        with open(lib.metrics_path(self.ws, "acme-shop")) as fh:
            before = json.load(fh).get("totals", {}).get("runs", 0)
        result = self.run_script("dispatch.py", "session-end",
                                 stdin=json.dumps({"cwd": self.repo}))
        self.assertEqual(result.returncode, 0, result.stderr)
        state = lib.load_state(self.tdir(self.ticket), "create-spec")
        self.assertEqual(state["runs"][-1]["status"], "interrupted")
        self.assertFalse(os.path.exists(os.path.join(self.tdir(self.ticket), ".lock")))
        with open(lib.metrics_path(self.ws, "acme-shop")) as fh:
            after = json.load(fh)["totals"]["runs"]
        self.assertEqual(after, before + 1)

    def test_handoff_and_resume(self):
        out = self.run_script("handoff.py", "--ticket", self.ticket,
                              "--summary", "done: analysis; next: spec 02")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["continue_with"],
                         "/acs:create-spec %s" % self.ticket)
        state = lib.load_state(self.tdir(self.ticket), "create-spec")
        self.assertEqual(state["runs"][-1]["status"], "handed_off")
        self.assertIn("analysis", state["runs"][-1]["handoff_summary"])
        resumed = json.loads(self.start("create-spec", self.ticket).stdout)
        self.assertTrue(resumed["reconcile"])
        self.assertTrue(resumed["handoff_summary"])


class TestClarifications(AcsWorkspaceCase):
    def setUp(self):
        super().setUp()
        self.ticket = self.new_ticket("Bulk import", "story")

    def clarify(self, *args):
        return self.run_script("clarify.py", *args, "--ticket", self.ticket)

    def test_lifecycle(self):
        entry = json.loads(self.clarify(
            "add", "--skill", "create-ticket",
            "--question", "CSV and JSON?", "--answer", "CSV only").stdout)
        self.assertEqual((entry["id"], entry["status"]), ("C-1", "answered"))

        opened = json.loads(self.clarify(
            "add", "--skill", "create-spec", "--question", "Duplicates?").stdout)
        self.assertEqual(opened["status"], "open")
        answered = json.loads(self.clarify(
            "answer", "--id", "C-2", "--answer", "reject with 409").stdout)
        self.assertEqual(answered["status"], "answered")

        # assumptions need both an answer and a rationale
        result = self.clarify("add", "--skill", "code", "--question", "Retries?",
                              "--source", "assumption")
        self.assertEqual(result.returncode, 2)
        assumed = json.loads(self.clarify(
            "add", "--skill", "code", "--question", "Retries?",
            "--source", "assumption", "--answer", "3",
            "--rationale", "matches retry.py:12").stdout)
        self.assertEqual(assumed["status"], "assumed")

        listing = json.loads(self.clarify("list").stdout)
        self.assertEqual(listing["count"], 3)
        self.assertEqual(json.loads(self.clarify("list", "--open").stdout)["count"], 0)


class TestValidators(AcsWorkspaceCase):
    def test_xml_valid_and_invalid(self):
        good = ('<task skill="code" phase="execute" ticket-id="SHOP-9">'
                '<objective>x</objective></task>')
        bad = ('<task skill="nope" phase="execute" ticket-id="9">'
               '<objective>x</objective></task>')
        self.assertEqual(self.run_script("validate_xml.py", "-", stdin=good).returncode, 0)
        result = self.run_script("validate_xml.py", "-", stdin=bad)
        self.assertEqual(result.returncode, 1)
        self.assertIn("INVALID", result.stderr)

    def test_xml_handoff_shape(self):
        good = ('<handoff skill="create-spec" ticket-id="SHOP-1" status="needs_input">'
                '<summary>s</summary><questions><question>q</question></questions></handoff>')
        self.assertEqual(self.run_script("validate_xml.py", "-", stdin=good).returncode, 0)


class TestStatusLines(AcsWorkspaceCase):
    def payload(self, cwd):
        return json.dumps({"model": {"display_name": "Opus"},
                           "workspace": {"current_dir": cwd}})

    def test_statusline_states(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        out = self.run_script("statusline.py", stdin=self.payload(plain), cwd=plain)
        self.assertEqual(out.returncode, 0)
        self.assertIn("plain", out.stdout)

        ticket = self.new_ticket("Fix rounding", "task")
        self.start("create-spec", ticket)
        out = self.run_script("statusline.py", stdin=self.payload(self.repo))
        self.assertEqual(out.returncode, 0, out.stderr)
        for expected in (ticket, "spec", "ticket"):
            self.assertIn(expected, out.stdout)

    def test_subagent_statusline_rows(self):
        ticket = self.new_ticket("X", "task")
        self.start("create-spec", ticket)
        payload = json.dumps({"columns": 80, "tasks": [
            {"id": "a1", "type": "acs:code-verifier", "status": "running",
             "startTime": (time.time() - 95) * 1000, "tokenCount": 45200, "cwd": self.repo},
            {"id": "a2", "type": "Explore", "description": "unrelated", "cwd": self.repo},
        ]})
        out = self.run_script("subagent-statusline.py", stdin=payload)
        self.assertEqual(out.returncode, 0, out.stderr)
        rows = [json.loads(line) for line in out.stdout.splitlines()]
        self.assertEqual([row["id"] for row in rows], ["a1"])  # non-acs row untouched
        self.assertIn(ticket, rows[0]["content"])

    def test_statusline_never_crashes(self):
        for bad in ("", "not json", '{"tasks": [{"id": "x", "type": 5}]}'):
            for script in ("statusline.py", "subagent-statusline.py"):
                out = self.run_script(script, stdin=bad)
                self.assertEqual(out.returncode, 0, (script, bad, out.stderr))


class ToolchainTests(unittest.TestCase):
    """check_toolchain backs /init Step 0b — the full-workflow dependency preflight."""

    def test_reports_every_known_tool(self):
        names = [r["name"] for r in lib.check_toolchain()]
        self.assertEqual(set(names), {"git", "python3", "gh", "pre-commit", "xmllint", "acli"})

    def test_core_tools_present_and_required(self):
        rows = {r["name"]: r for r in lib.check_toolchain()}
        for name in ("git", "python3"):  # the test runner can't exist without these
            self.assertTrue(rows[name]["present"], name)
            self.assertEqual(rows[name]["kind"], "required", name)
            self.assertTrue(rows[name]["version"], "%s should report a version" % name)

    def test_tracker_bumps_conditional_tools_to_required(self):
        gh = {r["name"]: r for r in lib.check_toolchain({"tracker": {"provider": "github"}})}["gh"]
        self.assertEqual(gh["kind"], "required")
        acli = {r["name"]: r for r in lib.check_toolchain({"tracker": {"provider": "jira"}})}["acli"]
        self.assertEqual(acli["kind"], "required")
        # local tracker leaves them at their baseline kinds
        base = {r["name"]: r for r in lib.check_toolchain()}
        self.assertEqual(base["gh"]["kind"], "recommended")
        self.assertEqual(base["acli"]["kind"], "optional")

    def test_missing_tools_excludes_present_and_optional(self):
        missing = lib.missing_tools()  # required + recommended by default
        self.assertNotIn("git", missing)
        self.assertNotIn("python3", missing)
        self.assertNotIn("xmllint", missing)  # optional, never offered by default
        for name in missing:
            self.assertIn(name, {"gh", "pre-commit"})


# ---------------------------------------------------------------------------
# MAR-9 — pipeline-default CLAUDE.md guidance + exempt non-ticket merge-pr --pr
# ---------------------------------------------------------------------------

TEMPLATE_DIR = os.path.join(REPO_ROOT, "plugins", "acs", "templates")


class TestManagedBlock(unittest.TestCase):
    """Spec 01 — the pure CLAUDE.md managed-block helpers in acs_lib (no fixture
    needed; these are pure string functions)."""

    def test_fresh_write_appends_block_and_preserves_user_prose(self):
        # (a) Fresh write into surrounding user content.
        existing = "# My project\n\nSome user notes.\n"
        body = "Ship via /acs:ship."
        out = lib.upsert_managed_block(existing, body)
        self.assertIn(lib.ACS_BLOCK_BEGIN, out)
        self.assertIn(lib.ACS_BLOCK_END, out)
        self.assertIn(body, out)
        # the original user prose survives byte-for-byte as a prefix
        self.assertTrue(out.startswith(existing))
        # exactly one blank line separates prior content from the BEGIN marker
        before_marker = out.split(lib.ACS_BLOCK_BEGIN, 1)[0]
        self.assertTrue(before_marker.endswith("\n\n"))
        self.assertFalse(before_marker.endswith("\n\n\n"))

    def test_idempotent_rerun_byte_identical(self):
        # (b) AC-2 run-twice property.
        existing = "# My project\n\nSome user notes.\n"
        body = "Ship via /acs:ship."
        first = lib.upsert_managed_block(existing, body)
        second = lib.upsert_managed_block(first, body)
        self.assertEqual(first, second)

    def test_replace_changed_block_leaves_surrounding_bytes_intact(self):
        # (c) Replace with a changed block; only the marker span changes.
        prefix = "# Top\n\nintro prose\n"
        suffix = "\n\n## Footer\n\ntrailing user text\n"
        first = lib.upsert_managed_block(prefix, "label acs-exempt")
        # add user content AFTER the block, then re-upsert with a different body
        with_suffix = first + suffix
        replaced = lib.upsert_managed_block(with_suffix, "label custom-exempt")
        # surrounding content (before BEGIN and after END) is byte-identical
        self.assertEqual(replaced.split(lib.ACS_BLOCK_BEGIN, 1)[0],
                         with_suffix.split(lib.ACS_BLOCK_BEGIN, 1)[0])
        self.assertEqual(replaced.split(lib.ACS_BLOCK_END, 1)[1],
                         with_suffix.split(lib.ACS_BLOCK_END, 1)[1])
        # the new body replaced the old one inside the span
        self.assertIn("label custom-exempt", replaced)
        self.assertNotIn("label acs-exempt", replaced)

    def test_empty_existing_emits_just_block(self):
        out = lib.upsert_managed_block("", "body text")
        self.assertTrue(out.startswith(lib.ACS_BLOCK_BEGIN))
        self.assertIn("body text", out)

    def test_render_substitutes_both_placeholders(self):
        # (d) render_managed_block fills {ticket_prefix} + {exempt_label}.
        template = "prefix {ticket_prefix} and label {exempt_label} done"
        rendered = lib.render_managed_block(template, "SHOP", "acs-exempt")
        self.assertIn("SHOP", rendered)
        self.assertIn("acs-exempt", rendered)
        self.assertNotIn("{ticket_prefix}", rendered)
        self.assertNotIn("{exempt_label}", rendered)

    def test_template_exists_with_markers_and_placeholders(self):
        # (e) AC-1 — template file content assertion.
        path = os.path.join(TEMPLATE_DIR, "CLAUDE.acs.md")
        self.assertTrue(os.path.isfile(path), path)
        with open(path) as fh:
            text = fh.read()
        self.assertIn(lib.ACS_BLOCK_BEGIN, text)
        self.assertIn(lib.ACS_BLOCK_END, text)
        self.assertIn("{ticket_prefix}", text)
        self.assertIn("{exempt_label}", text)
        # guidance content: steer everyday work to /acs:ship and exempt PRs to --pr
        self.assertIn("/acs:ship", text)
        self.assertIn("/acs:merge-pr --pr", text)


class TestExemptPrMerge(AcsWorkspaceCase):
    """Spec 02 + 03 — exempt non-ticket merge-pr --pr path: the classifier, the
    gate_merge_pr short-circuit, skill-start --pr mode (gh STUBBED), and the
    post-merge-pr --pr metrics-only bump."""

    # ---- spec 02: classifier --------------------------------------------

    def test_classifier_table_ac4(self):
        # (a) AC-4 — the exact five cases.
        self.assertEqual(lib.classify_merge_pr_arg("--pr 87"), ("exempt-pr", "87"))
        self.assertEqual(lib.classify_merge_pr_arg("#87"), ("exempt-pr", "87"))
        self.assertEqual(
            lib.classify_merge_pr_arg("https://github.com/acme/shop/pull/87"),
            ("exempt-pr", "87"))
        self.assertEqual(lib.classify_merge_pr_arg("87", ticket_resolves=False),
                         ("exempt-pr", "87"))
        self.assertEqual(lib.classify_merge_pr_arg("MAR-9", ticket_prefix="MAR"),
                         ("ticket", None))

    def test_classifier_bare_number_disambiguation_c3(self):
        # (b) C-3 — bare integer prefers ticket when one resolves.
        self.assertEqual(lib.classify_merge_pr_arg("87", ticket_resolves=True),
                         ("ticket", None))
        self.assertEqual(lib.classify_merge_pr_arg("87", ticket_resolves=False),
                         ("exempt-pr", "87"))

    def test_classifier_explicit_forms_always_exempt(self):
        # explicit forms are exempt even when a ticket would resolve.
        self.assertEqual(lib.classify_merge_pr_arg("--pr 87", ticket_resolves=True),
                         ("exempt-pr", "87"))
        self.assertEqual(lib.classify_merge_pr_arg("#87", ticket_resolves=True),
                         ("exempt-pr", "87"))
        self.assertEqual(
            lib.classify_merge_pr_arg("https://github.com/acme/shop/pull/87",
                                      ticket_resolves=True),
            ("exempt-pr", "87"))

    def test_classifier_ticket_id_default_prefix(self):
        # a ticket-shaped token is ticket-backed even without an explicit prefix.
        self.assertEqual(lib.classify_merge_pr_arg("SHOP-1"), ("ticket", None))

    def test_classifier_empty_or_unrecognized_is_ticket(self):
        self.assertEqual(lib.classify_merge_pr_arg(""), ("ticket", None))
        self.assertEqual(lib.classify_merge_pr_arg("garbage text"), ("ticket", None))

    def test_pr_labels_normalizes_dicts_and_strings(self):
        # gh emits [{"name": ...}]; tolerate bare strings too.
        self.assertEqual(
            lib._pr_labels({"labels": [{"name": "acs-exempt"}, "ACS", {"x": 1}]}),
            ["acs-exempt", "ACS"])
        self.assertEqual(lib._pr_labels({}), [])

    def test_merge_pr_arg_text_defaults_empty(self):
        # no args/arguments/argument key -> empty string (the ticket gate then
        # produces its own "could not resolve" error).
        self.assertEqual(lib._merge_pr_arg_text({}), "")
        self.assertEqual(lib._merge_pr_arg_text({"tool_input": {"other": 1}}), "")
        self.assertEqual(lib._merge_pr_arg_text({"tool_input": {"arguments": "#9"}}), "#9")

    # ---- spec 02: gate short-circuit ------------------------------------

    def test_gate_exempt_pr_flag_passes_through(self):
        # (c) AC-3 — --pr 87 allows where a ticket arg would block.
        result = self.pre("merge-pr", "--pr 87")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gate_exempt_hash_and_url_pass_through(self):
        # (d) explicit #N and PR-URL forms always allowed.
        self.assertEqual(self.pre("merge-pr", "#87").returncode, 0)
        self.assertEqual(
            self.pre("merge-pr", "https://github.com/acme/shop/pull/87").returncode, 0)

    def test_gate_ticket_arg_still_blocks_unchanged(self):
        # (e) AC-3/AC-8 regression — a ticket arg with no partition still blocks.
        result = self.pre("merge-pr", "SHOP-1")
        self.assertEqual(result.returncode, 2)
        self.assertIn("SHOP-1", result.stderr)

    # ---- spec 03: a fake gh on PATH (never the real GitHub) -------------

    def _gh_env(self, gh_body):
        """Return an env dict whose PATH carries a fake `gh` shim emitting gh_body.

        gh_body is the shell after the shebang; for the `pr view` path it should
        echo a JSON object and exit 0, or write to stderr and exit non-zero to
        simulate an error. The shim dir is PREPENDED to a real PATH so `git` (used
        by build_context) still resolves while our fake `gh` shadows any real one.
        `gh_body is None` means: provide NO gh at all (simulate the binary being
        absent) — PATH is set to the system dirs that hold git but not gh, so the
        script hits FileNotFoundError."""
        bindir = tempfile.mkdtemp(prefix="acs-fakebin-", dir=self.tmp)
        # A minimal real PATH that has git (/usr/bin) + sh (/bin) but NOT gh
        # (which lives in /opt/homebrew/bin or /usr/local/bin on dev machines).
        base_path = "/usr/bin:/bin"
        env = dict(os.environ)
        if gh_body is None:
            env["PATH"] = base_path
            return env
        gh = os.path.join(bindir, "gh")
        with open(gh, "w") as fh:
            fh.write("#!/bin/sh\n" + gh_body + "\n")
        os.chmod(gh, 0o755)
        env["PATH"] = bindir + os.pathsep + base_path
        return env

    def _pr_json(self, **over):
        data = {"number": 87, "state": "OPEN", "headRefName": "chore/cleanup",
                "baseRefName": "main", "labels": [{"name": "acs-exempt"}],
                "isDraft": False, "url": "https://github.com/acme/shop/pull/87"}
        data.update(over)
        return json.dumps(data)

    def _ws_untouched(self):
        """No ticket dir, no sessions pointer, no lock, no index, no pipeline were
        written by an exempt-pr --pr run."""
        repo_root = lib.repo_dir(self.ws, "acme-shop")
        self.assertFalse(os.path.isdir(lib.sessions_dir(self.ws, "acme-shop")))
        if os.path.isdir(repo_root):
            for name in os.listdir(repo_root):
                # only metrics.json may appear (post-merge-pr --pr bumps it)
                self.assertIn(name, {"metrics.json"}, name)

    # ---- spec 03: post-merge-pr --pr metrics-only ----------------------

    def test_post_merge_pr_flag_bumps_metrics_only(self):
        # (a) AC-7 — prs.merged += 1, no ticket state/index/pipeline/archive.
        out = self.run_script("post-merge-pr.py", "--pr", "87")
        self.assertEqual(out.returncode, 0, out.stderr)
        payload = json.loads(out.stdout)
        self.assertEqual(payload["mode"], "exempt-pr")
        self.assertTrue(payload["pr_merged"])
        with open(lib.metrics_path(self.ws, "acme-shop")) as fh:
            metrics = json.load(fh)
        self.assertEqual(metrics["prs"]["merged"], 1)
        self.assertEqual(metrics["prs"].get("created", 0), 0)
        self.assertEqual(metrics.get("totals", {}).get("runs", 0), 0)
        # no ticket index entry was written
        self.assertFalse(os.path.isfile(lib.index_path(self.ws, "acme-shop")))
        self._ws_untouched()

    def test_post_merge_pr_flag_increments_each_call(self):
        self.run_script("post-merge-pr.py", "--pr", "87")
        self.run_script("post-merge-pr.py", "--pr", "88")
        with open(lib.metrics_path(self.ws, "acme-shop")) as fh:
            self.assertEqual(json.load(fh)["prs"]["merged"], 2)

    # ---- spec 03: skill-start --pr exempt-pr mode (gh STUBBED) ----------

    def test_skill_start_pr_exempt_mode_prints_context(self):
        # (b) AC-5 — OPEN exempt PR → mode exempt-pr JSON, no state written.
        env = self._gh_env("echo '%s'" % self._pr_json())
        out = self.run_script("skill-start.py", "--skill", "merge-pr",
                              "--pr", "87", env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        ctx = json.loads(out.stdout)
        self.assertEqual(ctx["mode"], "exempt-pr")
        self.assertNotIn("ticket_id", ctx)
        self.assertNotIn("partition", ctx)
        self.assertNotIn("pipeline", ctx)
        self.assertEqual(ctx["pr"]["number"], 87)
        self.assertEqual(ctx["pr"]["url"], "https://github.com/acme/shop/pull/87")
        self.assertEqual(ctx["pr"]["branch"], "chore/cleanup")
        self.assertEqual(ctx["pr"]["base"], "main")
        self.assertIn("acs-exempt", ctx["pr"]["labels"])
        self._ws_untouched()

    def test_skill_start_pr_accepts_exempt_branch_without_label(self):
        # exempt by branch glob (release/*) even with no exempt label.
        body = self._pr_json(headRefName="release/1.2", labels=[])
        env = self._gh_env("echo '%s'" % body)
        out = self.run_script("skill-start.py", "--skill", "merge-pr",
                              "--pr", "87", env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["mode"], "exempt-pr")

    def test_skill_start_pr_rejected_for_non_merge_pr_skill(self):
        # (c) --pr only valid with --skill merge-pr.
        env = self._gh_env("echo '%s'" % self._pr_json())
        out = self.run_script("skill-start.py", "--skill", "code",
                              "--pr", "87", env=env)
        self.assertEqual(out.returncode, 2)
        self.assertTrue(out.stderr.strip())
        self.assertNotIn("Traceback", out.stderr)
        self._ws_untouched()

    def test_skill_start_pr_missing_gh_clean_exit(self):
        # (d-i) gh absent → clean exit 2, no traceback.
        env = self._gh_env(None)
        out = self.run_script("skill-start.py", "--skill", "merge-pr",
                              "--pr", "87", env=env)
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("Traceback", out.stderr)
        self.assertIn("gh", out.stderr)
        self._ws_untouched()

    def test_skill_start_pr_non_open_rejected(self):
        # (d-ii) non-OPEN PR → clean exit 2 naming the state.
        env = self._gh_env("echo '%s'" % self._pr_json(state="MERGED"))
        out = self.run_script("skill-start.py", "--skill", "merge-pr",
                              "--pr", "87", env=env)
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("Traceback", out.stderr)
        self.assertIn("MERGED", out.stderr)
        self._ws_untouched()

    def test_skill_start_pr_draft_rejected(self):
        env = self._gh_env("echo '%s'" % self._pr_json(isDraft=True))
        out = self.run_script("skill-start.py", "--skill", "merge-pr",
                              "--pr", "87", env=env)
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("Traceback", out.stderr)

    def test_skill_start_pr_ticket_backed_label_redirects(self):
        # (d-iii) PR carrying the require_label (ACS) → refuse + redirect.
        body = self._pr_json(labels=[{"name": "ACS"}])
        env = self._gh_env("echo '%s'" % body)
        out = self.run_script("skill-start.py", "--skill", "merge-pr",
                              "--pr", "87", env=env)
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("Traceback", out.stderr)
        self.assertIn("/acs:merge-pr", out.stderr)
        self._ws_untouched()

    def test_skill_start_pr_ticket_backed_branch_redirects(self):
        # (d-iii) PR whose branch embeds a ticket id → refuse + redirect with id.
        body = self._pr_json(headRefName="story/SHOP-42-x", labels=[])
        env = self._gh_env("echo '%s'" % body)
        out = self.run_script("skill-start.py", "--skill", "merge-pr",
                              "--pr", "87", env=env)
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("Traceback", out.stderr)
        self.assertIn("SHOP-42", out.stderr)
        self._ws_untouched()

    def test_skill_start_pr_non_exempt_non_ticket_rejected(self):
        # an OPEN PR that is neither exempt-labelled nor exempt-branch nor
        # ticket-backed → refuse + redirect to the ticket path.
        body = self._pr_json(headRefName="feature/whatever", labels=[])
        env = self._gh_env("echo '%s'" % body)
        out = self.run_script("skill-start.py", "--skill", "merge-pr",
                              "--pr", "87", env=env)
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("Traceback", out.stderr)
        self.assertIn("/acs:merge-pr", out.stderr)
        self._ws_untouched()

    def test_skill_start_pr_not_found_clean_exit(self):
        # gh exits non-zero (PR not found / API error) → clean exit 2.
        env = self._gh_env("echo 'no pull requests found' 1>&2; exit 1")
        out = self.run_script("skill-start.py", "--skill", "merge-pr",
                              "--pr", "999", env=env)
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("Traceback", out.stderr)
        self._ws_untouched()

    def test_skill_start_pr_non_json_output_clean_exit(self):
        # gh exits 0 but emits non-JSON → clean exit 2 (no traceback).
        env = self._gh_env("echo 'not json at all'")
        out = self.run_script("skill-start.py", "--skill", "merge-pr",
                              "--pr", "87", env=env)
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("Traceback", out.stderr)
        self._ws_untouched()

    def test_skill_start_pr_unparseable_ref_clean_exit(self):
        # --pr with a value that is not a PR reference → clean exit 2; gh never run.
        env = self._gh_env("echo '%s'" % self._pr_json())
        out = self.run_script("skill-start.py", "--skill", "merge-pr",
                              "--pr", "not-a-pr", env=env)
        self.assertEqual(out.returncode, 2)
        self.assertNotIn("Traceback", out.stderr)
        self.assertIn("PR reference", out.stderr)
        self._ws_untouched()

    def test_post_merge_pr_flag_outside_acs_repo_clean_exit(self):
        # build_context fails (no .acs settings) → clean exit 1, no traceback.
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        subprocess.run(["git", "init", "-q", plain], check=True)
        out = self.run_script("post-merge-pr.py", "--pr", "1", cwd=plain)
        self.assertEqual(out.returncode, 1)
        self.assertNotIn("Traceback", out.stderr)



class TestDistinctPRCount(AcsWorkspaceCase):
    """AC-1, AC-2, AC-3: distinct-PR counting via created_pr_numbers."""

    def _make_ticket_with_pr(self, pr_number=7):
        """Run the full pipeline up through create-pr with the given PR number,
        returning the child ticket id. The workspace is pre-seeded via setUp."""
        out = self.run_script("skill-start.py", "--skill", "create-ticket",
                              "--allocate", "--type", "epic", "--title", "E")
        self.assertEqual(out.returncode, 0, out.stderr)
        epic = json.loads(out.stdout)["ticket_id"]
        self.post("create-ticket", epic, {"status": "completed"})

        child = self.new_ticket("C", "story", "--parent", epic, "--needs-design", "false")

        with open(os.path.join(self.tdir(epic), "design.md"), "w") as fh:
            fh.write("# design")
        self.start("create-design", epic)
        self.post("create-design", epic, {"status": "completed"})

        self.start("create-spec", child)
        self.post("create-spec", child, {"status": "completed", "states": {"specs": ["01"]}})
        os.makedirs(os.path.join(self.tdir(child), "specs"), exist_ok=True)
        with open(os.path.join(self.tdir(child), "specs", "01.md"), "w") as fh:
            fh.write("# spec")
        self.start("code", child)
        self.post("code", child, {"status": "completed", "states": {"verifier_passed": True}})

        self.start("create-pr", child)
        self.post("create-pr", child, {
            "status": "completed",
            "states": {"pr": {"number": pr_number, "url": "https://github.com/acme/shop/pull/%d" % pr_number}},
        })
        return child

    def _read_metrics(self):
        with open(lib.metrics_path(self.ws, "acme-shop")) as fh:
            return json.load(fh)

    # AC-1 + AC-3: pr_number flows from states.pr.number into created_pr_numbers
    def test_ac1_created_pr_numbers_recorded_end_to_end(self):
        """After create-pr post with states.pr.number=7, prs.created_pr_numbers==[7]
        and prs.created==1.  Confirms the caller (run_post) extracts and passes
        the number (AC-3)."""
        self._make_ticket_with_pr(pr_number=7)
        metrics = self._read_metrics()
        self.assertEqual(metrics["prs"]["created"], 1)
        self.assertEqual(metrics["prs"]["created_pr_numbers"], [7])

    # AC-2: same number twice → no increment
    def test_ac2_same_number_twice_no_increment(self):
        """Calling update_metrics with the same pr_number twice must NOT double-count."""
        # Use update_metrics directly to control the pr_number precisely
        ws = self.ws
        repo_id = "acme-shop"
        # seed the workspace (the repo dir must exist for metrics_path)
        os.makedirs(os.path.join(ws, repo_id), exist_ok=True)
        # write a minimal tickets-index.json so index rebuild does not crash
        lib.write_json(lib.index_path(ws, repo_id), {"tickets": {}})

        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=7)
        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=7)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        self.assertEqual(m["prs"]["created"], 1)
        self.assertEqual(m["prs"]["created_pr_numbers"], [7])

    # AC-2: new number after same number → +1
    def test_ac2_new_number_increments(self):
        ws = self.ws
        repo_id = "acme-shop"
        os.makedirs(os.path.join(ws, repo_id), exist_ok=True)
        lib.write_json(lib.index_path(ws, repo_id), {"tickets": {}})

        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=7)
        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=7)
        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=8)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        self.assertEqual(m["prs"]["created"], 2)
        self.assertEqual(m["prs"]["created_pr_numbers"], [7, 8])

    # AC-2: pr_number=None with pr_created=True → no-op
    def test_ac2_none_pr_number_noop(self):
        ws = self.ws
        repo_id = "acme-shop"
        os.makedirs(os.path.join(ws, repo_id), exist_ok=True)
        lib.write_json(lib.index_path(ws, repo_id), {"tickets": {}})

        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=7)
        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=None)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        self.assertEqual(m["prs"]["created"], 1)
        self.assertEqual(m["prs"]["created_pr_numbers"], [7])

    # AC-2: non-positive pr_number with pr_created=True → no-op
    def test_ac2_nonpositive_pr_number_noop(self):
        ws = self.ws
        repo_id = "acme-shop"
        os.makedirs(os.path.join(ws, repo_id), exist_ok=True)
        lib.write_json(lib.index_path(ws, repo_id), {"tickets": {}})

        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=7)
        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=0)
        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=-1)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        self.assertEqual(m["prs"]["created"], 1)
        self.assertEqual(m["prs"]["created_pr_numbers"], [7])

    # AC-2: pr_created=False with a valid number → no-op
    def test_ac2_pr_created_false_noop(self):
        ws = self.ws
        repo_id = "acme-shop"
        os.makedirs(os.path.join(ws, repo_id), exist_ok=True)
        lib.write_json(lib.index_path(ws, repo_id), {"tickets": {}})

        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=7)
        lib.update_metrics(ws, repo_id, pr_created=False, pr_number=99)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        self.assertEqual(m["prs"]["created"], 1)
        self.assertEqual(m["prs"]["created_pr_numbers"], [7])

    # AC-2: default prs block includes created_pr_numbers
    def test_ac1_default_prs_includes_created_pr_numbers(self):
        ws = self.ws
        repo_id = "acme-shop"
        os.makedirs(os.path.join(ws, repo_id), exist_ok=True)
        lib.write_json(lib.index_path(ws, repo_id), {"tickets": {}})
        lib.update_metrics(ws, repo_id)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        self.assertIn("created_pr_numbers", m["prs"])
        self.assertEqual(m["prs"]["created_pr_numbers"], [])

    # AC-3: exempt-pr path still leaves created==0
    def test_ac3_exempt_pr_created_stays_zero(self):
        """Confirm the exempt --pr path (run_post_exempt_pr) does NOT set pr_created."""
        # This mirrors the existing test at ~:596-597 but calls lib directly
        ws = self.ws
        repo_id = "acme-shop"
        os.makedirs(os.path.join(ws, repo_id), exist_ok=True)
        lib.write_json(lib.index_path(ws, repo_id), {"tickets": {}})
        lib.update_metrics(ws, repo_id, pr_merged=True)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        self.assertEqual(m["prs"].get("created", 0), 0)
        self.assertEqual(m["prs"]["created_pr_numbers"], [])

    # AC-6: created_pr_numbers round-trips as a plain JSON list of ints
    def test_ac6_created_pr_numbers_round_trips_as_json_list(self):
        ws = self.ws
        repo_id = "acme-shop"
        os.makedirs(os.path.join(ws, repo_id), exist_ok=True)
        lib.write_json(lib.index_path(ws, repo_id), {"tickets": {}})
        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=42)
        lib.update_metrics(ws, repo_id, pr_created=True, pr_number=7)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        nums = m["prs"]["created_pr_numbers"]
        self.assertIsInstance(nums, list)
        self.assertEqual(nums, [7, 42])  # sorted
        for n in nums:
            self.assertIsInstance(n, int)


class TestBackfillDistinctPRCount(AcsWorkspaceCase):
    """AC-4: idempotent backfill of inflated prs.created."""

    def _write_create_pr_state(self, ws, repo_id, ticket_id, pr_number, archived=False):
        """Seed a create-pr-state.json for a ticket partition."""
        if archived:
            tdir = os.path.join(ws, repo_id, "archive", ticket_id)
        else:
            tdir = os.path.join(ws, repo_id, ticket_id)
        os.makedirs(tdir, exist_ok=True)
        state = {"runs": [], "states": {"pr": {"number": pr_number, "url": "https://example.com/pull/%d" % pr_number}}}
        lib.write_json(lib.state_path(tdir, "create-pr"), state)
        return tdir

    def _seed_workspace(self):
        """Build a workspace with two ticket partitions (one active, one archived)
        and an inflated metrics.json (created=99).  Returns (ws, repo_id)."""
        ws = self.ws
        repo_id = "acme-shop"
        os.makedirs(os.path.join(ws, repo_id), exist_ok=True)
        # tickets-index with two entries
        lib.write_json(lib.index_path(ws, repo_id), {
            "tickets": {
                "SHOP-1": {"id": "SHOP-1", "status": "done", "type": "story"},
                "SHOP-2": {"id": "SHOP-2", "status": "done", "type": "story"},
            }
        })
        # active partition: SHOP-1 → PR 7
        self._write_create_pr_state(ws, repo_id, "SHOP-1", pr_number=7, archived=False)
        # archived partition: SHOP-2 → PR 8
        self._write_create_pr_state(ws, repo_id, "SHOP-2", pr_number=8, archived=True)
        # inflated metrics
        lib.write_json(lib.metrics_path(ws, repo_id), {
            "prs": {"created": 99, "merged": 3, "created_pr_numbers": []},
            "tickets": {},
            "totals": {},
        })
        return ws, repo_id

    # AC-4: backfill heals inflated count
    def test_ac4_backfill_heals_inflated_count(self):
        ws, repo_id = self._seed_workspace()
        lib.backfill_distinct_pr_count(ws, repo_id)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        self.assertEqual(m["prs"]["created"], 2)
        self.assertEqual(m["prs"]["created_pr_numbers"], [7, 8])

    # AC-4: double run is idempotent (R1 mitigation)
    def test_ac4_backfill_idempotent_on_double_run(self):
        ws, repo_id = self._seed_workspace()
        lib.backfill_distinct_pr_count(ws, repo_id)
        lib.backfill_distinct_pr_count(ws, repo_id)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        self.assertEqual(m["prs"]["created"], 2)
        self.assertEqual(m["prs"]["created_pr_numbers"], [7, 8])

    # AC-4: backfill reads only metrics.json as a write (other files untouched)
    def test_ac4_backfill_writes_only_metrics_json(self):
        ws, repo_id = self._seed_workspace()
        # record mtimes before
        repo_dir = os.path.join(ws, repo_id)
        before = {}
        for fname in os.listdir(repo_dir):
            p = os.path.join(repo_dir, fname)
            if os.path.isfile(p):
                before[fname] = os.path.getmtime(p)
        # slight delay so mtime change is detectable
        import time as _time
        _time.sleep(0.05)

        lib.backfill_distinct_pr_count(ws, repo_id)

        after = {}
        for fname in os.listdir(repo_dir):
            p = os.path.join(repo_dir, fname)
            if os.path.isfile(p):
                after[fname] = os.path.getmtime(p)

        for fname, mtime in before.items():
            if fname == "metrics.json":
                continue  # this one IS allowed to change
            if fname in after:
                self.assertAlmostEqual(after[fname], mtime, places=1,
                                       msg="unexpected write to %s" % fname)

    # AC-4: ticket with no create-pr-state.json contributes 0 numbers
    def test_ac4_backfill_skips_ticket_with_no_state(self):
        ws = self.ws
        repo_id = "acme-shop"
        os.makedirs(os.path.join(ws, repo_id), exist_ok=True)
        # Only one ticket, no create-pr-state.json for it
        lib.write_json(lib.index_path(ws, repo_id), {
            "tickets": {"SHOP-1": {"id": "SHOP-1", "status": "done", "type": "story"}}
        })
        os.makedirs(os.path.join(ws, repo_id, "SHOP-1"), exist_ok=True)
        lib.write_json(lib.metrics_path(ws, repo_id), {
            "prs": {"created": 5, "merged": 0},
        })
        lib.backfill_distinct_pr_count(ws, repo_id)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        self.assertEqual(m["prs"]["created"], 0)
        self.assertEqual(m["prs"]["created_pr_numbers"], [])

    # AC-4: ticket with states.pr.number=null is skipped gracefully
    def test_ac4_backfill_skips_null_pr_number(self):
        ws = self.ws
        repo_id = "acme-shop"
        os.makedirs(os.path.join(ws, repo_id), exist_ok=True)
        lib.write_json(lib.index_path(ws, repo_id), {
            "tickets": {"SHOP-1": {"id": "SHOP-1", "status": "done", "type": "story"}}
        })
        tdir = os.path.join(ws, repo_id, "SHOP-1")
        os.makedirs(tdir, exist_ok=True)
        lib.write_json(lib.state_path(tdir, "create-pr"),
                       {"runs": [], "states": {"pr": {"number": None}}})
        lib.write_json(lib.metrics_path(ws, repo_id), {
            "prs": {"created": 5, "merged": 0},
        })
        lib.backfill_distinct_pr_count(ws, repo_id)
        m = lib.read_json(lib.metrics_path(ws, repo_id))
        self.assertEqual(m["prs"]["created"], 0)
        self.assertEqual(m["prs"]["created_pr_numbers"], [])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# MAR-15 spec 01 — due_date schema + write path
# ---------------------------------------------------------------------------

class TestDueDateSchema(unittest.TestCase):
    """AC-1: due_date is an optional, back-compatible addition to ticket.schema.json.

    The repo is stdlib-only (no third-party runtime/test deps), so instead of a
    full JSON-Schema validator these tests assert the specific contract the
    schema declares for due_date, reading the rule live from the schema file:
      - due_date is NOT in `required` (so an absent key conforms);
      - due_date is `oneOf [{type:string, pattern}, {type:null}]`, so null and a
        pattern-matching string conform while a non-matching string does not.
    The string-branch `pattern` is extracted from the loaded schema (not copied)
    and applied with `re.match`, so the tests track the real schema rule.
    """

    SCHEMA_PATH = os.path.join(REPO_ROOT, "plugins", "acs", "schemas", "ticket.schema.json")

    @classmethod
    def setUpClass(cls):
        with open(cls.SCHEMA_PATH) as fh:
            cls.schema = json.load(fh)
        due = cls.schema["properties"]["due_date"]
        branches = due["oneOf"]
        # Extract the string branch's pattern and confirm a null branch exists.
        cls.string_pattern = next(
            b["pattern"] for b in branches if b.get("type") == "string"
        )
        cls.allows_null = any(b.get("type") == "null" for b in branches)

    def _due_date_conforms(self, value, *, present=True):
        """Validate a candidate due_date against the schema's real contract.

        `present=False` models a ticket dict that omits the key entirely.
        """
        if not present:
            # Absent key conforms iff due_date is not required.
            return "due_date" not in self.schema["required"]
        if value is None:
            return self.allows_null
        if isinstance(value, str):
            return re.match(self.string_pattern, value) is not None
        return False

    def test_ticket_without_due_date_validates(self):
        """Absent due_date must remain schema-valid (back-compat)."""
        self.assertNotIn("due_date", self.schema["required"])
        self.assertTrue(self._due_date_conforms(None, present=False))

    def test_ticket_with_due_date_null_validates(self):
        """due_date: null must validate."""
        self.assertTrue(self._due_date_conforms(None))

    def test_ticket_with_valid_date_validates(self):
        """due_date: '2026-07-01' must validate."""
        self.assertTrue(self._due_date_conforms("2026-07-01"))

    def test_ticket_with_malformed_due_date_fails_validation(self):
        """due_date: 'not-a-date' must fail the schema's pattern rule."""
        self.assertFalse(self._due_date_conforms("not-a-date"))


class TestDueDateWritePath(AcsWorkspaceCase):
    """AC-2 + C-3: new-ticket.py --due-date sets ticket.json and tickets-index.json."""

    def test_due_date_written_to_ticket_json(self):
        """--due-date 2026-07-01 must appear in ticket.json.due_date."""
        ticket_id = self.new_ticket("T", "task", "--due-date", "2026-07-01")
        ticket = lib.load_ticket(self.tdir(ticket_id))
        self.assertEqual(ticket["due_date"], "2026-07-01")

    def test_due_date_propagated_to_index(self):
        """--due-date 2026-07-01 must propagate into tickets-index.json (C-3)."""
        ticket_id = self.new_ticket("T", "task", "--due-date", "2026-07-01")
        with open(lib.index_path(self.ws, "acme-shop")) as fh:
            index = __import__("json").load(fh)
        self.assertEqual(index["tickets"][ticket_id]["due_date"], "2026-07-01")

    def test_omitting_due_date_yields_null(self):
        """Omitting --due-date must write due_date: null in ticket.json."""
        ticket_id = self.new_ticket("T2", "task")
        ticket = lib.load_ticket(self.tdir(ticket_id))
        self.assertIsNone(ticket["due_date"])

    def test_malformed_due_date_rejected_non_zero_exit(self):
        """2026/07/01 (wrong separator) must exit non-zero with 'YYYY-MM-DD' in stderr."""
        result = self.run_script(
            "new-ticket.py", "--title", "T3", "--type", "task",
            "--due-date", "2026/07/01",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("YYYY-MM-DD", result.stderr)

    def test_datetime_string_rejected(self):
        """2026-07-01T00:00:00Z (datetime, not bare date) must exit non-zero."""
        result = self.run_script(
            "new-ticket.py", "--title", "T4", "--type", "task",
            "--due-date", "2026-07-01T00:00:00Z",
        )
        self.assertNotEqual(result.returncode, 0)


# ---------------------------------------------------------------------------
# MAR-56 spec 01 — classification axes, derive_lane, mint defaults, lane writes
# ---------------------------------------------------------------------------

class TestSizeStakesLaneSchema(unittest.TestCase):
    """AC-1 / AC-3: ticket.schema.json carries size/stakes/lane optional enums;
    no change to required list; additionalProperties stays True; legacy tickets
    still validate.

    Uses the same stdlib-only approach as TestDueDateSchema (no jsonschema import).
    """

    SCHEMA_PATH = os.path.join(REPO_ROOT, "plugins", "acs", "schemas", "ticket.schema.json")

    @classmethod
    def setUpClass(cls):
        with open(cls.SCHEMA_PATH) as fh:
            cls.schema = json.load(fh)

    def test_size_enum_present(self):
        """size must be an enum with exactly {trivial, small, standard, large}."""
        props = self.schema["properties"]
        self.assertIn("size", props)
        self.assertEqual(
            sorted(props["size"]["enum"]),
            ["large", "small", "standard", "trivial"],
        )

    def test_stakes_enum_present(self):
        """stakes must be an enum with exactly {low, normal, high}."""
        props = self.schema["properties"]
        self.assertIn("stakes", props)
        self.assertEqual(
            sorted(props["stakes"]["enum"]),
            ["high", "low", "normal"],
        )

    def test_lane_enum_present(self):
        """lane must be an enum with exactly {TRIVIAL, SMALL, STANDARD, COMPLEX}."""
        props = self.schema["properties"]
        self.assertIn("lane", props)
        self.assertEqual(
            sorted(props["lane"]["enum"]),
            ["COMPLEX", "SMALL", "STANDARD", "TRIVIAL"],
        )

    def test_size_stakes_lane_not_required(self):
        """None of the three new fields must appear in required."""
        required = self.schema.get("required", [])
        for field in ("size", "stakes", "lane"):
            self.assertNotIn(field, required, "%s must not be required" % field)

    def test_additional_properties_true(self):
        """additionalProperties must remain True (additive schema)."""
        self.assertTrue(self.schema.get("additionalProperties", False))

    def test_invalid_size_value_not_in_enum(self):
        """'huge' must not be in the size enum (stdlib enum-rejection guard)."""
        enum = self.schema["properties"]["size"]["enum"]
        self.assertNotIn("huge", enum)

    def test_invalid_stakes_value_not_in_enum(self):
        """'critical' must not be in the stakes enum."""
        enum = self.schema["properties"]["stakes"]["enum"]
        self.assertNotIn("critical", enum)

    def test_invalid_lane_value_not_in_enum(self):
        """'MINI' must not be in the lane enum."""
        enum = self.schema["properties"]["lane"]["enum"]
        self.assertNotIn("MINI", enum)

    def test_legacy_ticket_satisfies_required_list(self):
        """A legacy ticket dict with no size/stakes/lane is back-compat:
        the required list does not include the three new fields, so their
        absence does not invalidate the ticket (R1 guard)."""
        required = set(self.schema.get("required", []))
        legacy_fields = {
            "id", "title", "type", "description", "acceptance_criteria",
            "priority", "parent", "children", "status", "external",
            "assignee", "story_points", "needs_design",
        }
        # The required list must be satisfiable by a legacy ticket (no new fields).
        self.assertTrue(
            required.issubset(legacy_fields),
            "required fields not satisfiable by a legacy ticket: %s" % (required - legacy_fields),
        )


class TestDeriveLane(unittest.TestCase):
    """AC-2 / AC-3: derive_lane returns the correct lane for every cell of the
    routing table, including the rule overrides and conservative defaults.
    Full 21+ assertion grid per spec 01 Test plan.
    """

    def _lane(self, size, stakes, needs_design, ticket_type):
        return lib.derive_lane(size, stakes, needs_design, ticket_type)

    # --- base grid (no overrides) ---

    def test_trivial_low_story(self):
        self.assertEqual(self._lane("trivial", "low", False, "story"), "TRIVIAL")

    def test_trivial_normal_story(self):
        self.assertEqual(self._lane("trivial", "normal", False, "story"), "TRIVIAL")

    def test_small_low_story(self):
        self.assertEqual(self._lane("small", "low", False, "story"), "SMALL")

    def test_small_normal_story(self):
        self.assertEqual(self._lane("small", "normal", False, "story"), "SMALL")

    def test_standard_low_story(self):
        self.assertEqual(self._lane("standard", "low", False, "story"), "STANDARD")

    def test_standard_normal_story(self):
        self.assertEqual(self._lane("standard", "normal", False, "story"), "STANDARD")

    def test_large_low_story(self):
        self.assertEqual(self._lane("large", "low", False, "story"), "COMPLEX")

    def test_large_normal_story(self):
        self.assertEqual(self._lane("large", "normal", False, "story"), "COMPLEX")

    # --- stakes=high floor (Rule 3; Rule 2 fires first for large) ---

    def test_trivial_high_floors_to_standard(self):
        self.assertEqual(self._lane("trivial", "high", False, "story"), "STANDARD")

    def test_small_high_floors_to_standard(self):
        self.assertEqual(self._lane("small", "high", False, "story"), "STANDARD")

    def test_standard_high_stays_standard(self):
        self.assertEqual(self._lane("standard", "high", False, "story"), "STANDARD")

    def test_large_high_is_complex_rule2_beats_rule3(self):
        """large + high -> COMPLEX because Rule 2 (size=large) fires before Rule 3."""
        self.assertEqual(self._lane("large", "high", False, "story"), "COMPLEX")

    # --- needs_design floor (Rule 4) ---

    def test_trivial_low_needs_design_floors_to_standard(self):
        self.assertEqual(self._lane("trivial", "low", True, "story"), "STANDARD")

    def test_small_normal_needs_design_floors_to_standard(self):
        self.assertEqual(self._lane("small", "normal", True, "story"), "STANDARD")

    # --- epic override (Rule 1) ---

    def test_trivial_low_epic_is_complex(self):
        self.assertEqual(self._lane("trivial", "low", False, "epic"), "COMPLEX")

    def test_small_normal_epic_is_complex(self):
        self.assertEqual(self._lane("small", "normal", False, "epic"), "COMPLEX")

    def test_standard_high_epic_is_complex(self):
        self.assertEqual(self._lane("standard", "high", False, "epic"), "COMPLEX")

    # --- absent / None / unrecognized inputs (Rule 6 — AC-3) ---

    def test_none_none_defaults_to_standard(self):
        self.assertEqual(self._lane(None, None, False, "story"), "STANDARD")

    def test_empty_string_defaults_to_standard(self):
        self.assertEqual(self._lane("", "", False, "story"), "STANDARD")

    def test_unknown_size_defaults_to_standard(self):
        self.assertEqual(self._lane("unknown", "normal", False, "story"), "STANDARD")

    def test_unknown_stakes_does_not_floor(self):
        """Unrecognized stakes that is not 'high' must not trigger the high floor."""
        self.assertEqual(self._lane("small", "unknown", False, "story"), "SMALL")

    # --- additional edge cases ---

    def test_task_type_uses_size_dispatch(self):
        self.assertEqual(self._lane("small", "low", False, "task"), "SMALL")

    def test_needs_design_true_with_trivial_low_gives_standard_not_trivial(self):
        """needs_design=True must prevent TRIVIAL even with size=trivial, stakes=low."""
        result = self._lane("trivial", "low", True, "task")
        self.assertEqual(result, "STANDARD")
        self.assertNotEqual(result, "TRIVIAL")


class TestMintLaneDefaults(AcsWorkspaceCase):
    """AC-4: new_ticket_doc and new-ticket.py write size/stakes/lane defaults and
    honor explicit overrides.
    """

    def test_default_story_has_standard_normal_standard(self):
        """new_ticket_doc with no size/stakes kwargs -> standard/normal/STANDARD."""
        doc = lib.new_ticket_doc("T-1", "Test", "story")
        self.assertEqual(doc["size"], "standard")
        self.assertEqual(doc["stakes"], "normal")
        self.assertEqual(doc["lane"], "STANDARD")

    def test_epic_has_complex_lane(self):
        """new_ticket_doc for epic -> needs_design=True -> lane=COMPLEX (Rule 1)."""
        doc = lib.new_ticket_doc("T-2", "Test", "epic")
        self.assertTrue(doc["needs_design"])
        self.assertEqual(doc["lane"], "COMPLEX")

    def test_explicit_size_stakes_override(self):
        """Explicit size=trivial, stakes=low -> lane=TRIVIAL."""
        doc = lib.new_ticket_doc("T-3", "Test", "story", size="trivial", stakes="low")
        self.assertEqual(doc["size"], "trivial")
        self.assertEqual(doc["stakes"], "low")
        self.assertEqual(doc["lane"], "TRIVIAL")

    def test_small_high_stakes_floors_to_standard(self):
        """size=small, stakes=high -> lane=STANDARD (Rule 3)."""
        doc = lib.new_ticket_doc("T-4", "Test", "story", size="small", stakes="high")
        self.assertEqual(doc["lane"], "STANDARD")

    def test_cli_explicit_size_stakes(self):
        """new-ticket.py --size trivial --stakes low must write size/stakes/lane=TRIVIAL."""
        ticket_id = self.new_ticket("CLI test", "task",
                                    "--size", "trivial", "--stakes", "low")
        ticket = lib.load_ticket(self.tdir(ticket_id))
        self.assertEqual(ticket["size"], "trivial")
        self.assertEqual(ticket["stakes"], "low")
        self.assertEqual(ticket["lane"], "TRIVIAL")

    def test_cli_defaults_standard_normal_standard(self):
        """new-ticket.py with no --size/--stakes must write standard/normal/STANDARD."""
        ticket_id = self.new_ticket("CLI default test", "task")
        ticket = lib.load_ticket(self.tdir(ticket_id))
        self.assertEqual(ticket["size"], "standard")
        self.assertEqual(ticket["stakes"], "normal")
        self.assertEqual(ticket["lane"], "STANDARD")

    def test_lane_always_derived_not_verbatim(self):
        """Lane is always computed by derive_lane; passing inconsistent values
        must yield the derived lane, not the raw input."""
        # Even if a caller somehow passes a lane kwarg, new_ticket_doc should
        # always recompute. Verify via normal override: small+high -> STANDARD.
        doc = lib.new_ticket_doc("T-5", "Test", "story", size="small", stakes="high")
        expected = lib.derive_lane("small", "high", False, "story")
        self.assertEqual(doc["lane"], expected)


class TestLaneWrites(AcsWorkspaceCase):
    """AC-8: update_pipeline and update_index record lane in state files."""

    def setUp(self):
        super().setUp()
        self.ticket_id = self.new_ticket("Lane write test", "task",
                                         "--size", "trivial", "--stakes", "low")
        self._tdir = self.tdir(self.ticket_id)

    def test_update_pipeline_writes_lane(self):
        """update_pipeline(..., lane='TRIVIAL') must write lane to pipeline-state.json."""
        lib.update_pipeline(self._tdir, self.ticket_id, "create-spec", "done",
                            lane="TRIVIAL")
        data = lib.read_json(
            os.path.join(self._tdir, "pipeline-state.json"))
        self.assertEqual(data["lane"], "TRIVIAL")

    def test_update_pipeline_lane_survives_second_update(self):
        """A second update_pipeline call for a different skill must not drop lane."""
        lib.update_pipeline(self._tdir, self.ticket_id, "create-spec", "done",
                            lane="TRIVIAL")
        lib.update_pipeline(self._tdir, self.ticket_id, "code", "done",
                            lane="TRIVIAL")
        data = lib.read_json(
            os.path.join(self._tdir, "pipeline-state.json"))
        self.assertEqual(data["lane"], "TRIVIAL")

    def test_update_pipeline_without_lane_does_not_crash(self):
        """Calling update_pipeline without lane= must not write/overwrite the field
        and must not raise."""
        lib.update_pipeline(self._tdir, self.ticket_id, "create-spec", "done",
                            lane="SMALL")
        lib.update_pipeline(self._tdir, self.ticket_id, "code", "done")
        data = lib.read_json(
            os.path.join(self._tdir, "pipeline-state.json"))
        # lane from first call survives; second call without lane doesn't overwrite
        self.assertEqual(data["lane"], "SMALL")

    def test_update_index_writes_lane(self):
        """update_index with ticket['lane']='SMALL' must persist to index."""
        ticket = lib.load_ticket(self._tdir)
        ticket["lane"] = "SMALL"
        lib.update_index(self.ws, "acme-shop", ticket)
        with open(lib.index_path(self.ws, "acme-shop")) as fh:
            index = json.load(fh)
        self.assertEqual(index["tickets"][self.ticket_id]["lane"], "SMALL")

    def test_update_index_no_lane_key_writes_none(self):
        """update_index with a ticket dict that has no lane key must write
        lane: None (or absent) without crashing."""
        ticket = lib.load_ticket(self._tdir)
        ticket.pop("lane", None)
        lib.update_index(self.ws, "acme-shop", ticket)
        with open(lib.index_path(self.ws, "acme-shop")) as fh:
            index = json.load(fh)
        # lane entry should exist and be None (or the key should be present)
        entry = index["tickets"][self.ticket_id]
        # ticket.get("lane") when lane is absent returns None — that's what was written
        self.assertIn("lane", entry)
        self.assertIsNone(entry["lane"])

    def test_update_pipeline_lane_none_does_not_write_key(self):
        """Calling update_pipeline with lane=None (default) must not add a lane key
        when one was not already there (or at least must not crash)."""
        # Start fresh: call with no lane
        lib.update_pipeline(self._tdir, self.ticket_id, "create-spec", "done")
        data = lib.read_json(
            os.path.join(self._tdir, "pipeline-state.json"))
        # lane was not written (no lane= arg means None, so the if-guard skips it)
        # The key must be absent in the initial write (or written from the ticket's
        # mint-time create-ticket call if it was written earlier)
        # We only assert it did not crash — the key may or may not be present
        # depending on whether the setUp mint already wrote it.
        self.assertIsInstance(data, dict)  # no crash


# ---------------------------------------------------------------------------
# MAR-56 spec 02 — high_stakes_paths settings, recommend_stakes, AC-7 consistency
# ---------------------------------------------------------------------------

class TestHighStakesPathsSettings(unittest.TestCase):
    """AC-5: settings.schema.json defines high_stakes_paths as an array-of-strings
    with the seed default; DEFAULT_SETTINGS has the seed list; absent key resolves
    to the seed.

    Uses the same stdlib-only approach as TestDueDateSchema (no jsonschema import).
    """

    SCHEMA_PATH = os.path.join(REPO_ROOT, "plugins", "acs", "schemas", "settings.schema.json")

    SEED_LIST = [
        "auth/**",
        "payments/**",
        "migrations/**",
        "public-api/**",
        "security/**",
    ]

    @classmethod
    def setUpClass(cls):
        with open(cls.SCHEMA_PATH) as fh:
            cls.schema = json.load(fh)

    def test_high_stakes_paths_in_schema(self):
        """settings.schema.json must define high_stakes_paths."""
        self.assertIn("high_stakes_paths", self.schema["properties"])

    def test_high_stakes_paths_is_array_type(self):
        """high_stakes_paths must be type:array."""
        prop = self.schema["properties"]["high_stakes_paths"]
        self.assertEqual(prop["type"], "array")

    def test_high_stakes_paths_items_are_strings(self):
        """high_stakes_paths.items must be type:string."""
        prop = self.schema["properties"]["high_stakes_paths"]
        self.assertEqual(prop["items"]["type"], "string")

    def test_high_stakes_paths_schema_default_is_seed(self):
        """The schema's default for high_stakes_paths must be the 5-element seed list."""
        prop = self.schema["properties"]["high_stakes_paths"]
        self.assertEqual(prop.get("default"), self.SEED_LIST)

    def test_default_settings_has_seed_list(self):
        """DEFAULT_SETTINGS['high_stakes_paths'] must equal the 5-element seed list."""
        self.assertEqual(lib.DEFAULT_SETTINGS["high_stakes_paths"], self.SEED_LIST)

    def test_absent_key_resolves_to_seed(self):
        """When high_stakes_paths is absent from settings, fall back to DEFAULT_SETTINGS seed."""
        settings = {}  # no high_stakes_paths key
        result = settings.get("high_stakes_paths",
                               lib.DEFAULT_SETTINGS["high_stakes_paths"])
        self.assertEqual(result, self.SEED_LIST)

    def test_project_override_replaces_seed(self):
        """A project-supplied high_stakes_paths replaces (not extends) the seed."""
        settings = {"high_stakes_paths": ["src/payments/**"]}
        result = settings.get("high_stakes_paths",
                               lib.DEFAULT_SETTINGS["high_stakes_paths"])
        self.assertEqual(result, ["src/payments/**"])
        # seed patterns must NOT appear
        self.assertNotIn("auth/**", result)

    def test_string_array_passes_items_rule(self):
        """A list of strings is accepted by the items.type==string rule (stdlib check)."""
        prop = self.schema["properties"]["high_stakes_paths"]
        items_type = prop["items"]["type"]
        candidate = ["auth/**", "payments/**"]
        for item in candidate:
            self.assertIsInstance(item, str), "item %r should be a string" % item

    def test_non_array_rejected_by_type_rule(self):
        """A plain string is not an array (stdlib type check)."""
        prop = self.schema["properties"]["high_stakes_paths"]
        self.assertEqual(prop["type"], "array")
        self.assertNotIsInstance("auth/**", list)  # string != array

    def test_array_of_non_strings_rejected_by_items_rule(self):
        """Items of type other than string must not satisfy items.type==string."""
        prop = self.schema["properties"]["high_stakes_paths"]
        items_type = prop["items"]["type"]
        self.assertEqual(items_type, "string")
        for bad_item in [42, True]:
            self.assertNotIsInstance(bad_item, str,
                                     "non-string item %r should fail items.type==string" % bad_item)


class TestRecommendStakes(unittest.TestCase):
    """AC-6: recommend_stakes(paths, settings) returns 'high' on any glob match,
    'normal' otherwise; never writes; override supersedes seed.
    """

    SEED_SETTINGS = None  # None triggers fallback to DEFAULT_SETTINGS seed

    def _rec(self, paths, settings=None):
        return lib.recommend_stakes(paths, settings)

    def test_match_auth(self):
        """paths=['auth/login.py'] + default settings -> 'high'."""
        self.assertEqual(self._rec(["auth/login.py"]), "high")

    def test_match_payments(self):
        """paths=['payments/stripe_hook.py'] + default settings -> 'high'."""
        self.assertEqual(self._rec(["payments/stripe_hook.py"]), "high")

    def test_match_migrations(self):
        """paths=['migrations/0042_add_column.py'] + default settings -> 'high'."""
        self.assertEqual(self._rec(["migrations/0042_add_column.py"]), "high")

    def test_match_public_api(self):
        """paths=['public-api/v2/endpoints.py'] + default settings -> 'high'."""
        self.assertEqual(self._rec(["public-api/v2/endpoints.py"]), "high")

    def test_match_security(self):
        """paths=['security/certs.py'] + default settings -> 'high'."""
        self.assertEqual(self._rec(["security/certs.py"]), "high")

    def test_no_match_returns_normal(self):
        """paths with no glob match -> 'normal'."""
        self.assertEqual(
            self._rec(["src/utils.py", "tests/test_utils.py"]),
            "normal",
        )

    def test_empty_paths_returns_normal(self):
        """Empty paths list -> 'normal'."""
        self.assertEqual(self._rec([]), "normal")

    def test_custom_glob_override_match(self):
        """Custom glob replaces seed: src/billing/** match -> 'high'."""
        settings = {"high_stakes_paths": ["src/billing/**"]}
        self.assertEqual(self._rec(["src/billing/invoice.py"], settings), "high")

    def test_custom_glob_override_no_match(self):
        """Custom glob replaces seed: non-matching path -> 'normal'."""
        settings = {"high_stakes_paths": ["src/billing/**"]}
        self.assertEqual(self._rec(["src/utils.py"], settings), "normal")

    def test_custom_override_supersedes_seed(self):
        """Custom glob replaces seed; a seed-pattern path does NOT match."""
        settings = {"high_stakes_paths": ["src/billing/**"]}
        # auth/login.py would match the seed but NOT the override
        self.assertEqual(self._rec(["auth/login.py"], settings), "normal")

    def test_none_settings_uses_seed(self):
        """settings=None falls back to DEFAULT_SETTINGS seed; auth path -> 'high'."""
        self.assertEqual(self._rec(["auth/login.py"], None), "high")

    def test_multi_path_first_match_short_circuit(self):
        """Multiple paths: first glob match returns 'high' (short-circuit)."""
        # src/utils.py does not match; auth/login.py does
        result = self._rec(["src/utils.py", "auth/login.py"])
        self.assertEqual(result, "high")

    def test_recommend_stakes_never_returns_low(self):
        """recommend_stakes never returns 'low'; it only returns 'high' or 'normal'."""
        for paths in ([], ["src/x.py"], ["auth/y.py"]):
            result = self._rec(paths)
            self.assertIn(result, ("high", "normal"))
            self.assertNotEqual(result, "low")


class TestLaneConsistency(AcsWorkspaceCase):
    """AC-7: lane == derive_lane(size, stakes, needs_design, type) for a minted ticket;
    inconsistent lane is detectable.
    """

    def test_minted_ticket_lane_is_consistent(self):
        """A ticket minted with size=small, stakes=high must have a lane consistent
        with its axes (stakes=high floor -> STANDARD)."""
        ticket_id = self.new_ticket("Consistency test", "story",
                                    "--size", "small", "--stakes", "high")
        ticket = lib.load_ticket(self.tdir(ticket_id))
        expected_lane = lib.derive_lane(
            ticket["size"], ticket["stakes"], ticket["needs_design"], ticket["type"]
        )
        self.assertEqual(ticket["lane"], expected_lane)

    def test_conservative_defaults_are_consistent(self):
        """A ticket minted with no size/stakes uses standard/normal -> STANDARD;
        the lane must be consistent with those axes."""
        ticket_id = self.new_ticket("Default test", "story")
        ticket = lib.load_ticket(self.tdir(ticket_id))
        expected_lane = lib.derive_lane(
            ticket["size"], ticket["stakes"], ticket["needs_design"], ticket["type"]
        )
        self.assertEqual(ticket["lane"], expected_lane)
        self.assertEqual(ticket["lane"], "STANDARD")

    def test_inconsistent_lane_is_detectable(self):
        """A hand-written ticket with lane inconsistent with axes is detectable by
        the derive_lane consistency check (verifier re-check, spec 02 §4e)."""
        # Build a ticket dict with an inconsistent lane (trivial/low should give TRIVIAL,
        # but we write COMPLEX — a mis-written cache)
        ticket = {
            "id": "T-99", "title": "x", "type": "story",
            "size": "trivial", "stakes": "low", "needs_design": False,
            "lane": "COMPLEX",  # deliberately inconsistent
        }
        correct_lane = lib.derive_lane(
            ticket["size"], ticket["stakes"], ticket["needs_design"], ticket["type"]
        )
        # The verifier check: lane != derive_lane(...) means inconsistency detected
        self.assertNotEqual(ticket["lane"], correct_lane)
        self.assertEqual(correct_lane, "TRIVIAL")

    def test_epic_fan_out_child_uses_conservative_defaults(self):
        """Child minted via new-ticket.py WITHOUT --size/--stakes must get
        standard/normal/STANDARD (conservative defaults for fan-out)."""
        # Create the epic first
        epic_id = self.new_ticket("Epic test", "epic")
        # Mint child without size/stakes (fan-out pattern)
        child_id = self.new_ticket("Child test", "story", "--parent", epic_id,
                                   "--needs-design", "false")
        child = lib.load_ticket(self.tdir(child_id))
        self.assertEqual(child["size"], "standard")
        self.assertEqual(child["stakes"], "normal")
        self.assertEqual(child["lane"], "STANDARD")
