"""Repository boundary and safe, bounded patch application."""
import hashlib
import os
import re
import subprocess
from pathlib import Path


def validate_repo(repo: str, allowed: set[str]):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or repo not in allowed:
        raise ValueError("Repository is not in HEALER_ALLOWED_REPOS")


def redact(text: str) -> str:
    text = re.sub(r"(?i)(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})", "[REDACTED]", text)
    for key in ("GITHUB_TOKEN", "ASI_ONE_API_KEY", "AGENT_SEED_PHRASE"):
        secret = os.getenv(key, "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def command(args: list[str], cwd: Path | None = None, timeout: int = 120,
            env: dict | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {redact((result.stdout + result.stderr)[-3000:])}")
    return redact(result.stdout)


def git(repo: Path, *args: str) -> str:
    # Some mounted workspaces map checkout ownership to root. Trust only this
    # agent-created checkout for the current command, never globally.
    return command(["git", "-c", f"safe.directory={repo.resolve()}", *args], cwd=repo)


def apply_patch(repo: Path, patch: str):
    if not patch or len(patch.encode()) > 100_000 or "\x00" in patch:
        raise ValueError("Patch is empty or too large")
    # Unified diffs are valid without Git's optional `diff --git` headers.
    # The model often returns this form; add the headers before the same path
    # and tracked-file checks rather than rejecting a valid patch.
    if "diff --git " not in patch:
        patch = re.sub(
            r"(?m)^--- a/(.+)\n\+\+\+ b/(.+)\n",
            lambda match: f"diff --git a/{match[1]} b/{match[2]}\n{match[0]}",
            patch,
        )
    paths = re.findall(r"^diff --git a/(.+) b/(.+)$", patch, re.M)
    if not paths or len(paths) > 12 or len(paths) != patch.count("diff --git "):
        raise ValueError("Expected a bounded git unified diff")
    tracked = set(git(repo, "ls-files", "-z").split("\x00"))
    for before, after in paths:
        if before != after or before not in tracked:
            raise ValueError("Only changes to existing tracked files are supported")
        path = Path(before)
        if path.is_absolute() or ".." in path.parts or any(p in {".git", ".github"} for p in path.parts):
            raise ValueError("Protected patch path")
        if (repo / path).is_symlink():
            raise ValueError("Symlink patch path")
    if re.search(r"^(?:new file mode|deleted file mode|old mode|new mode|rename (?:from|to)|copy (?:from|to)|GIT binary patch)", patch, re.M):
        raise ValueError("File operations and binary patches are not supported")
    for args in (["git", "-c", f"safe.directory={repo.resolve()}", "apply", "--check", "-"],
                 ["git", "-c", f"safe.directory={repo.resolve()}", "apply", "-"]):
        result = subprocess.run(args, cwd=repo, input=patch, text=True,
                                capture_output=True, timeout=20)
        if result.returncode:
            raise ValueError(f"Patch rejected: {redact(result.stderr)[:500]}")


def diff_hash(repo: Path) -> str:
    return hashlib.sha256(git(repo, "diff", "HEAD", "--binary").encode()).hexdigest()
