"""Small GitHub REST client. Git operations never put a token in the URL."""
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from core.security import command, redact


class GitHub:
    def __init__(self, token: str):
        if not token:
            raise ValueError("GITHUB_TOKEN is required")
        self.token = token

    def request(self, method: str, path: str, data: dict | None = None) -> dict:
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request("https://api.github.com" + path, data=body, method=method,
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Accept": "application/vnd.github+json",
                                              "Content-Type": "application/json",
                                              "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"GitHub API {exc.code}: {redact(exc.read(1000).decode(errors='replace'))}") from None

    def issue(self, repo: str, number: int) -> dict:
        issue = self.request("GET", f"/repos/{repo}/issues/{number}")
        if "pull_request" in issue:
            raise ValueError("The requested number is a PR, not an issue")
        return issue

    def default_branch(self, repo: str) -> str:
        return self.request("GET", f"/repos/{repo}")["default_branch"]

    def branch_sha(self, repo: str, branch: str) -> str:
        from urllib.parse import quote
        return self.request("GET", f"/repos/{repo}/git/ref/heads/{quote(branch, safe='/')}")["object"]["sha"]

    def pr(self, repo: str, title: str, body: str, head: str, base: str) -> str:
        return self.request("POST", f"/repos/{repo}/pulls",
                            {"title": title, "body": body, "head": head, "base": base})["html_url"]

    def existing_pr(self, repo: str, branch: str) -> str:
        from urllib.parse import quote
        owner = repo.split("/", 1)[0]
        pulls = self.request("GET", f"/repos/{repo}/pulls?state=open&head={quote(owner + ':' + branch)}")
        return pulls[0]["html_url"] if pulls else ""

    def clone(self, repo: str, destination: Path):
        # v1 supports public repositories only. No credential is passed to untrusted checkout operations.
        command(["git", "clone", "--no-checkout", f"https://github.com/{repo}.git", str(destination)], timeout=180)

    def push(self, directory: Path, branch: str):
        # Git prompts invoke this fixed helper. Neither the URL nor command arguments contain the token.
        with tempfile.TemporaryDirectory(prefix="healer-auth-") as temp:
            script = Path(temp) / "askpass"
            script.write_text('#!/bin/sh\ncase "$1" in *Username*) printf %s x-access-token;; *) printf %s "$GITHUB_TOKEN";; esac\n')
            script.chmod(0o700)
            env = dict(os.environ, GITHUB_TOKEN=self.token, GIT_ASKPASS=str(script), GIT_TERMINAL_PROMPT="0")
            command(["git", "-c", f"safe.directory={directory.resolve()}", "-c", "credential.helper=", "push", "origin",
                     f"HEAD:refs/heads/{branch}"], cwd=directory, timeout=120, env=env)
