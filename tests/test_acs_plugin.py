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
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

    def run_script(self, script, *args, stdin=None, cwd=None):
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, script)] + list(args),
            input=stdin, capture_output=True, text=True, cwd=cwd or self.repo,
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
        for skill in ("init", "ship", "handoff"):
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
        self.assertEqual(metrics["prs"], {"created": 1, "merged": 1})

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


if __name__ == "__main__":
    unittest.main()
