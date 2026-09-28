import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github/scripts"))
import review_state as state
import submission_gate
import llm_review


class GitDataAPI:
    """In-memory Git trees/commits, with non-fast-forward rejection and no network."""
    repo = "org/repo"
    def __init__(self):
        self.head = None
        self.trees = {}
        self.commits = {}
        self.conflict = None
    def api(self, method, path, data=None, missing=False):
        if path == "git/ref/heads/ssl-evaluaciones":
            return {"object": {"sha": self.head}} if self.head else None
        if path.startswith("contents/"):
            file, ref = path[9:].split("?ref=")
            content = self.trees[self.commits[ref]["tree"]["sha"]].get(file)
            return {"content": base64.b64encode(content.encode()).decode()} if content else None
        if path == "git/trees":
            tree = copy.deepcopy(self.trees.get(data.get("base_tree"), {}))
            for entry in data["tree"]:
                tree[entry["path"]] = entry["content"]
            sha = f"tree-{len(self.trees)}"
            self.trees[sha] = tree
            return {"sha": sha}
        if path == "git/commits":
            sha = f"commit-{len(self.commits)}"
            self.commits[sha] = {"tree": {"sha": data["tree"]}, "parents": data["parents"]}
            return {"sha": sha}
        if path.startswith("git/commits/"):
            return self.commits[path.split('/')[-1]]
        if method == "POST" and path == "git/refs":
            if self.head:
                raise state.APIError(422, method, path)
            self.head = data["sha"]
            return {}
        if method == "PATCH" and path == "git/refs/heads/ssl-evaluaciones":
            self.assert_no_force(data)
            if self.conflict:
                callback, self.conflict = self.conflict, None
                callback()
            if self.commits[data["sha"]]["parents"] != [self.head]:
                raise state.APIError(422, method, path)
            self.head = data["sha"]
            return {}
        raise AssertionError((method, path))
    def assert_no_force(self, data):
        if data["force"]:
            raise AssertionError("Force updates are forbidden")


class StateAPITests(unittest.TestCase):
    def setUp(self):
        self.gh = GitDataAPI()
        self.ledger = state.Ledger(self.gh)
    def record(self, branch="TP_1", generation="100"):
        return state.report_record(branch, 1, "a" * 40, "Complete report", generation)
    def test_report_and_marker_publish_in_same_commit_and_idempotently(self):
        self.assertIsNone(self.ledger.read("TP_1"))
        record = self.record()
        self.ledger.save("TP_1", record)
        head = self.gh.head
        tree = self.gh.trees[self.gh.commits[head]["tree"]["sha"]]
        self.assertIn("reportes/TP_1/100.md", tree)
        self.assertIn("evaluaciones/TP_1.json", tree)
        self.assertEqual(self.ledger.read("TP_1")["reports"], [record])
        self.ledger.save("TP_1", record)
        self.assertEqual(self.gh.head, head)
    def test_parallel_tp_write_does_not_lose_other_tp_history(self):
        self.ledger.save("TP_1", self.record())
        self.gh.conflict = lambda: self.ledger.save("TP_2", self.record("TP_2", "200"))
        self.ledger.save("TP_1", self.record(generation="101"))
        self.assertEqual(len(self.ledger.read("TP_1")["reports"]), 2)
        self.assertEqual(len(self.ledger.read("TP_2")["reports"]), 1)
    def test_corrupt_state_fails_closed(self):
        self.ledger.save("TP_1", self.record())
        tree = self.gh.trees[self.gh.commits[self.gh.head]["tree"]["sha"]]
        tree["evaluaciones/TP_1.json"] = '{"schema":1,"branch":"TP_1","reports":[]}'
        with self.assertRaises(ValueError):
            self.ledger.read("TP_1")
    def test_api_only_treats_404_as_missing(self):
        gh = state.GitHub("org/repo", "fake-test-token")
        for status in [401, 403, 429, 500, 503]:
            with patch.object(state, "urlopen", side_effect=HTTPError("url", status, "error", {}, None)):
                with self.assertRaises(state.APIError):
                    gh.api("GET", "git/ref/heads/ssl-evaluaciones", missing=True)
        with patch.object(state, "urlopen", side_effect=HTTPError("url", 404, "missing", {}, None)):
            self.assertIsNone(gh.api("GET", "missing", missing=True))
    def test_comment_marker_from_student_is_not_overwritten(self):
        calls = []
        gh = state.GitHub("org/repo", "fake-test-token")
        comments = [{"id": 7, "user": {"login": "student"}, "body": state.MARKER}]
        gh.pages = lambda _: iter(comments)
        gh.api = lambda *args: calls.append(args)
        gh.comment(9, "report")
        self.assertEqual(calls[0][:2], ("POST", "issues/9/comments"))
    def test_legacy_closed_pr_full_report_imported_but_errors_are_not(self):
        body = "\n".join([state.MARKER, "### Resultado:", "### Evaluación de rúbrica", "### Trabajo en equipo",
                          "Revisión automática orientativa — la decisión final es del docente."])
        comment = {"id": 17, "user": {"login": state.BOT}, "body": body,
                   "html_url": "https://example.invalid/comment", "created_at": "2026-09-01"}
        pr = {"number": 4, "state": "closed", "head": {"repo": {"full_name": "org/repo"}}}
        gh = types.SimpleNamespace(repo="org/repo", pages=lambda path: iter([pr] if path.startswith("pulls?") else [comment]))
        recovered = state.find_legacy(gh, "TP_1")
        self.assertEqual(recovered["pr"], 4)
        self.assertIsNone(recovered["head_sha"])
        comment["body"] = state.MARKER + "Error: timeout"
        self.assertIsNone(state.find_legacy(gh, "TP_1"))
        comment["body"] = body
        comment["user"]["login"] = "student"
        self.assertIsNone(state.find_legacy(gh, "TP_1"))


