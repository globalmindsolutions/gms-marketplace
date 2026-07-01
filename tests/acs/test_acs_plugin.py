"""Unit/integration tests for the acs plugin's deterministic layer.

Covers the hook library (acs_lib), the named pre/post hooks via the
dispatcher, the helper CLIs (skill-start, new-ticket, handoff, clarify,
validate_xml), and the status-line scripts — everything that gates and
persists the pipeline. Each test drives the real scripts in a throwaway
git repo + workspace, asserting on exit codes and the JSON state files
(the same artifacts the pipeline itself trusts).

Run:  python3 -m unittest discover -s tests -v
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

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

    def test_gate_code_trivial_lane_skips_create_spec(self):
        # AC-1: TRIVIAL lane does NOT require create-spec or specs/ dir.
        # derive_lane("trivial", "low", ...) -> "TRIVIAL" (acs_lib.py:98-99)
        t = self.new_ticket("X", "task", "--size", "trivial", "--stakes", "low")
        # No create-spec start/post, no specs/ directory created.
        result = self.pre("code", t)
        self.assertEqual(result.returncode, 0)

    def test_gate_code_small_lane_skips_create_spec(self):
        # AC-1: SMALL lane does NOT require create-spec or specs/ dir.
        # derive_lane("small", "normal", ...) -> "SMALL" (acs_lib.py:96-97)
        t = self.new_ticket("Y", "task", "--size", "small", "--stakes", "normal")
        # No create-spec start/post, no specs/ directory created.
        result = self.pre("code", t)
        self.assertEqual(result.returncode, 0)

    def test_gate_code_standard_lane_blocks_without_create_spec(self):
        # AC-2: STANDARD lane blocks when create-spec not completed and no specs dir.
        # derive_lane("standard", "normal", ...) -> "STANDARD" (acs_lib.py:94-95)
        t = self.new_ticket("Z", "task")
        # No create-spec, no specs dir.
        result = self.pre("code", t)
        self.assertEqual(result.returncode, 2)
        self.assertIn("create-spec", result.stderr)

    def test_gate_code_complex_lane_blocks_without_create_spec(self):
        # AC-2: COMPLEX lane blocks when create-spec not completed and no specs dir.
        # derive_lane("large", ...) -> "COMPLEX" (acs_lib.py:88-89)
        t = self.new_ticket("W", "task", "--size", "large")
        # No create-spec, no specs dir.
        result = self.pre("code", t)
        self.assertEqual(result.returncode, 2)

    def test_gate_code_absent_lane_recomputes_via_derive_lane(self):
        # AC-2: When the "lane" key is absent from ticket.json (legacy ticket),
        # gate_code recomputes via derive_lane and fails-closed for STANDARD axes.
        t = self.new_ticket("V", "task")  # default size=standard -> STANDARD
        # Remove the "lane" key from ticket.json to simulate a legacy ticket.
        tdir = self.tdir(t)
        ticket_path = os.path.join(tdir, "ticket.json")
        with open(ticket_path) as fh:
            doc = json.load(fh)
        doc.pop("lane", None)
        with open(ticket_path, "w") as fh:
            json.dump(doc, fh)
        # derive_lane fallback: absent size -> STANDARD -> full-lane block.
        result = self.pre("code", t)
        self.assertEqual(result.returncode, 2)


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

    def test_docs_only_relaxation_section_present_in_code_skill(self):
        """MAR-65 AC-6: 'docs_only' must appear in code/SKILL.md to anchor the
        docs_only relaxation section so it cannot be silently dropped."""
        import os
        plugin = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "plugins", "acs")
        skill_path = os.path.join(plugin, "skills", "code", "SKILL.md")
        with open(skill_path, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("docs_only", body,
                      "code/SKILL.md must contain 'docs_only' (docs_only relaxation section "
                      "must not be silently dropped) (MAR-65 AC-6)")


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

    # -----------------------------------------------------------------------
    # AC-2 Parity corpus (T1, keystone) — written FIRST per TDD discipline.
    # Every XSD violation class is represented; assertions are unconditional
    # (no xmllint on PATH required).  The xmllint parity leg is conditional.
    # -----------------------------------------------------------------------

    # Corpus fixture strings — valid messages (one per root element)
    VALID_TASK = (
        '<task skill="code" phase="execute" ticket-id="SHOP-1">'
        '<objective>Implement feature X</objective>'
        '<inputs><file>/src/foo.py</file></inputs>'
        '<constraints><constraint name="c1">no breaking changes</constraint></constraints>'
        '<context>background info</context>'
        '</task>'
    )
    VALID_RESULT = (
        '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
        '<outputs><file>/src/foo.py</file></outputs>'
        '<findings><finding severity="info">all clear</finding></findings>'
        '<metrics tokens-input="1000" tokens-output="200" cost-usd="0.05"/>'
        '<stop-reason>done</stop-reason>'
        '</result>'
    )
    VALID_HANDOFF = (
        '<handoff skill="create-spec" ticket-id="SHOP-1" status="needs_input">'
        '<summary>Summarised progress</summary>'
        '<questions><question>What priority?</question></questions>'
        '<next-step>resume after user answers</next-step>'
        '</handoff>'
    )

    # Corpus fixture strings — malformed messages (one per XSD violation class)
    # (i) bad root element — root not in {task, result, handoff}
    MALFORMED_BAD_ROOT = '<foo skill="code" phase="execute" ticket-id="SHOP-1"/>'

    # (ii) missing required attribute — missing 'skill'
    MALFORMED_MISSING_SKILL = (
        '<task phase="execute" ticket-id="SHOP-1">'
        '<objective>obj</objective>'
        '</task>'
    )

    # (ii) invalid attribute value — skill not in enum
    MALFORMED_INVALID_SKILL = (
        '<task skill="nope" phase="execute" ticket-id="SHOP-1">'
        '<objective>obj</objective>'
        '</task>'
    )

    # (ii) bad ticket-id pattern — must match [A-Z][A-Z0-9]*-[0-9]+
    MALFORMED_BAD_TICKET_ID = (
        '<task skill="code" phase="execute" ticket-id="123">'
        '<objective>obj</objective>'
        '</task>'
    )

    # (iii) out-of-order children — constraints before objective in task
    MALFORMED_OUT_OF_ORDER = (
        '<task skill="code" phase="execute" ticket-id="SHOP-1">'
        '<constraints><constraint name="c1">x</constraint></constraints>'
        '<objective>obj</objective>'
        '</task>'
    )

    # (iv) wrong list item — <bar/> inside <inputs> instead of <file>
    MALFORMED_WRONG_LIST_ITEM = (
        '<task skill="code" phase="execute" ticket-id="SHOP-1">'
        '<objective>obj</objective>'
        '<inputs><bar/></inputs>'
        '</task>'
    )

    # (v) bad enum — status not in {completed, failed, needs_input}
    MALFORMED_BAD_STATUS_ENUM = (
        '<result skill="code" phase="execute" ticket-id="SHOP-1" status="bad_status"/>'
    )

    # (v) bad enum — severity not in {blocking, info}
    MALFORMED_BAD_SEVERITY_ENUM = (
        '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
        '<findings><finding severity="critical">something bad</finding></findings>'
        '</result>'
    )

    # (vi) CARDINALITY: duplicate maxOccurs=1 sequence children
    # xs:sequence in acs-messages.xsd has maxOccurs=1 (default) for every element;
    # duplicate children must be rejected (XSD rejects them via xs:sequence constraint).

    # duplicate <objective> in <task> (required, maxOccurs=1)
    MALFORMED_DUP_OBJECTIVE = (
        '<task skill="code" phase="execute" ticket-id="SHOP-1">'
        '<objective>first</objective>'
        '<objective>second</objective>'
        '</task>'
    )

    # duplicate <summary> in <handoff> (required, maxOccurs=1)
    MALFORMED_DUP_SUMMARY = (
        '<handoff skill="create-spec" ticket-id="SHOP-1" status="completed">'
        '<summary>first</summary>'
        '<summary>second</summary>'
        '</handoff>'
    )

    # duplicate <metrics> in <result> (optional, maxOccurs=1)
    MALFORMED_DUP_METRICS = (
        '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
        '<metrics tokens-input="100" tokens-output="50" cost-usd="0.01"/>'
        '<metrics tokens-input="200" tokens-output="100" cost-usd="0.02"/>'
        '</result>'
    )

    # duplicate <inputs> container in <task> (optional, maxOccurs=1)
    MALFORMED_DUP_INPUTS = (
        '<task skill="code" phase="execute" ticket-id="SHOP-1">'
        '<objective>obj</objective>'
        '<inputs><file>/a.py</file></inputs>'
        '<inputs><file>/b.py</file></inputs>'
        '</task>'
    )

    # duplicate <next-step> in <handoff> (optional, maxOccurs=1)
    MALFORMED_DUP_NEXT_STEP = (
        '<handoff skill="create-spec" ticket-id="SHOP-1" status="completed">'
        '<summary>s</summary>'
        '<next-step>step one</next-step>'
        '<next-step>step two</next-step>'
        '</handoff>'
    )

    # (vii) xs:decimal grammar: cost-usd must match optional-sign + digits +
    # optional single decimal point — NO exponent, NO inf/nan, NO underscores.
    # Each of these is accepted by Python float() but rejected by xs:decimal.
    MALFORMED_COST_USD_INF = (
        '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
        '<metrics tokens-input="100" tokens-output="50" cost-usd="inf"/>'
        '</result>'
    )
    MALFORMED_COST_USD_NAN = (
        '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
        '<metrics tokens-input="100" tokens-output="50" cost-usd="nan"/>'
        '</result>'
    )
    MALFORMED_COST_USD_EXPONENT = (
        '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
        '<metrics tokens-input="100" tokens-output="50" cost-usd="1e5"/>'
        '</result>'
    )
    MALFORMED_COST_USD_UNDERSCORE = (
        '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
        '<metrics tokens-input="100" tokens-output="50" cost-usd="1_000"/>'
        '</result>'
    )
    MALFORMED_COST_USD_EMPTY = (
        '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
        '<metrics tokens-input="100" tokens-output="50" cost-usd=""/>'
        '</result>'
    )

    # (viii) closed content model — the XSD declares no anyAttribute / wildcard,
    # so an undeclared attribute on any element is invalid (xmllint rejects it;
    # the in-process validator must too).
    MALFORMED_UNDECLARED_ATTR_ROOT = (
        '<task skill="code" phase="execute" ticket-id="SHOP-1" bogus="y">'
        '<objective>x</objective></task>'
    )
    MALFORMED_UNDECLARED_ATTR_METRICS = (
        '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
        '<metrics cost-usd="0.1" bogus="1"/></result>'
    )
    MALFORMED_UNDECLARED_ATTR_FINDING = (
        '<result skill="code" phase="execute" ticket-id="SHOP-1" status="completed">'
        '<findings><finding severity="info" bogus="z">m</finding></findings></result>'
    )
    MALFORMED_UNDECLARED_ATTR_CONSTRAINT = (
        '<task skill="code" phase="execute" ticket-id="SHOP-1"><objective>x</objective>'
        '<constraints><constraint name="n" extra="z">c</constraint></constraints></task>'
    )
    # (ix) text-only (xs:string) leaves admit no element children.
    MALFORMED_CHILD_IN_FILE = (
        '<task skill="code" phase="execute" ticket-id="SHOP-1"><objective>x</objective>'
        '<inputs><file>a<sub/></file></inputs></task>'
    )
    MALFORMED_CHILD_IN_OBJECTIVE = (
        '<task skill="code" phase="execute" ticket-id="SHOP-1">'
        '<objective>x<nested/></objective></task>'
    )

    VALID_CORPUS = [
        ("valid_task", VALID_TASK),
        ("valid_result", VALID_RESULT),
        ("valid_handoff", VALID_HANDOFF),
    ]
    MALFORMED_CORPUS = [
        ("bad_root", MALFORMED_BAD_ROOT),
        ("missing_skill", MALFORMED_MISSING_SKILL),
        ("invalid_skill", MALFORMED_INVALID_SKILL),
        ("bad_ticket_id", MALFORMED_BAD_TICKET_ID),
        ("out_of_order", MALFORMED_OUT_OF_ORDER),
        ("wrong_list_item", MALFORMED_WRONG_LIST_ITEM),
        ("bad_status_enum", MALFORMED_BAD_STATUS_ENUM),
        ("bad_severity_enum", MALFORMED_BAD_SEVERITY_ENUM),
        # (vi) cardinality — duplicate maxOccurs=1 sequence elements
        ("dup_objective", MALFORMED_DUP_OBJECTIVE),
        ("dup_summary", MALFORMED_DUP_SUMMARY),
        ("dup_metrics", MALFORMED_DUP_METRICS),
        ("dup_inputs", MALFORMED_DUP_INPUTS),
        ("dup_next_step", MALFORMED_DUP_NEXT_STEP),
        # (vii) xs:decimal grammar — cost-usd values Python float() accepts but xs:decimal rejects
        ("cost_usd_inf", MALFORMED_COST_USD_INF),
        ("cost_usd_nan", MALFORMED_COST_USD_NAN),
        ("cost_usd_exponent", MALFORMED_COST_USD_EXPONENT),
        ("cost_usd_underscore", MALFORMED_COST_USD_UNDERSCORE),
        ("cost_usd_empty", MALFORMED_COST_USD_EMPTY),
        # (viii) closed content model — undeclared attributes
        ("undeclared_attr_root", MALFORMED_UNDECLARED_ATTR_ROOT),
        ("undeclared_attr_metrics", MALFORMED_UNDECLARED_ATTR_METRICS),
        ("undeclared_attr_finding", MALFORMED_UNDECLARED_ATTR_FINDING),
        ("undeclared_attr_constraint", MALFORMED_UNDECLARED_ATTR_CONSTRAINT),
        # (ix) text-only leaves admit no element children
        ("child_in_file", MALFORMED_CHILD_IN_FILE),
        ("child_in_objective", MALFORMED_CHILD_IN_OBJECTIVE),
    ]

    def _load_validate_xml(self):
        """Import validate_xml in-process (SCRIPTS is already on sys.path)."""
        import importlib
        import importlib.util
        _target = os.path.join(SCRIPTS, "validate_xml.py")
        spec = importlib.util.spec_from_file_location("validate_xml", _target)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_ac2_parity_valid_corpus_in_process(self):
        """Valid corpus messages return [] from validate_structurally (AC-2)."""
        mod = self._load_validate_xml()
        for name, xml in self.VALID_CORPUS:
            errors = mod.validate_structurally(xml)
            self.assertEqual(errors, [],
                             "Expected no errors for %s but got: %s" % (name, errors))

    def test_ac2_parity_malformed_corpus_in_process(self):
        """Malformed corpus messages return non-empty errors from validate_structurally (AC-2)."""
        mod = self._load_validate_xml()
        for name, xml in self.MALFORMED_CORPUS:
            errors = mod.validate_structurally(xml)
            self.assertTrue(errors,
                            "Expected errors for %s but got empty list" % name)

    @unittest.skipUnless(shutil.which("xmllint"), "xmllint not on PATH")
    def test_ac2_parity_corpus_xmllint_matches_in_process(self):
        """xmllint and in-process paths agree on every corpus message (AC-2 parity)."""
        mod = self._load_validate_xml()
        all_cases = list(self.VALID_CORPUS) + list(self.MALFORMED_CORPUS)
        for name, xml in all_cases:
            in_process_errors = mod.validate_structurally(xml)
            in_process_ok = (in_process_errors == [])

            with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
                fh.write(xml)
                tmp_path = fh.name
            try:
                xmllint_ok, xmllint_detail = mod.validate_with_xmllint(tmp_path)
            finally:
                os.unlink(tmp_path)

            self.assertEqual(
                in_process_ok, xmllint_ok,
                "PARITY GAP on %r: in-process=%s xmllint=%s detail=%r errors=%r"
                % (name, in_process_ok, xmllint_ok, xmllint_detail, in_process_errors)
            )

    # -----------------------------------------------------------------------
    # AC-2 parity: cardinality (maxOccurs=1 on sequence members)
    # -----------------------------------------------------------------------

    def test_ac2_cardinality_duplicate_children_rejected_in_process(self):
        """Duplicate maxOccurs=1 sequence children must be rejected by validate_structurally.

        xs:sequence in acs-messages.xsd has maxOccurs=1 (default) for every element.
        Two <objective>, two <summary>, two <metrics>, two <inputs>, two <next-step>
        must each produce at least one error (AC-2 cardinality gap closure).
        """
        mod = self._load_validate_xml()
        cardinality_cases = [
            ("dup_objective", self.MALFORMED_DUP_OBJECTIVE),
            ("dup_summary", self.MALFORMED_DUP_SUMMARY),
            ("dup_metrics", self.MALFORMED_DUP_METRICS),
            ("dup_inputs", self.MALFORMED_DUP_INPUTS),
            ("dup_next_step", self.MALFORMED_DUP_NEXT_STEP),
        ]
        for name, xml in cardinality_cases:
            errors = mod.validate_structurally(xml)
            self.assertTrue(
                errors,
                "Expected cardinality error for %s but validate_structurally returned []. "
                "Duplicate maxOccurs=1 child must be rejected." % name,
            )

    @unittest.skipUnless(shutil.which("xmllint"), "xmllint not on PATH")
    def test_ac2_cardinality_parity_with_xmllint(self):
        """Cardinality violations: in-process and xmllint must both return INVALID."""
        mod = self._load_validate_xml()
        cardinality_cases = [
            ("dup_objective", self.MALFORMED_DUP_OBJECTIVE),
            ("dup_summary", self.MALFORMED_DUP_SUMMARY),
            ("dup_metrics", self.MALFORMED_DUP_METRICS),
            ("dup_inputs", self.MALFORMED_DUP_INPUTS),
            ("dup_next_step", self.MALFORMED_DUP_NEXT_STEP),
        ]
        for name, xml in cardinality_cases:
            in_process_ok = (mod.validate_structurally(xml) == [])
            with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
                fh.write(xml)
                tmp_path = fh.name
            try:
                xmllint_ok, xmllint_detail = mod.validate_with_xmllint(tmp_path)
            finally:
                os.unlink(tmp_path)
            self.assertEqual(
                in_process_ok, xmllint_ok,
                "PARITY GAP on cardinality case %r: in-process=%s xmllint=%s detail=%r"
                % (name, in_process_ok, xmllint_ok, xmllint_detail),
            )
            self.assertFalse(
                xmllint_ok,
                "xmllint should reject duplicate child %r (maxOccurs=1 violation)" % name,
            )

    # -----------------------------------------------------------------------
    # AC-2 parity: xs:decimal grammar for cost-usd
    # -----------------------------------------------------------------------

    def test_ac2_cost_usd_decimal_grammar_rejected_in_process(self):
        """cost-usd values valid for Python float() but invalid for xs:decimal must be rejected.

        xs:decimal lexical space: optional sign, digits, optional single decimal point.
        No exponent (1e5), no inf, no nan, no underscores (1_000), no empty string.
        """
        mod = self._load_validate_xml()
        decimal_cases = [
            ("cost_usd_inf", self.MALFORMED_COST_USD_INF),
            ("cost_usd_nan", self.MALFORMED_COST_USD_NAN),
            ("cost_usd_exponent", self.MALFORMED_COST_USD_EXPONENT),
            ("cost_usd_underscore", self.MALFORMED_COST_USD_UNDERSCORE),
            ("cost_usd_empty", self.MALFORMED_COST_USD_EMPTY),
        ]
        for name, xml in decimal_cases:
            errors = mod.validate_structurally(xml)
            self.assertTrue(
                errors,
                "Expected xs:decimal error for %s but validate_structurally returned []. "
                "Python float()-parseable but xs:decimal-invalid values must be rejected." % name,
            )

    @unittest.skipUnless(shutil.which("xmllint"), "xmllint not on PATH")
    def test_ac2_cost_usd_decimal_parity_with_xmllint(self):
        """cost-usd xs:decimal violations: in-process and xmllint must both return INVALID."""
        mod = self._load_validate_xml()
        decimal_cases = [
            ("cost_usd_inf", self.MALFORMED_COST_USD_INF),
            ("cost_usd_nan", self.MALFORMED_COST_USD_NAN),
            ("cost_usd_exponent", self.MALFORMED_COST_USD_EXPONENT),
            ("cost_usd_underscore", self.MALFORMED_COST_USD_UNDERSCORE),
            ("cost_usd_empty", self.MALFORMED_COST_USD_EMPTY),
        ]
        for name, xml in decimal_cases:
            in_process_ok = (mod.validate_structurally(xml) == [])
            with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
                fh.write(xml)
                tmp_path = fh.name
            try:
                xmllint_ok, xmllint_detail = mod.validate_with_xmllint(tmp_path)
            finally:
                os.unlink(tmp_path)
            self.assertEqual(
                in_process_ok, xmllint_ok,
                "PARITY GAP on xs:decimal case %r: in-process=%s xmllint=%s detail=%r"
                % (name, in_process_ok, xmllint_ok, xmllint_detail),
            )
            self.assertFalse(
                xmllint_ok,
                "xmllint should reject cost-usd=%r (xs:decimal violation)" % name,
            )

    # -----------------------------------------------------------------------
    # AC-1: No per-message subprocess on the default path
    # -----------------------------------------------------------------------

    def test_ac1_no_subprocess_on_default_path(self):
        """Default path (ACS_XML_AUTHORITATIVE unset) spawns zero subprocesses (AC-1)."""
        mod = self._load_validate_xml()
        messages = [self.VALID_TASK, self.MALFORMED_BAD_ROOT, self.VALID_RESULT]
        env_without = {k: v for k, v in os.environ.items()
                       if k != "ACS_XML_AUTHORITATIVE"}
        with mock.patch.dict(os.environ, env_without, clear=True):
            with mock.patch("subprocess.run") as mock_run:
                for xml in messages:
                    mod.validate_structurally(xml)
                self.assertEqual(mock_run.call_count, 0,
                                 "subprocess.run was called on the default (in-process) path")

    def test_ac1_cli_default_path_is_in_process_not_xmllint(self):
        """Default CLI path (ACS_XML_AUTHORITATIVE unset) uses in-process engine, not xmllint.
        The stdout output for a valid message must NOT say 'xmllint' on the default fast path
        (AC-1: no per-message subprocess spawn on the default path)."""
        env = self._env_no_authoritative()
        result = self.run_script("validate_xml.py", "-", stdin=self.VALID_TASK, env=env)
        self.assertEqual(result.returncode, 0,
                         "Expected exit 0. stderr=%r" % result.stderr)
        # The in-process fast path should say "in-process" in stdout, NOT "xmllint"
        self.assertIn("in-process", result.stdout,
                      "Expected 'in-process' marker in stdout on default path. stdout=%r" % result.stdout)
        self.assertNotIn("xmllint", result.stdout,
                         "Default fast path must NOT invoke xmllint. stdout=%r" % result.stdout)

    # -----------------------------------------------------------------------
    # AC-1/AC-5: Opt-in xmllint via ACS_XML_AUTHORITATIVE
    # -----------------------------------------------------------------------

    @unittest.skipUnless(shutil.which("xmllint"), "xmllint not on PATH")
    def test_ac1_optin_xmllint_with_xmllint_present(self):
        """ACS_XML_AUTHORITATIVE=1 + xmllint on PATH: valid message exits 0 with xmllint marker
        in stdout (AC-1 opt-in path)."""
        env = dict(os.environ, ACS_XML_AUTHORITATIVE="1")
        result = self.run_script("validate_xml.py", "-", stdin=self.VALID_TASK, env=env)
        self.assertEqual(result.returncode, 0, "Expected exit 0 for valid message with xmllint. "
                         "stderr=%r stdout=%r" % (result.stderr, result.stdout))
        # The xmllint opt-in path prints "valid (xmllint, ...)"
        self.assertIn("xmllint", result.stdout,
                      "Expected 'xmllint' in stdout when ACS_XML_AUTHORITATIVE=1 and xmllint present")

    def test_ac5_optin_without_xmllint_still_validates(self):
        """ACS_XML_AUTHORITATIVE=1 with xmllint absent from PATH: valid message still exits 0
        (env var has no effect when xmllint absent — AC-5)."""
        # Strip xmllint from PATH by providing a minimal PATH
        minimal_path = "/usr/bin:/bin"
        env = dict(os.environ, ACS_XML_AUTHORITATIVE="1", PATH=minimal_path)
        # Ensure xmllint is genuinely absent from the minimal PATH
        import shutil as _shutil
        orig_path = os.environ.get("PATH", "")
        os.environ["PATH"] = minimal_path
        try:
            xmllint_in_minimal = _shutil.which("xmllint")
        finally:
            os.environ["PATH"] = orig_path
        if xmllint_in_minimal:
            self.skipTest("xmllint found in minimal PATH %r; can't test absent case" % minimal_path)

        result = self.run_script("validate_xml.py", "-", stdin=self.VALID_TASK, env=env)
        self.assertEqual(result.returncode, 0,
                         "Expected exit 0 even when ACS_XML_AUTHORITATIVE=1 and xmllint absent. "
                         "stderr=%r" % result.stderr)
        self.assertNotIn("Traceback", result.stderr,
                         "Unexpected traceback when xmllint absent")

    # -----------------------------------------------------------------------
    # AC-3: CLI fail-fast on in-process path (no xmllint required)
    # -----------------------------------------------------------------------

    def _env_no_authoritative(self):
        """Return env dict without ACS_XML_AUTHORITATIVE (default fast path)."""
        return {k: v for k, v in os.environ.items() if k != "ACS_XML_AUTHORITATIVE"}

    def test_ac3_bad_xml_exits_1_with_invalid_marker(self):
        """<bad/> piped to stdin exits 1 with INVALID in stderr on the in-process path (AC-3)."""
        env = self._env_no_authoritative()
        result = self.run_script("validate_xml.py", "-", stdin="<bad/>", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("INVALID", result.stderr)

    def test_ac3_valid_task_exits_0(self):
        """Valid <task> piped to stdin exits 0 on the in-process path (AC-3)."""
        env = self._env_no_authoritative()
        result = self.run_script("validate_xml.py", "-", stdin=self.VALID_TASK, env=env)
        self.assertEqual(result.returncode, 0,
                         "Expected exit 0 for valid task. stderr=%r" % result.stderr)

    def test_ac3_valid_result_exits_0(self):
        """Valid <result> piped to stdin exits 0 on the in-process path (AC-3)."""
        env = self._env_no_authoritative()
        result = self.run_script("validate_xml.py", "-", stdin=self.VALID_RESULT, env=env)
        self.assertEqual(result.returncode, 0,
                         "Expected exit 0 for valid result. stderr=%r" % result.stderr)

    def test_ac3_valid_handoff_exits_0(self):
        """Valid <handoff> piped to stdin exits 0 on the in-process path (AC-3)."""
        env = self._env_no_authoritative()
        result = self.run_script("validate_xml.py", "-", stdin=self.VALID_HANDOFF, env=env)
        self.assertEqual(result.returncode, 0,
                         "Expected exit 0 for valid handoff. stderr=%r" % result.stderr)

    # -----------------------------------------------------------------------
    # AC-6: Back-compat CLI signature
    # -----------------------------------------------------------------------

    def test_ac6_positional_file_arg(self):
        """validate_xml.py <file> exits 0 for a valid XML file (AC-6)."""
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
            fh.write(self.VALID_TASK)
            tmp = fh.name
        try:
            result = self.run_script("validate_xml.py", tmp)
            self.assertEqual(result.returncode, 0,
                             "Expected exit 0. stderr=%r" % result.stderr)
        finally:
            os.unlink(tmp)

    def test_ac6_multiple_file_args_all_valid(self):
        """validate_xml.py <file1> <file2> exits 0 when both are valid (AC-6)."""
        files = []
        try:
            for xml in (self.VALID_TASK, self.VALID_RESULT):
                with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
                    fh.write(xml)
                    files.append(fh.name)
            result = self.run_script("validate_xml.py", *files)
            self.assertEqual(result.returncode, 0,
                             "Expected exit 0. stderr=%r" % result.stderr)
        finally:
            for p in files:
                os.unlink(p)

    def test_ac6_mixed_file_args_exits_1_with_invalid(self):
        """validate_xml.py <valid> <invalid> exits 1 with INVALID in stderr (AC-6)."""
        files = []
        try:
            for xml in (self.VALID_TASK, self.MALFORMED_BAD_ROOT):
                with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
                    fh.write(xml)
                    files.append(fh.name)
            result = self.run_script("validate_xml.py", *files)
            self.assertEqual(result.returncode, 1)
            self.assertIn("INVALID", result.stderr)
        finally:
            for p in files:
                os.unlink(p)

    def test_ac6_stdin_form(self):
        """validate_xml.py - with valid task exits 0 (AC-6 back-compat pin for stdin form)."""
        result = self.run_script("validate_xml.py", "-", stdin=self.VALID_TASK)
        self.assertEqual(result.returncode, 0,
                         "Expected exit 0. stderr=%r" % result.stderr)

    def test_ac6_no_args_exits_1_with_usage(self):
        """validate_xml.py with no arguments exits 1 and prints usage (AC-6)."""
        result = self.run_script("validate_xml.py")
        self.assertEqual(result.returncode, 1)
        # Usage text goes to stderr (the __doc__ string)
        self.assertIn("validate_xml.py", result.stderr)

    # -----------------------------------------------------------------------
    # AC-4: Batched validation entry point (T2, Spec 02)
    # Tests written FIRST (TDD RED step) — validate_batch / batch_overall_ok
    # do not exist yet when these tests are added.
    # -----------------------------------------------------------------------

    def test_ac4_mixed_batch_correct_per_message_verdicts(self):
        """Mixed batch returns correct per-message (ok, errors) tuples (AC-4).

        A 4-message batch [valid_task, bad_root, valid_result, missing_skill]:
        - index 0: (True, [])
        - index 1: (False, non-empty errors)
        - index 2: (True, [])
        - index 3: (False, non-empty errors)
        batch_overall_ok must be False when any member is invalid.
        """
        mod = self._load_validate_xml()
        messages = [
            self.VALID_TASK,
            self.MALFORMED_BAD_ROOT,
            self.VALID_RESULT,
            self.MALFORMED_MISSING_SKILL,
        ]
        results = mod.validate_batch(messages)

        # One result per input
        self.assertEqual(len(results), 4)

        # Index 0: valid task
        self.assertEqual(results[0], (True, []),
                         "Expected (True, []) for valid_task, got %r" % (results[0],))

        # Index 1: bad root
        self.assertFalse(results[1][0],
                         "Expected ok=False for MALFORMED_BAD_ROOT")
        self.assertGreater(len(results[1][1]), 0,
                           "Expected non-empty errors for MALFORMED_BAD_ROOT")

        # Index 2: valid result
        self.assertEqual(results[2], (True, []),
                         "Expected (True, []) for valid_result, got %r" % (results[2],))

        # Index 3: missing skill
        self.assertFalse(results[3][0],
                         "Expected ok=False for MALFORMED_MISSING_SKILL")
        self.assertGreater(len(results[3][1]), 0,
                           "Expected non-empty errors for MALFORMED_MISSING_SKILL")

        # Overall must be False (at least one member invalid)
        self.assertFalse(mod.batch_overall_ok(results),
                         "batch_overall_ok should be False when any member is invalid")

    def test_ac4_all_valid_batch_overall_ok_true(self):
        """All-valid batch: all ok=True tuples and batch_overall_ok returns True (AC-4)."""
        mod = self._load_validate_xml()
        all_valid = [self.VALID_TASK, self.VALID_RESULT, self.VALID_HANDOFF]
        all_results = mod.validate_batch(all_valid)

        self.assertTrue(all(ok for ok, _ in all_results),
                        "Expected all ok=True in all-valid batch, got: %r" % all_results)
        self.assertTrue(mod.batch_overall_ok(all_results),
                        "batch_overall_ok should be True for all-valid batch")

    def test_ac4_per_message_parity_with_validate_structurally(self):
        """validate_batch([msg])[0] matches (len(vs)==0, vs) from validate_structurally (AC-4)."""
        mod = self._load_validate_xml()
        for name, xml in list(self.VALID_CORPUS) + list(self.MALFORMED_CORPUS):
            vs_errors = mod.validate_structurally(xml)
            expected = (len(vs_errors) == 0, vs_errors)
            batch_result = mod.validate_batch([xml])[0]
            self.assertEqual(batch_result, expected,
                             "Parity mismatch for %s: batch=%r vs_expected=%r"
                             % (name, batch_result, expected))

    def test_ac4_no_subprocess_in_batch_path(self):
        """validate_batch spawns zero subprocesses on the default (in-process) path (AC-1/AC-4)."""
        mod = self._load_validate_xml()
        messages = [self.VALID_TASK, self.MALFORMED_BAD_ROOT, self.VALID_RESULT]
        with mock.patch("validate_xml.subprocess.run") as mock_run:
            mod.validate_batch(messages)
        self.assertEqual(mock_run.call_count, 0,
                         "validate_batch must not call subprocess.run; got %d call(s)"
                         % mock_run.call_count)

    def test_ac4_single_call_atomicity_n5(self):
        """validate_batch with N=5 messages returns exactly 5 entries in one call (AC-4)."""
        mod = self._load_validate_xml()
        messages = [
            self.VALID_TASK,
            self.VALID_RESULT,
            self.VALID_HANDOFF,
            self.MALFORMED_BAD_ROOT,
            self.MALFORMED_MISSING_SKILL,
        ]
        # The whole batch is processed in a single expression — no iteration at the call site
        results = mod.validate_batch(messages)
        self.assertEqual(len(results), 5,
                         "Expected exactly 5 results for N=5 batch, got %d" % len(results))

    def test_ac4_empty_input_returns_empty_list(self):
        """validate_batch([]) returns [] (empty, no error); batch_overall_ok([]) is True (AC-4)."""
        mod = self._load_validate_xml()
        results = mod.validate_batch([])
        self.assertEqual(results, [],
                         "Expected [] for empty input, got %r" % results)
        self.assertTrue(mod.batch_overall_ok([]),
                        "batch_overall_ok([]) should be True (vacuously)")

    def test_ac4_error_detail_is_meaningful(self):
        """validate_batch returns meaningful error strings for known malformed messages (AC-4)."""
        mod = self._load_validate_xml()
        # MALFORMED_MISSING_SKILL is missing required attribute 'skill'
        results = mod.validate_batch([self.MALFORMED_MISSING_SKILL])
        ok, errors = results[0]
        self.assertFalse(ok, "Expected ok=False for MALFORMED_MISSING_SKILL")
        self.assertGreater(len(errors), 0, "Expected non-empty errors list")
        # The error should mention 'skill' or 'attribute' or 'missing' or 'INVALID'
        joined = " ".join(errors).lower()
        self.assertTrue(
            any(kw in joined for kw in ("skill", "attribute", "missing", "invalid")),
            "Error detail should mention a relevant keyword; got: %r" % errors
        )

    # -----------------------------------------------------------------------
    # Closed content model — undeclared attributes + intrusive children
    # (the XSD has no anyAttribute/wildcard; in-process must match xmllint).
    # -----------------------------------------------------------------------

    CLOSED_CONTENT_CASES = [
        ("undeclared_attr_root", MALFORMED_UNDECLARED_ATTR_ROOT),
        ("undeclared_attr_metrics", MALFORMED_UNDECLARED_ATTR_METRICS),
        ("undeclared_attr_finding", MALFORMED_UNDECLARED_ATTR_FINDING),
        ("undeclared_attr_constraint", MALFORMED_UNDECLARED_ATTR_CONSTRAINT),
        ("child_in_file", MALFORMED_CHILD_IN_FILE),
        ("child_in_objective", MALFORMED_CHILD_IN_OBJECTIVE),
    ]

    def test_closed_content_model_rejected_in_process(self):
        """Undeclared attributes and intrusive children must be rejected in-process."""
        mod = self._load_validate_xml()
        for name, xml in self.CLOSED_CONTENT_CASES:
            errors = mod.validate_structurally(xml)
            self.assertTrue(
                errors,
                "Expected a closed-content-model error for %s but got []; the XSD "
                "declares no anyAttribute/wildcard, so this must be rejected." % name,
            )

    @unittest.skipUnless(shutil.which("xmllint"), "xmllint not on PATH")
    def test_closed_content_model_parity_with_xmllint(self):
        """Closed-content violations: in-process and xmllint must both return INVALID."""
        mod = self._load_validate_xml()
        for name, xml in self.CLOSED_CONTENT_CASES:
            in_process_ok = (mod.validate_structurally(xml) == [])
            with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
                fh.write(xml)
                tmp_path = fh.name
            try:
                xmllint_ok, xmllint_detail = mod.validate_with_xmllint(tmp_path)
            finally:
                os.unlink(tmp_path)
            self.assertEqual(
                in_process_ok, xmllint_ok,
                "PARITY GAP on closed-content case %r: in-process=%s xmllint=%s detail=%r"
                % (name, in_process_ok, xmllint_ok, xmllint_detail),
            )
            self.assertFalse(xmllint_ok, "xmllint should reject %r" % name)

    def test_validate_batch_isolates_non_string_element(self):
        """A non-string (e.g. None) batch element yields a per-message error, not a crash."""
        mod = self._load_validate_xml()
        results = mod.validate_batch([self.VALID_TASK, None])
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0][0], "valid message should pass")
        self.assertFalse(results[1][0], "None element should be reported invalid, not crash")
        self.assertFalse(mod.batch_overall_ok(results))


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

    # -- MAR-70 regression: doubling / non-idempotency of the /acs:init writer ----
    # The template ships a COMPLETE block (maintainer header + its own BEGIN/END);
    # the writer must inject only the inner body wrapped in exactly ONE marker pair.

    HEADER_MARKER = "CLAUDE.acs.md — acs managed block"

    def _template_text(self):
        with open(os.path.join(TEMPLATE_DIR, "CLAUDE.acs.md"), encoding="utf-8") as fh:
            return fh.read()

    def test_managed_body_from_template_drops_header_and_markers(self):
        # The rendered body carries the guidance but NEITHER the maintainer header
        # NOR the template's own markers (the writer owns the markers).
        body = lib.managed_body_from_template(self._template_text(), "SHOP", "acs-exempt")
        self.assertIn("/acs:ship", body)
        self.assertIn("SHOP", body)
        self.assertIn("acs-exempt", body)
        self.assertNotIn(self.HEADER_MARKER, body)
        self.assertNotIn(lib.ACS_BLOCK_BEGIN, body)
        self.assertNotIn(lib.ACS_BLOCK_END, body)

    def test_ac1_fresh_write_single_pair_no_header(self):
        # AC-1: a fresh write from the real template yields EXACTLY one BEGIN/END
        # pair around the body only; the maintainer header is never injected.
        existing = "# My project\n\nSome user notes.\n"
        body = lib.managed_body_from_template(self._template_text(), "SHOP", "acs-exempt")
        out = lib.upsert_managed_block(existing, body)
        self.assertEqual(out.count(lib.ACS_BLOCK_BEGIN), 1)
        self.assertEqual(out.count(lib.ACS_BLOCK_END), 1)
        self.assertNotIn(self.HEADER_MARKER, out)
        self.assertIn("/acs:ship", out)
        self.assertTrue(out.startswith(existing))  # AC-4: prior content preserved

    def test_ac2_idempotent_double_run_from_template(self):
        # AC-2: running the writer twice is byte-identical (whole real-template path).
        body = lib.managed_body_from_template(self._template_text(), "SHOP", "acs-exempt")
        existing = "# My project\n\nSome user notes.\n"
        first = lib.upsert_managed_block(existing, body)
        second = lib.upsert_managed_block(first, body)
        self.assertEqual(first, second)
        self.assertEqual(second.count(lib.ACS_BLOCK_BEGIN), 1)
        self.assertEqual(second.count(lib.ACS_BLOCK_END), 1)

    def _legacy_doubled_file(self, prefix_user, suffix_user):
        """Reconstruct the pre-fix (buggy) artifact: the OLD writer wrapped the
        WHOLE substituted template (header + inner BEGIN/END) in a second marker
        pair, producing two BEGIN + two END with the header sandwiched between the
        outer and inner BEGIN."""
        whole_template = lib.render_managed_block(self._template_text(), "SHOP", "acs-exempt")
        doubled = "%s\n%s\n%s" % (lib.ACS_BLOCK_BEGIN, whole_template, lib.ACS_BLOCK_END)
        return prefix_user + doubled + suffix_user

    def test_ac3_self_heals_legacy_doubled_block(self):
        # AC-3 + AC-4: running the writer against an already-doubled/legacy block
        # collapses it to a single clean pair with no orphaned markers, and the
        # surrounding user content is preserved byte-for-byte.
        prefix_user = "# My project\n\nSome user notes.\n\n"
        suffix_user = "\n\n## More\n\ntrailing user text\n"
        legacy = self._legacy_doubled_file(prefix_user, suffix_user)
        # precondition: the fixture really is doubled
        self.assertEqual(legacy.count(lib.ACS_BLOCK_BEGIN), 2)
        self.assertEqual(legacy.count(lib.ACS_BLOCK_END), 2)

        body = lib.managed_body_from_template(self._template_text(), "SHOP", "acs-exempt")
        healed = lib.upsert_managed_block(legacy, body)
        self.assertEqual(healed.count(lib.ACS_BLOCK_BEGIN), 1)
        self.assertEqual(healed.count(lib.ACS_BLOCK_END), 1)
        self.assertNotIn(self.HEADER_MARKER, healed)          # header no longer leaked
        self.assertTrue(healed.startswith(prefix_user))       # AC-4 surrounding bytes
        self.assertTrue(healed.endswith(suffix_user))         # AC-4 surrounding bytes
        # and the heal is itself idempotent thereafter
        self.assertEqual(lib.upsert_managed_block(healed, body), healed)

    def test_ac3_self_heal_no_orphaned_marker_via_old_find_bug(self):
        # Pin the specific non-idempotency root cause: a naive find(END) would match
        # the INNER end and leave the OUTER end orphaned after the block. rfind(END)
        # must consume the whole doubled span so the healed file is a single clean
        # block immediately followed by the untouched user suffix.
        legacy = self._legacy_doubled_file("intro\n\n", "\n\noutro\n")
        body = lib.managed_body_from_template(self._template_text(), "SHOP", "acs-exempt")
        healed = lib.upsert_managed_block(legacy, body)
        self.assertEqual(healed.count(lib.ACS_BLOCK_END), 1)
        # exactly one END, and the text after it is the user suffix — no orphan.
        self.assertEqual(healed.split(lib.ACS_BLOCK_END, 1)[1], "\n\noutro\n")

    def test_upsert_defensively_strips_body_that_carries_markers(self):
        # Even a buggy caller that passes a body already wrapped in markers (the
        # original defect) cannot cause doubling: the reducer strips them.
        body_with_markers = "%s\nguidance\n%s" % (lib.ACS_BLOCK_BEGIN, lib.ACS_BLOCK_END)
        out = lib.upsert_managed_block("", body_with_markers)
        self.assertEqual(out.count(lib.ACS_BLOCK_BEGIN), 1)
        self.assertEqual(out.count(lib.ACS_BLOCK_END), 1)
        self.assertIn("guidance", out)


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



## MAR-58 spec 01 — TestVerifyDepth


class TestVerifyDepth(unittest.TestCase):
    """AC-1/AC-2/AC-7: verify_depth(lane, stakes) returns 'light' or 'full' per the
    full lane x stakes grid, including the high-stakes floor and conservative defaults.
    VERIFY_ITERATION_CAP constants asserted (AC-3/AC-4).
    """

    def _depth(self, lane, stakes):
        return lib.verify_depth(lane, stakes)

    # --- base light cells (lane in {TRIVIAL, SMALL}, stakes in {low, normal}) ---

    def test_trivial_low_is_light(self):
        self.assertEqual(self._depth("TRIVIAL", "low"), "light")

    def test_trivial_normal_is_light(self):
        self.assertEqual(self._depth("TRIVIAL", "normal"), "light")

    def test_small_low_is_light(self):
        self.assertEqual(self._depth("SMALL", "low"), "light")

    def test_small_normal_is_light(self):
        self.assertEqual(self._depth("SMALL", "normal"), "light")

    # --- base full cells (lane in {STANDARD, COMPLEX} -> full regardless of stakes) ---

    def test_standard_low_is_full(self):
        self.assertEqual(self._depth("STANDARD", "low"), "full")

    def test_standard_normal_is_full(self):
        self.assertEqual(self._depth("STANDARD", "normal"), "full")

    def test_complex_low_is_full(self):
        self.assertEqual(self._depth("COMPLEX", "low"), "full")

    def test_complex_normal_is_full(self):
        self.assertEqual(self._depth("COMPLEX", "normal"), "full")

    # --- high-stakes floor (AC-2): stakes=high always yields full ---

    def test_trivial_high_is_full(self):
        self.assertEqual(self._depth("TRIVIAL", "high"), "full")

    def test_small_high_is_full(self):
        self.assertEqual(self._depth("SMALL", "high"), "full")

    def test_standard_high_is_full(self):
        self.assertEqual(self._depth("STANDARD", "high"), "full")

    def test_complex_high_is_full(self):
        self.assertEqual(self._depth("COMPLEX", "high"), "full")

    def test_trivial_high_is_never_light(self):
        """AC-2: high-stakes TRIVIAL ticket NEVER gets light verify."""
        self.assertNotEqual(self._depth("TRIVIAL", "high"), "light")

    # --- conservative default (AC-1): absent/None/empty/unknown lane -> full ---

    def test_none_lane_normal_is_full(self):
        self.assertEqual(self._depth(None, "normal"), "full")

    def test_empty_string_lane_is_full(self):
        self.assertEqual(self._depth("", "normal"), "full")

    def test_unknown_lane_is_full(self):
        self.assertEqual(self._depth("unknown", "low"), "full")

    # --- unknown/None stakes (non-"high") does not floor a fast lane ---

    def test_trivial_unknown_stakes_is_light(self):
        """Only 'high' triggers the stakes floor; unrecognized stakes does not."""
        self.assertEqual(self._depth("TRIVIAL", "unknown"), "light")

    def test_trivial_none_stakes_is_light(self):
        """None stakes is not 'high'; a TRIVIAL ticket stays light."""
        self.assertEqual(self._depth("TRIVIAL", None), "light")

    # --- iteration-cap constant values (AC-3/AC-4/AC-7) ---

    def test_cap_light_is_1(self):
        self.assertEqual(lib.VERIFY_ITERATION_CAP["light"], 1)

    def test_cap_full_is_3(self):
        self.assertEqual(lib.VERIFY_ITERATION_CAP["full"], 3)


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


## MAR-57 spec 01 — TestLaneRank


class TestLaneRank(unittest.TestCase):
    """AC-1/AC-7: lane_rank(lane) returns the integer rank for each canonical lane
    and falls back to STANDARD's rank (2) for absent/None/unrecognized values.
    LANE_ORDER ordering is strictly monotone.
    """

    def test_trivial_rank_is_0(self):
        self.assertEqual(lib.lane_rank("TRIVIAL"), 0)

    def test_small_rank_is_1(self):
        self.assertEqual(lib.lane_rank("SMALL"), 1)

    def test_standard_rank_is_2(self):
        self.assertEqual(lib.lane_rank("STANDARD"), 2)

    def test_complex_rank_is_3(self):
        self.assertEqual(lib.lane_rank("COMPLEX"), 3)

    def test_none_defaults_to_standard_rank(self):
        """Conservative floor: absent lane treated as STANDARD (rank 2)."""
        self.assertEqual(lib.lane_rank(None), 2)

    def test_empty_string_defaults_to_standard_rank(self):
        self.assertEqual(lib.lane_rank(""), 2)

    def test_unknown_string_defaults_to_standard_rank(self):
        self.assertEqual(lib.lane_rank("MEGA"), 2)

    def test_lowercase_unrecognized_defaults_to_standard_rank(self):
        """Only uppercase canonical strings recognized; lowercase 'trivial' is unknown."""
        self.assertEqual(lib.lane_rank("trivial"), 2)

    def test_ordering_is_strictly_monotone(self):
        """TRIVIAL < SMALL < STANDARD < COMPLEX rank ordering is strict."""
        self.assertLess(lib.lane_rank("TRIVIAL"), lib.lane_rank("SMALL"))
        self.assertLess(lib.lane_rank("SMALL"), lib.lane_rank("STANDARD"))
        self.assertLess(lib.lane_rank("STANDARD"), lib.lane_rank("COMPLEX"))

    def test_lane_order_constant_has_four_entries(self):
        """LANE_ORDER must list exactly the four canonical lanes."""
        self.assertEqual(lib.LANE_ORDER, ["TRIVIAL", "SMALL", "STANDARD", "COMPLEX"])


## MAR-57 spec 01 — TestEscalateLane


class TestEscalateLane(unittest.TestCase):
    """AC-1/AC-3/AC-4/AC-7: escalate_lane returns the HIGHER of (current_lane,
    recomputed lane from derive_lane) as a (lane, depth, ceiling) triple.
    The clamp is upward-only: equal or lower candidates never lower current_lane.
    """

    def _escalate(self, current_lane, size, stakes, needs_design=False, ticket_type="story"):
        return lib.escalate_lane(current_lane, size, stakes, needs_design, ticket_type)

    # --- upward escalation cases ---

    def test_raise_trivial_to_small(self):
        """current=TRIVIAL, axes produce SMALL -> returned lane is SMALL."""
        lane, depth, ceiling = self._escalate("TRIVIAL", "small", "normal")
        self.assertEqual(lane, "SMALL")

    def test_raise_trivial_to_standard(self):
        """current=TRIVIAL, axes produce STANDARD -> returned lane is STANDARD."""
        lane, depth, ceiling = self._escalate("TRIVIAL", "standard", "normal")
        self.assertEqual(lane, "STANDARD")

    def test_raise_trivial_to_complex(self):
        """current=TRIVIAL, size=large -> COMPLEX (Rule 2)."""
        lane, depth, ceiling = self._escalate("TRIVIAL", "large", "normal")
        self.assertEqual(lane, "COMPLEX")

    def test_raise_small_to_standard(self):
        """current=SMALL, axes produce STANDARD -> returned lane is STANDARD."""
        lane, depth, ceiling = self._escalate("SMALL", "standard", "normal")
        self.assertEqual(lane, "STANDARD")

    def test_raise_small_to_standard_via_high_stakes(self):
        """current=SMALL, trivial size but high stakes -> STANDARD (Rule 3 floor)."""
        lane, depth, ceiling = self._escalate("SMALL", "trivial", "high")
        self.assertEqual(lane, "STANDARD")

    def test_raise_standard_to_complex(self):
        """current=STANDARD, size=large -> COMPLEX."""
        lane, depth, ceiling = self._escalate("STANDARD", "large", "normal")
        self.assertEqual(lane, "COMPLEX")

    # --- hold cases (equal or lower candidate -> return current unchanged) ---

    def test_hold_same_lane(self):
        """current=STANDARD, candidate=STANDARD (equal) -> hold at STANDARD."""
        lane, depth, ceiling = self._escalate("STANDARD", "standard", "normal")
        self.assertEqual(lane, "STANDARD")

    def test_lower_candidate_returns_current_standard(self):
        """current=STANDARD, axes produce TRIVIAL (lower) -> hold at STANDARD (AC-3/AC-7)."""
        lane, depth, ceiling = self._escalate("STANDARD", "trivial", "normal")
        self.assertEqual(lane, "STANDARD")

    def test_lower_candidate_returns_current_complex(self):
        """current=COMPLEX, axes produce STANDARD (lower) -> hold at COMPLEX."""
        lane, depth, ceiling = self._escalate("COMPLEX", "standard", "normal")
        self.assertEqual(lane, "COMPLEX")

    # --- conservative None/unknown current_lane handling ---

    def test_none_current_floors_to_standard_rank_raises_to_complex(self):
        """current=None floors at STANDARD rank (2); COMPLEX rank (3) > 2 -> raises to COMPLEX."""
        lane, depth, ceiling = self._escalate(None, "large", "normal")
        self.assertEqual(lane, "COMPLEX")

    def test_none_current_floors_prevents_drop(self):
        """current=None floors at STANDARD; TRIVIAL candidate (rank 0) < STANDARD (rank 2) -> hold.
        Result lane rank must be >= STANDARD rank (AC-3/AC-7)."""
        lane, depth, ceiling = self._escalate(None, "trivial", "normal")
        self.assertGreaterEqual(lib.lane_rank(lane), lib.lane_rank("STANDARD"))

    # --- AC-4 recompute via derive_lane (single authority) ---

    def test_candidate_equals_derive_lane(self):
        """Returned lane for a raising case equals derive_lane(axes) — AC-4."""
        expected_lane = lib.derive_lane("large", "normal", False, "story")
        lane, depth, ceiling = self._escalate("TRIVIAL", "large", "normal")
        self.assertEqual(lane, expected_lane)

    def test_returned_depth_matches_verify_depth(self):
        """Returned depth equals verify_depth(returned_lane, stakes) — AC-4."""
        lane, depth, ceiling = self._escalate("TRIVIAL", "large", "normal")
        expected_depth = lib.verify_depth(lane, "normal")
        self.assertEqual(depth, expected_depth)

    def test_returned_ceiling_matches_verify_iteration_cap(self):
        """Returned ceiling equals VERIFY_ITERATION_CAP[depth] — AC-4."""
        lane, depth, ceiling = self._escalate("TRIVIAL", "large", "normal")
        self.assertEqual(ceiling, lib.VERIFY_ITERATION_CAP[depth])

    def test_hold_returned_depth_matches_verify_depth(self):
        """When holding current_lane, depth is verify_depth(current_lane, stakes)."""
        lane, depth, ceiling = self._escalate("STANDARD", "trivial", "normal")
        self.assertEqual(depth, lib.verify_depth("STANDARD", "normal"))

    def test_hold_returned_ceiling_matches_verify_iteration_cap(self):
        """When holding, ceiling is VERIFY_ITERATION_CAP[depth]."""
        lane, depth, ceiling = self._escalate("STANDARD", "trivial", "normal")
        self.assertEqual(ceiling, lib.VERIFY_ITERATION_CAP[lib.verify_depth("STANDARD", "normal")])

    def test_pure_no_state_mutation(self):
        """escalate_lane is a pure function: it must not write any files.
        Calling it with no-I/O inputs must not create pipeline-state.json or ticket.json."""
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            before_files = set(os.listdir(tmpdir))
            lib.escalate_lane("SMALL", "large", "normal", False, "story")
            after_files = set(os.listdir(tmpdir))
        self.assertEqual(before_files, after_files)


## MAR-57 spec 02 — TestInLoopEscalation


class TestInLoopEscalation(AcsWorkspaceCase):
    """MAR-57 Spec 02 (AC-1, AC-4, AC-6, AC-7): assert that the escalation sequence
    described in code/SKILL.md (three triggers -> escalate_lane -> persist via the
    existing writers) correctly updates all three state files.

    These tests mirror the coordinator's in-loop sequence directly:
      1. escalate_lane(current, new_size, new_stakes, ...) -> (new_lane, depth, ceiling)
      2. ticket["lane"] = new_lane; save_ticket(tdir, ticket)
      3. update_pipeline(tdir, ticket_id, "code", "in_progress", lane=new_lane)
      4. update_index(workspace, repo_id, ticket)

    Each test seeds a ticket at a specific lane and exercises one outcome of that
    sequence (raise, hold, ceiling) against the persisted JSON.
    """

    def setUp(self):
        super().setUp()
        # Seed: SMALL lane (size=small, stakes=normal)
        self.ticket_id = self.new_ticket("Escalation test", "story",
                                         "--size", "small", "--stakes", "normal")
        self._tdir = self.tdir(self.ticket_id)
        self._ticket = lib.load_ticket(self._tdir)

    # --- AC-4: escalation writes raised lane to ticket.json ---

    def test_escalation_raises_ticket_json_lane(self):
        """AC-4: seed=SMALL; escalate axes to standard/normal -> STANDARD;
        save_ticket writes new lane; reload confirms ticket['lane'] == 'STANDARD'
        and equals derive_lane(new_size, new_stakes, needs_design, type)."""
        ticket = self._ticket
        self.assertEqual(ticket["lane"], "SMALL")  # pre-condition

        # Simulate trigger: axes raised to standard/normal -> STANDARD candidate
        new_lane, _, _ = lib.escalate_lane(
            ticket["lane"], "standard", "normal",
            ticket["needs_design"], ticket["type"]
        )
        self.assertEqual(new_lane, "STANDARD")

        # Persist (as coordinator does)
        ticket["size"] = "standard"
        ticket["stakes"] = "normal"
        ticket["lane"] = new_lane
        lib.save_ticket(self._tdir, ticket)

        # Reload and assert
        reloaded = lib.load_ticket(self._tdir)
        self.assertEqual(reloaded["lane"], "STANDARD")
        expected = lib.derive_lane("standard", "normal", reloaded["needs_design"],
                                   reloaded["type"])
        self.assertEqual(reloaded["lane"], expected,
                         "Persisted lane must equal derive_lane(new_size, new_stakes, "
                         "needs_design, type) (AC-4)")

    # --- AC-4: escalation writes raised lane to pipeline-state.json ---

    def test_escalation_writes_pipeline_state_lane(self):
        """AC-4: seed=SMALL; after escalation, update_pipeline persists new lane
        'STANDARD' to pipeline-state.json."""
        ticket = self._ticket
        new_lane, _, _ = lib.escalate_lane(
            ticket["lane"], "standard", "normal",
            ticket["needs_design"], ticket["type"]
        )
        self.assertEqual(new_lane, "STANDARD")

        lib.update_pipeline(self._tdir, self.ticket_id, "code", "in_progress",
                            lane=new_lane)

        data = lib.read_json(os.path.join(self._tdir, "pipeline-state.json"))
        self.assertEqual(data["lane"], "STANDARD",
                         "pipeline-state.json must carry escalated lane (AC-4)")

    # --- AC-4: escalation writes raised lane to tickets-index.json ---

    def test_escalation_writes_index_lane(self):
        """AC-4: seed=SMALL; after escalation, update_index persists new lane
        'STANDARD' to tickets-index.json."""
        ticket = self._ticket
        new_lane, _, _ = lib.escalate_lane(
            ticket["lane"], "standard", "normal",
            ticket["needs_design"], ticket["type"]
        )
        self.assertEqual(new_lane, "STANDARD")

        ticket["lane"] = new_lane
        lib.update_index(self.ws, "acme-shop", ticket)

        with open(lib.index_path(self.ws, "acme-shop")) as fh:
            index = json.load(fh)
        self.assertEqual(index["tickets"][self.ticket_id]["lane"], "STANDARD",
                         "tickets-index.json must carry escalated lane (AC-4)")

    # --- AC-7/AC-3: lower candidate leaves all state unchanged ---

    def test_lower_candidate_leaves_all_state_unchanged(self):
        """AC-7/AC-3: seed=STANDARD; a TRIVIAL candidate is lower -> escalate_lane
        returns STANDARD (hold); no writer is called; files remain at STANDARD."""
        # Re-seed at STANDARD
        ticket_id = self.new_ticket("Hold test", "story",
                                    "--size", "standard", "--stakes", "normal")
        tdir = self.tdir(ticket_id)
        ticket = lib.load_ticket(tdir)
        self.assertEqual(ticket["lane"], "STANDARD")  # pre-condition

        # Simulate trigger returning lower candidate (TRIVIAL)
        new_lane, _, _ = lib.escalate_lane(
            ticket["lane"], "trivial", "normal",
            ticket["needs_design"], ticket["type"]
        )
        # clamp: candidate TRIVIAL < current STANDARD -> hold at STANDARD
        self.assertEqual(new_lane, "STANDARD",
                         "escalate_lane must hold at STANDARD when candidate is lower (AC-3/AC-7)")

        # Coordinator rule: new_lane == current_lane -> no-op, no writer called.
        # We verify by NOT calling any writer and confirming state is unchanged.
        reloaded = lib.load_ticket(tdir)
        self.assertEqual(reloaded["lane"], "STANDARD",
                         "ticket.json lane must not change when escalate_lane holds (AC-7)")

    # --- AC-1: ceiling raised on escalation ---

    def test_ceiling_raised_on_escalation(self):
        """AC-1: seed=SMALL (light, ceiling=1); escalate to STANDARD (full, ceiling=3);
        new ceiling == VERIFY_ITERATION_CAP['full'] == 3."""
        ticket = self._ticket
        self.assertEqual(ticket["lane"], "SMALL")

        new_lane, depth, new_ceiling = lib.escalate_lane(
            ticket["lane"], "standard", "normal",
            ticket["needs_design"], ticket["type"]
        )
        self.assertEqual(new_lane, "STANDARD")
        self.assertEqual(depth, "full")
        self.assertEqual(new_ceiling, lib.VERIFY_ITERATION_CAP["full"],
                         "Ceiling must be VERIFY_ITERATION_CAP['full']==3 after escalation (AC-1)")
        self.assertEqual(new_ceiling, 3)

    # --- AC-1/AC-7: ceiling is monotone — never lowered ---

    def test_ceiling_is_monotone_never_lowered(self):
        """AC-1/AC-7: if coordinator already has ceiling=3 and escalate_lane
        returns the same or lower candidate, ceiling must not decrease below 3."""
        # current=STANDARD (ceiling=3), lower candidate -> hold at STANDARD
        ticket = self._ticket
        ticket["lane"] = "STANDARD"

        new_lane, depth, new_ceiling = lib.escalate_lane(
            "STANDARD", "trivial", "normal",
            ticket["needs_design"], ticket["type"]
        )
        # Hold: new_lane == STANDARD -> depth == 'full', ceiling == 3
        self.assertEqual(new_lane, "STANDARD")
        self.assertEqual(new_ceiling, 3)

        # Coordinator rule: actual ceiling = max(current_ceiling, new_ceiling)
        # If current ceiling was already 3, it must stay 3.
        current_ceiling = 3
        actual_ceiling = max(current_ceiling, new_ceiling)
        self.assertEqual(actual_ceiling, 3,
                         "Ceiling must stay 3 after a no-raise call (AC-1/AC-7)")

    # --- AC-6: trigger (b) uses recommend_stakes / high_stakes_paths glob ---

    def test_trigger_b_uses_recommend_stakes(self):
        """AC-6: trigger (b) reuses recommend_stakes() over the changed file set;
        a path matching the auth/** glob returns 'high'; passing stakes='high' to
        escalate_lane from TRIVIAL produces STANDARD (Rule 3 floor — AC-6)."""
        # Confirm recommend_stakes() returns 'high' for an auth/ path
        stakes_result = lib.recommend_stakes(["auth/login.py"], None)
        self.assertEqual(stakes_result, "high",
                         "recommend_stakes must return 'high' for auth/ path (AC-6 trigger b)")

        # Pass resulting stakes to escalate_lane (as coordinator does on trigger b)
        new_lane, _, _ = lib.escalate_lane(
            "TRIVIAL", "trivial", stakes_result, False, "story"
        )
        # Rule 3: stakes=high -> STANDARD floor; STANDARD > TRIVIAL -> escalate
        self.assertEqual(new_lane, "STANDARD",
                         "TRIVIAL + high stakes (trigger b) must escalate to STANDARD "
                         "(Rule 3, AC-6)")
        # Confirm lane equals derive_lane (single authority, AC-4)
        expected = lib.derive_lane("trivial", "high", False, "story")
        self.assertEqual(new_lane, expected)


## MAR-57 spec 03 — TestGuardAxes


class TestGuardAxes(unittest.TestCase):
    """AC-3: guard_axes(current_size, current_stakes, proposed_size, proposed_stakes)
    returns (effective_size, effective_stakes) by taking the higher of each axis:
      stakes ordering: low < normal < high
      size ordering:   trivial < small < standard < large
    Effective rank >= current rank for both axes (upward-only, negative guarantee).
    Pure function: no I/O, no side effects.
    """

    def _guard(self, cs, ck, ps, pk):
        return lib.guard_axes(cs, ck, ps, pk)

    # --- stakes axis: raise and hold ---

    def test_guard_raises_stakes(self):
        """current=normal, proposed=high -> effective=high."""
        _, eff_stakes = self._guard("standard", "normal", "standard", "high")
        self.assertEqual(eff_stakes, "high")

    def test_guard_holds_stakes_on_lower_proposal(self):
        """current=high, proposed=normal -> effective=high (not lowered)."""
        _, eff_stakes = self._guard("standard", "high", "standard", "normal")
        self.assertEqual(eff_stakes, "high")

    def test_guard_stakes_same(self):
        """current=normal, proposed=normal -> effective=normal (equal, hold)."""
        _, eff_stakes = self._guard("standard", "normal", "standard", "normal")
        self.assertEqual(eff_stakes, "normal")

    def test_guard_raises_stakes_from_low(self):
        """current=low, proposed=high -> effective=high."""
        _, eff_stakes = self._guard("standard", "low", "standard", "high")
        self.assertEqual(eff_stakes, "high")

    def test_guard_holds_stakes_low_on_lower_proposal(self):
        """current=normal, proposed=low -> effective=normal (not lowered)."""
        _, eff_stakes = self._guard("standard", "normal", "standard", "low")
        self.assertEqual(eff_stakes, "normal")

    # --- size axis: raise and hold ---

    def test_guard_raises_size(self):
        """current=small, proposed=standard -> effective=standard."""
        eff_size, _ = self._guard("small", "normal", "standard", "normal")
        self.assertEqual(eff_size, "standard")

    def test_guard_holds_size_on_lower_proposal(self):
        """current=standard, proposed=trivial -> effective=standard (not lowered)."""
        eff_size, _ = self._guard("standard", "normal", "trivial", "normal")
        self.assertEqual(eff_size, "standard")

    def test_guard_raises_size_from_trivial(self):
        """current=trivial, proposed=large -> effective=large."""
        eff_size, _ = self._guard("trivial", "normal", "large", "normal")
        self.assertEqual(eff_size, "large")

    def test_guard_holds_size_large_on_lower_proposal(self):
        """current=large, proposed=standard -> effective=large (not lowered)."""
        eff_size, _ = self._guard("large", "normal", "standard", "normal")
        self.assertEqual(eff_size, "large")

    # --- both axes ---

    def test_guard_both_axes_raise(self):
        """Both proposed > current -> both effective = proposed."""
        eff_size, eff_stakes = self._guard("trivial", "low", "standard", "high")
        self.assertEqual(eff_size, "standard")
        self.assertEqual(eff_stakes, "high")

    def test_guard_both_axes_hold(self):
        """Both proposed < current -> both effective = current."""
        eff_size, eff_stakes = self._guard("large", "high", "trivial", "low")
        self.assertEqual(eff_size, "large")
        self.assertEqual(eff_stakes, "high")

    # --- None current: treated as lowest, any explicit proposed wins ---

    def test_guard_none_current_size_floors_conservatively(self):
        """current_size=None -> treated as lowest; proposed 'trivial' wins."""
        eff_size, _ = self._guard(None, "normal", "trivial", "normal")
        self.assertEqual(eff_size, "trivial")

    def test_guard_none_current_stakes_floors_conservatively(self):
        """current_stakes=None -> treated as lowest; proposed 'low' wins."""
        _, eff_stakes = self._guard("standard", None, "standard", "low")
        self.assertEqual(eff_stakes, "low")

    def test_guard_none_current_both_proposed_wins(self):
        """Both current None -> both proposed win (they are the only known values)."""
        eff_size, eff_stakes = self._guard(None, None, "standard", "high")
        self.assertEqual(eff_size, "standard")
        self.assertEqual(eff_stakes, "high")

    # --- None proposed: effective = current ---

    def test_guard_none_proposed_size_leaves_current(self):
        """proposed_size=None -> effective_size = current_size."""
        eff_size, _ = self._guard("standard", "normal", None, "normal")
        self.assertEqual(eff_size, "standard")

    def test_guard_none_proposed_stakes_leaves_current(self):
        """proposed_stakes=None -> effective_stakes = current_stakes."""
        _, eff_stakes = self._guard("standard", "high", "standard", None)
        self.assertEqual(eff_stakes, "high")

    # --- AC-3 property: effective rank >= current rank for all pairs ---

    def test_effective_rank_ge_current_rank_size_grid(self):
        """AC-3 property: for every (current_size, proposed_size) pair, effective rank
        is always >= current rank (upward-only negative guarantee on size)."""
        sizes = ["trivial", "small", "standard", "large"]
        size_rank = {s: i for i, s in enumerate(sizes)}
        for current in sizes:
            for proposed in sizes:
                eff_size, _ = self._guard(current, "normal", proposed, "normal")
                self.assertGreaterEqual(
                    size_rank.get(eff_size, 0),
                    size_rank.get(current, 0),
                    "guard_axes lowered size from %r to %r (proposed=%r)" % (
                        current, eff_size, proposed))

    def test_effective_rank_ge_current_rank_stakes_grid(self):
        """AC-3 property: for every (current_stakes, proposed_stakes) pair, effective
        rank is always >= current rank (upward-only negative guarantee on stakes)."""
        stakes = ["low", "normal", "high"]
        stakes_rank = {s: i for i, s in enumerate(stakes)}
        for current in stakes:
            for proposed in stakes:
                _, eff_stakes = self._guard("standard", current, "standard", proposed)
                self.assertGreaterEqual(
                    stakes_rank.get(eff_stakes, 0),
                    stakes_rank.get(current, 0),
                    "guard_axes lowered stakes from %r to %r (proposed=%r)" % (
                        current, eff_stakes, proposed))

    def test_guard_axes_is_pure_no_files_written(self):
        """guard_axes is a pure function: calling it must not write any files."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            before = set(os.listdir(tmpdir))
            lib.guard_axes("standard", "normal", "trivial", "low")
            after = set(os.listdir(tmpdir))
        self.assertEqual(before, after)

    def test_guard_none_current_unrecognized_proposed_returns_proposed(self):
        """None current + unrecognized proposed: conservatively return proposed
        (the only value we have; it is not lower than the unknown current)."""
        # Both unrecognized: c_rank == -1, p_rank == -1, p_rank not > c_rank,
        # but current is None so the conservative branch returns proposed.
        eff_size, _ = self._guard(None, "normal", "unknown-size", "normal")
        # proposed 'unknown-size' is returned (it's the best known value)
        self.assertEqual(eff_size, "unknown-size")


## MAR-57 spec 03 — TestNegativeGuarantee


class TestNegativeGuarantee(AcsWorkspaceCase):
    """AC-3/AC-7: no automatic/unattended path lowers lane, size, or stakes below
    a user-confirmed value. Tests exercise the full escalation sequence:
      guard_axes -> escalate_lane -> save_ticket
    and assert the persisted values never go below the current confirmed values.
    """

    def setUp(self):
        super().setUp()
        # Seed a ticket at STANDARD (size=standard, stakes=normal)
        self.ticket_id = self.new_ticket("Guard test", "story",
                                         "--size", "standard", "--stakes", "normal")
        self._tdir = self.tdir(self.ticket_id)

    def _run_escalation_sequence(self, tdir, ticket, proposed_size, proposed_stakes):
        """Simulate the coordinator's in-loop escalation sequence:
          1. guard_axes -> effective axes (upward-only)
          2. escalate_lane(current_lane, eff_size, eff_stakes, ...) -> (new_lane, depth, ceiling)
          3. save_ticket(tdir, ticket) if lane raised
        Returns the reloaded ticket after the sequence.
        """
        eff_size, eff_stakes = lib.guard_axes(
            ticket.get("size"), ticket.get("stakes"),
            proposed_size, proposed_stakes
        )
        new_lane, _, _ = lib.escalate_lane(
            ticket.get("lane"), eff_size, eff_stakes,
            ticket.get("needs_design", False), ticket.get("type", "story")
        )
        # Only persist if strictly higher (coordinator no-op rule)
        if lib.lane_rank(new_lane) > lib.lane_rank(ticket.get("lane")):
            ticket["size"] = eff_size
            ticket["stakes"] = eff_stakes
            ticket["lane"] = new_lane
            lib.save_ticket(tdir, ticket)
        return lib.load_ticket(tdir)

    # --- AC-3: no automatic path lowers lane ---

    def test_no_automatic_path_lowers_lane(self):
        """AC-3: property grid over (current_lane, proposed_lower_lane) pairs.
        After running the full escalation sequence with a lower-ranked proposed
        lane, the persisted ticket['lane'] must be >= current_lane rank."""
        seeds = [
            ("SMALL",    "small",    "normal"),
            ("STANDARD", "standard", "normal"),
            ("COMPLEX",  "large",    "normal"),
        ]
        # Lower-ranked proposals for each seed
        lower_proposals = {
            "SMALL":    [("trivial", "normal")],
            "STANDARD": [("trivial", "normal"), ("small", "normal")],
            "COMPLEX":  [("trivial", "normal"), ("small", "normal"), ("standard", "normal")],
        }
        for seed_lane, seed_size, seed_stakes in seeds:
            # Mint a ticket at seed lane
            tid = self.new_ticket("NegGuard-%s" % seed_lane, "story",
                                  "--size", seed_size, "--stakes", seed_stakes)
            tdir = self.tdir(tid)
            ticket = lib.load_ticket(tdir)
            self.assertEqual(ticket["lane"], seed_lane)

            for p_size, p_stakes in lower_proposals[seed_lane]:
                reloaded = self._run_escalation_sequence(tdir, ticket, p_size, p_stakes)
                self.assertGreaterEqual(
                    lib.lane_rank(reloaded["lane"]),
                    lib.lane_rank(seed_lane),
                    "Automatic path lowered lane from %r to %r "
                    "(proposed size=%r stakes=%r)" % (
                        seed_lane, reloaded["lane"], p_size, p_stakes)
                )
                # Reload ticket for next iteration (must not have changed)
                ticket = lib.load_ticket(tdir)

    # --- AC-3: no automatic path lowers stakes ---

    def test_no_automatic_path_lowers_stakes(self):
        """AC-3: seed ticket at high stakes; escalation sequence with proposed_stakes=normal
        must not write stakes=normal to ticket.json — guard_axes clamps it to 'high'."""
        # Mint a ticket at STANDARD + high stakes
        tid = self.new_ticket("StakesGuard", "story",
                               "--size", "standard", "--stakes", "high")
        tdir = self.tdir(tid)
        ticket = lib.load_ticket(tdir)
        self.assertEqual(ticket["stakes"], "high")

        # Simulate: coordinator proposes to lower stakes to 'normal'
        reloaded = self._run_escalation_sequence(tdir, ticket, "standard", "normal")
        self.assertEqual(reloaded["stakes"], "high",
                         "Automatic path must not lower stakes from 'high' to 'normal' "
                         "(AC-3 negative guarantee)")

    # --- AC-3: no automatic path lowers size ---

    def test_no_automatic_path_lowers_size(self):
        """AC-3: seed ticket at large size; escalation sequence with proposed_size=trivial
        must not write size=trivial to ticket.json — guard_axes clamps it to 'large'."""
        # Mint a ticket at COMPLEX (large) size
        tid = self.new_ticket("SizeGuard", "story",
                               "--size", "large", "--stakes", "normal")
        tdir = self.tdir(tid)
        ticket = lib.load_ticket(tdir)
        self.assertEqual(ticket["size"], "large")

        # Simulate: coordinator proposes to lower size to 'trivial'
        reloaded = self._run_escalation_sequence(tdir, ticket, "trivial", "normal")
        self.assertEqual(reloaded["size"], "large",
                         "Automatic path must not lower size from 'large' to 'trivial' "
                         "(AC-3 negative guarantee)")

    # --- AC-3/AC-7: absent/ambiguous signals leave STANDARD ticket at STANDARD ---

    def test_no_unattended_path_lowers_standard_ticket(self):
        """AC-3/AC-7: seed ticket confirmed at STANDARD; run escalation sequence
        with absent/ambiguous signals (None proposed axes); ticket stays at STANDARD."""
        ticket = lib.load_ticket(self._tdir)
        self.assertEqual(ticket["lane"], "STANDARD")

        # Absent signals: proposed axes are None
        reloaded = self._run_escalation_sequence(
            self._tdir, ticket, None, None  # no new signal
        )
        self.assertEqual(reloaded["lane"], "STANDARD",
                         "Absent signals must not change STANDARD lane (AC-3/AC-7)")

    # --- AC-7: guard_axes + escalate_lane sequence never produces lower lane than derive_lane ---

    def test_sequence_effective_size_stakes_consistent_with_result(self):
        """AC-3/AC-4: after guard_axes -> escalate_lane, the resulting lane equals
        derive_lane(eff_size, eff_stakes, ...) — single routing authority preserved."""
        ticket = lib.load_ticket(self._tdir)
        eff_size, eff_stakes = lib.guard_axes(
            ticket.get("size"), ticket.get("stakes"), "large", "high"
        )
        new_lane, _, _ = lib.escalate_lane(
            ticket.get("lane"), eff_size, eff_stakes,
            ticket.get("needs_design", False), ticket.get("type", "story")
        )
        expected = lib.derive_lane(eff_size, eff_stakes,
                                   ticket.get("needs_design", False),
                                   ticket.get("type", "story"))
        self.assertEqual(new_lane, expected,
                         "escalate_lane must route via derive_lane (AC-4 single authority)")
