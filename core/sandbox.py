"""Run untrusted project tests with no network or host credentials."""
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from core.security import redact


def test(repo: Path, image: str, argv: list[str], timeout: int = 180) -> tuple[int, str]:
    if not argv or len(argv) > 20 or any(not isinstance(a, str) or not a or len(a) > 300 for a in argv):
        raise ValueError("A bounded test command (argv) is required")
    if not image or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/:@-" for c in image):
        raise ValueError("Invalid Docker image")
    name = "healer-" + uuid4().hex
    cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", "--cap-drop", "ALL",
           "--security-opt", "no-new-privileges", "--pids-limit", "128", "--memory", "1g",
           "--cpus", "1", "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=128m",
           "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{repo.resolve()}:/workspace:rw",
           "-v", f"{(repo / '.git').resolve()}:/workspace/.git:ro",
           "-w", "/workspace", image, *argv]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, redact((result.stdout + result.stderr)[-12000:])
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
        return 124, "Test timed out"