class TriggeringActorTests(unittest.TestCase):
    def test_student_cannot_rerun_teacher_manual_gate(self):
        pr = {"state": "open", "base": {"ref": "main", "sha": "a" * 40},
              "head": {"ref": "TP_1", "sha": "b" * 40, "repo": {"full_name": "org/repo"}}}
        gh = types.SimpleNamespace(repo="org/repo", api=lambda *args: pr)
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "event.json"
            event.write_text('{}')
            env = {"GITHUB_EVENT_PATH": str(event), "GITHUB_EVENT_NAME": "workflow_dispatch",
                   "GITHUB_REF": "refs/heads/main", "REQUEST_PR": "1", "GITHUB_ACTOR": "Teacher",
                   "GITHUB_TRIGGERING_ACTOR": "Student"}
            with patch.dict(os.environ, env), patch.object(submission_gate, "GitHub", return_value=gh), \
                 patch.object(submission_gate, "fetch_shas"), patch.object(submission_gate, "blob", return_value=b"* @Teacher"):
                with self.assertRaisesRegex(ValueError, "Solo un CODEOWNER"):
                    submission_gate.main()
    def test_student_cannot_rerun_review_job_with_teacher_gate_outputs(self):
        pr = {"state": "open", "base": {"ref": "main", "sha": "a" * 40},
              "head": {"ref": "TP_1", "sha": "b" * 40, "repo": {"full_name": "org/repo"}}}
        gh = types.SimpleNamespace(repo="org/repo", api=lambda *args: pr)
        env = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
               "PR_NUMBER": "1", "HEAD_SHA": "b" * 40, "FORCE_REVIEW": "true",
               "GITHUB_ACTOR": "Teacher", "GITHUB_TRIGGERING_ACTOR": "Student"}
        import local_receipt
        with patch.dict(os.environ, env), patch.object(state, "GitHub", return_value=gh), \
             patch.object(submission_gate, "fetch_shas"), patch.object(local_receipt, "blob", return_value=b"* @Teacher"):
            with self.assertRaisesRegex(ValueError, "no es CODEOWNER"):
                llm_review.main()


if __name__ == "__main__":
    unittest.main()
