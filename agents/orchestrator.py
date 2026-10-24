"""Issue -> failing regression -> fix -> passing tests -> approval -> PR."""
import fcntl
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

from core.github import GitHub
from core.llm import PatchPlanner
from core.models import Run
from core.sandbox import test
from core.security import apply_patch, diff_hash, git, redact, validate_repo
from core.state import Store


def allowed_repos() -> set[str]:
    return {r.strip() for r in os.getenv("HEALER_ALLOWED_REPOS", "").split(",") if r.strip()}


@contextmanager
def locked(directory: Path):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def context_files(repo: Path, issue: str) -> dict[str, str]:
    """Bound context to tracked source/tests. Never read .env or arbitrary paths into the LLM."""
    paths = git(repo, "ls-files", "-z").split("\x00")
    words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_]{3,}", issue.lower()))
    extensions = {".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java"}
    choices = []
    for name in paths:
        p = Path(name)
        if (p.suffix not in extensions or p.name.startswith(".") or
                any(part.startswith(".") for part in p.parts) or (repo / p).is_symlink()):
            continue
        score = sum(w in name.lower() for w in words)
        choices.append((score, name))
    choices.sort(key=lambda x: (-x[0], x[1]))
    selected = {}
    for _, name in choices[:40]:
        path = repo / name
        if path.stat().st_size <= 12000:
            selected[name] = path.read_text(errors="replace")
        if len(selected) >= 12 or sum(map(len, selected.values())) > 45000:
            break
    if not selected:
        raise ValueError("No small, supported source files found; ask a human to narrow the issue")
    return selected


