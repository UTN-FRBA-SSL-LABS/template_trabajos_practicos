import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import local_receipt as receipt
import llm_review
import review_state
import submission_gate


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = Path.cwd()
        self.repo = Path(self.tmp.name)
        os.chdir(self.repo)
        self.git("init", "-q")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "Tests")
        for folder in [".github/scripts", "TP1/src", "TP1/tests/input", "TP1/tests/output/expected"]:
            Path(folder).mkdir(parents=True)
        shutil.copy(ROOT / receipt.RECIPE, receipt.RECIPE)
        shutil.copy(ROOT / "TP1/tests/run_testsuite.sh", "TP1/tests/run_testsuite.sh")
        shutil.copy(ROOT / "TP1/tests/colors.sh", "TP1/tests/colors.sh")
        Path("TP1/tests/settings.sh").write_text("input_extension='.txt'\nmin_percentage_matching_per_test=80\nmin_average_percentage_over_all_test=80\nmin_quantity_test=3\npass_tests=1\n")
        for n in range(1, 4):
            Path(f"TP1/tests/input/test_{n}.txt").write_text("case\n")
            Path(f"TP1/tests/output/expected/test_{n}.txt").write_text("OK\n")
        Path("TP1/src/main.c").write_text('#include <stdio.h>\nint main(void) { puts("OK"); return 0; }\n')
        Path("TP1/GNUmakefile").write_text("all:\n\tmkdir -p bin\n\tcc src/main.c -o bin/tp1\n")
        Path("TP1/README.md").write_text("Descripción\n")
        Path(".gitattributes").write_text("*.c text eol=lf\n*.sh text eol=lf\n")
        Path(".gitignore").write_text("bin/\nobj/\n*.pyc\n__pycache__/\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.base = self.git("rev-parse", "HEAD").strip()

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL, text=True)

    def run_local(self, success=True):
        result = subprocess.run([sys.executable, str(ROOT / receipt.RECIPE), "TP1"],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout[-2000:])
        return result

    def commit_receipt(self):
        self.git("add", "TP1/.verificacion-local.json")
        self.git("commit", "-qm", "constancia")

    def test_real_clean_build_suite_and_remote_validation(self):
        self.run_local()
        self.assertFalse(Path("TP1/bin").exists(), "Clean build must not reuse working-tree binaries")
        self.commit_receipt()
        receipt.validate("TP1", "HEAD", self.base)
        result = subprocess.run([sys.executable, str(ROOT / receipt.RECIPE), "TP1", "--ci"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout[-1000:])

    def test_docs_do_not_invalidate_but_source_and_build_inputs_do(self):
        self.run_local()
        self.commit_receipt()
        Path("TP1/README.md").write_text("Documentación nueva\n")
        self.git("add", ".")
        self.git("commit", "-qm", "docs")
        receipt.validate("TP1", "HEAD", self.base)
        for file in ["TP1/src/main.c", "TP1/GNUmakefile"]:
            with self.subTest(file=file):
                Path(file).write_text(Path(file).read_text() + "\n")
                self.git("add", file)
                self.git("commit", "-qm", "cambio")
                with self.assertRaises(ValueError):
                    receipt.validate("TP1", "HEAD", self.base)

    def test_failed_tests_invalidate_old_receipt_and_ignore_stale_binary(self):
        self.run_local()
        Path("TP1/bin").mkdir()
        Path("TP1/bin/tp1").write_text("old passing binary")
        Path("TP1/src/main.c").write_text('#include <stdio.h>\nint main(void) { puts("WRONG"); return 0; }\n')
        self.git("add", "TP1/src/main.c")
        self.run_local(success=False)
        self.assertEqual(json.loads(Path("TP1/.verificacion-local.json").read_text())["result"], "failed")

    def test_compilation_failure_invalidates_receipt(self):
        self.run_local()
        Path("TP1/src/main.c").write_text("not C")
        self.git("add", "TP1/src/main.c")
        self.run_local(success=False)
        self.assertEqual(json.loads(Path("TP1/.verificacion-local.json").read_text())["result"], "failed")

    def test_official_tests_changed_on_main_require_new_verification(self):
        self.run_local()
        self.commit_receipt()
        head = self.git("rev-parse", "HEAD").strip()
        Path("TP1/tests/settings.sh").write_text(Path("TP1/tests/settings.sh").read_text() + "\n# Updated official suite\n")
        self.git("add", ".")
        self.git("commit", "-qm", "official update")
        with self.assertRaisesRegex(ValueError, "suite no coincide"):
            receipt.validate("TP1", head, "HEAD")

    def test_missing_receipt_unstaged_source_and_symlink(self):
        with self.assertRaises(subprocess.CalledProcessError):
            receipt.validate("TP1", "HEAD", self.base)
        Path("TP1/src/main.c").write_text("changed unstaged")
        self.run_local(success=False)
        Path("TP1/src/link.c").symlink_to("/etc/passwd")
        self.git("add", "TP1/src/link.c")
        with self.assertRaisesRegex(ValueError, "enlaces simbólicos"):
            receipt.fingerprint("TP1")

    def test_crlf_checkout_is_hashed_as_committed_git_content(self):
        source = Path("TP1/src/main.c")
        source.write_bytes(source.read_bytes().replace(b"\n", b"\r\n"))
        self.git("add", "TP1/src/main.c")
        self.run_local()
        self.commit_receipt()
        receipt.validate("TP1", "HEAD", self.base)

    def test_protected_paths_and_branch_scope(self):
        Path("TP1/tests/settings.sh").write_text("pass everything")
        self.git("add", ".")
        self.git("commit", "-qm", "modified tests")
        with self.assertRaisesRegex(ValueError, "protegidos"):
            submission_gate.validate_paths("TP_1", self.base, "HEAD")
        with self.assertRaises(ValueError):
            submission_gate.validate_paths("feature", self.base, "HEAD")

    def test_local_timeout_terminates_process_group(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            receipt.run_bounded(["sh", "-c", "sleep 30 & wait"], self.repo, 0.1)


class MemoryLedger:
    def __init__(self):
        self.state = None
    def read(self, branch):
        return copy.deepcopy(self.state)
    def save(self, branch, record):
        self.state = self.state or {"schema": 1, "branch": branch, "reports": []}
        self.state["reports"].append(record)
        return self.read(branch)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.ledger = MemoryLedger()
        self.calls = 0
        self.published = []
    def generate(self):
        self.calls += 1
        return "Reporte completo", {"input_tokens": 12, "output_tokens": 34}
    def run_review(self, pr=1, head="a" * 40, generation="100", force=False, generate=None, publish=None):
        return llm_review.review_once(self.ledger, "TP_1", pr, head, generation, force,
                                      generate or self.generate, publish or self.published.append)
    def test_one_report_across_new_commits_and_new_prs(self):
        self.assertEqual(self.run_review(), "generated")
        self.assertEqual(self.run_review(head="b" * 40, generation="101"), "reused")
        self.assertEqual(self.run_review(pr=2, generation="102"), "reused")
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.published[-1]["reports"][0]["pr"], 1)
    def test_timeout_and_other_failures_allow_later_success(self):
        for error in [TimeoutError(), RuntimeError("quota"), ValueError("max_tokens")]:
            with self.assertRaises(type(error)):
                self.run_review(generate=lambda: (_ for _ in ()).throw(error))
            self.assertIsNone(self.ledger.state)
        self.run_review()
        self.assertEqual(self.calls, 1)
    def test_comment_failure_reuses_durably_saved_report(self):
        def fail(state):
            self.assertIsNotNone(self.ledger.state)
            raise RuntimeError("GitHub comments unavailable")
        with self.assertRaises(RuntimeError):
            self.run_review(publish=fail)
        self.run_review(generation="101")
        self.assertEqual(self.calls, 1)
    def test_manual_dispatch_once_even_on_rerun_and_history_preserved(self):
        self.run_review()
        self.run_review(generation="200", force=True)
        self.run_review(generation="200", force=True)
        self.assertEqual(self.calls, 2)
        self.assertEqual(len(self.ledger.state["reports"]), 2)
    def test_failed_manual_extra_keeps_previous_complete_report(self):
        self.run_review()
        with self.assertRaises(TimeoutError):
            self.run_review(generation="200", force=True, generate=lambda: (_ for _ in ()).throw(TimeoutError()))
        self.run_review(generation="201")
        self.assertEqual(self.calls, 1)
    def test_codeowners_are_not_collaborator_permissions(self):
        policy = "# teachers\n* @Teacher @Other\n"
        self.assertTrue(review_state.is_codeowner(policy, "teacher"))
        self.assertFalse(review_state.is_codeowner(policy, "student"))
        for complex_policy in ["* @org/team", "* @Teacher\nTP1/ @Student"]:
            with self.assertRaises(ValueError):
                review_state.is_codeowner(complex_policy, "Teacher")
    def test_model_response_must_be_complete_and_nonempty_no_retry(self):
        calls = []
        response = types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text="Complete")],
                                         usage=types.SimpleNamespace(input_tokens=1, output_tokens=2))
        def create(**kwargs):
            calls.append(kwargs)
            return response
        client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
        self.assertEqual(llm_review.generate_report("prompt", client)[0], "Complete")
        response.stop_reason = "max_tokens"
        with self.assertRaises(ValueError):
            llm_review.generate_report("prompt", client)
        response.stop_reason = "end_turn"
        response.content[0].text = " "
        with self.assertRaises(ValueError):
            llm_review.generate_report("prompt", client)
        self.assertEqual(len(calls), 3)
    def test_notice_links_original_pr_and_tested_sha(self):
        self.run_review()
        gh = types.SimpleNamespace(repo="org/repo", comment=lambda pr, text: self.published.append(text))
        review_state.publish_saved(gh, "TP_1", 9, self.ledger.state)
        text = self.published[-1]
        self.assertIn("/pull/1", text)
        self.assertIn("a" * 40, text)
        self.assertIn("no se extiende a commits posteriores", text)
        self.assertIn("ssl-evaluaciones/reportes/TP_1/100.md", text)


if __name__ == "__main__":
    unittest.main()
