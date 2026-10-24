import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.orchestrator import Orchestrator
from core.security import apply_patch, git
from core.state import Store


class FakeGitHub:
    def __init__(self, source):
        self.source = source
        self.pushes = 0
        self.prs = 0

    def issue(self, repo, number):
        return {"title": "Fix broken math", "body": "add returns the wrong answer"}

    def default_branch(self, repo):
        return "main"

    def branch_sha(self, repo, branch):
        return git(self.source, "rev-parse", "HEAD").strip()

    def clone(self, repo, dest):
        subprocess.run(["git", "clone", "-q", str(self.source), str(dest)], check=True)

    def push(self, directory, branch):
        self.pushes += 1

    def pr(self, repo, title, body, head, base):
        self.prs += 1
        return "https://github.com/acme/calc/pull/1"

    def existing_pr(self, repo, branch):
        return ""


class FakePlanner:
    def propose(self, task, issue, files, observations=""):
        if task.startswith("Add a minimal regression"):
            return {"reason": "Report the bug", "patch": (
                "diff --git a/tests/test_calc.py b/tests/test_calc.py\n"
                "--- a/tests/test_calc.py\n+++ b/tests/test_calc.py\n"
                "@@ -1 +1,2 @@\n-assert True\n+assert True\n+assert 1 + 1 == 2\n")}
        return {"reason": "e3 proves the reported regression", "patch": (
            "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
            "@@ -1 +1 @@\n-def add(a, b): return a - b\n+def add(a, b): return a + b\n")}


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "tests").mkdir()
        (self.source / "tests/test_calc.py").write_text("assert True\n")
        (self.source / "calc.py").write_text("def add(a, b): return a - b\n")
        for cmd in (["init", "-q", "-b", "main"], ["add", "."],
                    ["-c", "user.name=Tester", "-c", "user.email=test@example.com", "commit", "-qm", "init"]):
            subprocess.run(["git", *cmd], cwd=self.source, check=True)
        self.github = FakeGitHub(self.source)
        self.worker = Orchestrator(Store(self.root / "state"), self.github, FakePlanner())

    def test_approval_gates_publication(self):
        with patch.dict(os.environ, {"HEALER_ALLOWED_REPOS": "acme/calc"}), patch(
                "agents.orchestrator.test", side_effect=[(0, "baseline passed"), (1, "regression failed"), (0, "test passed")]):
            run = self.worker.investigate("acme/calc", 3, "sender-A", ["python", "-m", "pytest"], "python:3.12")
            self.assertEqual(run.status, "awaiting_approval", run.error)
            self.assertEqual([e.trust for e in run.evidence], ["reported", "observed", "observed", "observed"])
            self.assertEqual(self.github.pushes, 0)
            with self.assertRaisesRegex(ValueError, "identity"):
                self.worker.approve(run.id, "sender-B", run.diff_hash)
            with self.assertRaisesRegex(ValueError, "hash"):
                self.worker.approve(run.id, "sender-A", "bad")
            published = self.worker.approve(run.id, "sender-A", run.diff_hash)
            self.assertEqual(published.status, "published")
            self.assertEqual(self.github.prs, 1)

    def test_failed_regression_never_publishes(self):
        with patch.dict(os.environ, {"HEALER_ALLOWED_REPOS": "acme/calc"}), patch(
                "agents.orchestrator.test", return_value=(0, "nothing failed")):
            run = self.worker.investigate("acme/calc", 3, "sender-A", ["pytest"], "python:3.12")
            self.assertEqual(run.status, "failed")
            self.assertEqual(self.github.pushes, 0)
            with self.assertRaises(ValueError):
                self.worker.approve(run.id, "sender-A", run.diff_hash)

    def test_changed_checkout_invalidates_approval(self):
        with patch.dict(os.environ, {"HEALER_ALLOWED_REPOS": "acme/calc"}), patch(
                "agents.orchestrator.test", side_effect=[(0, "baseline passed"), (1, "failed"), (0, "passed")]):
            run = self.worker.investigate("acme/calc", 3, "sender-A", ["pytest"], "python:3.12")
            self.assertEqual(run.status, "awaiting_approval", run.error)
            (self.worker.store.directory(run.id) / "checkout/calc.py").write_text("def add(a, b): return 42\n")
            with self.assertRaisesRegex(ValueError, "changed"):
                self.worker.approve(run.id, "sender-A", run.diff_hash)
            self.assertEqual(self.github.pushes, 0)

    def test_patch_cannot_change_config_or_add_files(self):
        with self.assertRaises(ValueError):
            apply_patch(self.source, "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n")
        with self.assertRaises(ValueError):
            apply_patch(self.source, "diff --git a/new.py b/new.py\n")

    def test_plain_unified_diff_is_accepted(self):
        apply_patch(self.source, "--- a/calc.py\n+++ b/calc.py\n"
                    "@@ -1 +1 @@\n-def add(a, b): return a - b\n+def add(a, b): return a + b\n")
        self.assertIn("return a + b", (self.source / "calc.py").read_text())


if __name__ == "__main__":
    unittest.main()