class Orchestrator:
    def __init__(self, store: Store, github: GitHub | None = None, planner: PatchPlanner | None = None):
        self.store = store
        self.github = github or GitHub(os.environ.get("GITHUB_TOKEN", ""))
        self.planner = planner or PatchPlanner()

    def investigate(self, repo: str, issue: int, requester: str,
                    test_command: list[str], image: str) -> Run:
        validate_repo(repo, allowed_repos())
        if issue <= 0 or not requester or not test_command or not image:
            raise ValueError("Issue, requester, test command, and Docker image are required")
        run = Run.new(repo, issue, requester, test_command, image)
        self.store.save(run)
        directory = self.store.directory(run.id)
        with locked(directory):
            try:
                details = self.github.issue(repo, issue)
                description = (details["title"] + "\n" + (details.get("body") or ""))[:12000]
                run.add("github:issue", "reported", redact(description))
                branch = self.github.default_branch(repo)
                checkout = directory / "checkout"
                self.github.clone(repo, checkout)
                base_sha = self.github.branch_sha(repo, branch)
                git(checkout, "checkout", "--detach", base_sha)
                run.base_sha = base_sha
                (directory / "base_branch").write_text(branch)
                files = context_files(checkout, description)
                clean_hash = diff_hash(checkout)
                clean_code, clean_output = test(checkout, image, test_command)
                if diff_hash(checkout) != clean_hash:
                    raise ValueError("Baseline tests modified tracked files")
                if git(checkout, "rev-parse", "HEAD").strip() != base_sha:
                    raise ValueError("Baseline tests changed checkout history")
                run.add("tool:baseline", "observed", f"exit={clean_code}\n{clean_output}")
                if clean_code:
                    raise ValueError("Baseline tests do not pass; cannot attribute a regression to this issue")
                # A generated regression is required: failure must be observed, not inferred from an issue.
                regression = self.planner.propose(
                    "Add a minimal regression test that fails for the issue. Change test files only.",
                    description, files)
                if not all("test" in p.lower() or "spec" in p.lower() for p in
                           re.findall(r"^diff --git a/(.+) b/", regression["patch"], re.M)):
                    raise ValueError("Regression patch must modify test files only")
                apply_patch(checkout, regression["patch"])
                before_tests = diff_hash(checkout)
                code, output = test(checkout, image, test_command)
                if diff_hash(checkout) != before_tests:
                    raise ValueError("Tests modified tracked files")
                if git(checkout, "rev-parse", "HEAD").strip() != base_sha:
                    raise ValueError("Tests changed checkout history")
                run.add("tool:regression", "observed", f"exit={code}\n{output}")
                self.store.save(run)
                if code == 0 or code == 124 or code == 125:
                    raise ValueError("Regression did not produce a usable failing test")
                fix = self.planner.propose(
                    "Fix the defect without changing the regression test. Cite observed evidence e3 in reason.",
                    description, context_files(checkout, description), f"e3: {output}")
                apply_patch(checkout, fix["patch"])
                if not re.search(r"\be3\b", fix["reason"]):
                    raise ValueError("Root-cause explanation must cite observed evidence e3")
                before_tests = diff_hash(checkout)
                code, output = test(checkout, image, test_command)
                if diff_hash(checkout) != before_tests:
                    raise ValueError("Tests modified tracked files")
                if git(checkout, "rev-parse", "HEAD").strip() != base_sha:
                    raise ValueError("Tests changed checkout history")
                run.add("tool:verification", "observed", f"exit={code}\n{output}")
                if code:
                    raise ValueError("Verification failed; no PR will be created")
                git(checkout, "diff", "--check")
                run.summary = redact(fix["reason"][:3000])
                run.diff_hash = diff_hash(checkout)
                run.status = "awaiting_approval"
            except Exception as exc:
                run.status = "failed"
                run.error = redact(str(exc))[:1000]
            self.store.save(run)
        return run

    def approve(self, run_id: str, actor: str, expected_hash: str) -> Run:
        directory = self.store.directory(run_id)
        with locked(directory):
            run = self.store.load(run_id)
            if run.status not in {"awaiting_approval", "approved"}:
                raise ValueError("Run is not awaiting approval")
            if actor != run.requester or expected_hash != run.diff_hash:
                raise ValueError("Approval identity or diff hash does not match")
            validate_repo(run.repo, allowed_repos())
            checkout = directory / "checkout"
            if run.head_sha:
                if git(checkout, "rev-parse", "HEAD").strip() != run.head_sha or git(checkout, "diff", "HEAD", "--"):
                    raise ValueError("Committed checkout changed since approval")
            elif diff_hash(checkout) != run.diff_hash or git(checkout, "rev-parse", "HEAD").strip() != run.base_sha:
                raise ValueError("Checkout changed since verification")
            if run.status == "awaiting_approval":
                run.approved_by = actor
                run.status = "approved"
                self.store.save(run)
            # Delivery is retryable after failure; do not repeat a completed PR.
            branch = f"healer/issue-{run.issue}-{run.id[:12]}"
            base = (directory / "base_branch").read_text().strip()
            if self.github.branch_sha(run.repo, base) != run.base_sha:
                raise ValueError("Default branch moved; rerun investigation")
            if not run.head_sha:
                git(checkout, "config", "user.name", "Self-Healing Agent")
                git(checkout, "config", "user.email", "self-healing-agent@users.noreply.github.com")
                git(checkout, "add", "-u")
                git(checkout, "commit", "-m", f"fix: resolve issue #{run.issue}")
                run.head_sha = git(checkout, "rev-parse", "HEAD").strip()
                self.store.save(run)
            self.github.push(checkout, branch)
            existing = self.github.existing_pr(run.repo, branch)
            if existing:
                run.pr_url = existing
                run.status = "published"
                self.store.save(run)
                return run
            report = (f"Closes #{run.issue}\n\n{run.summary}\n\n"
                      f"Verification: regression failed before the fix and configured tests passed after.\n"
                      f"Approved by {actor}; diff SHA-256: `{run.diff_hash}`.\n\nEvidence:\n" +
                      "\n".join(f"- {e.id} ({e.trust}, {e.source}): {e.content[:300].replace(chr(10), ' ')}"
                                for e in run.evidence))
            run.pr_url = self.github.pr(run.repo, f"Fix #{run.issue}", report, branch, base)
            run.status = "published"
            self.store.save(run)
            return run
