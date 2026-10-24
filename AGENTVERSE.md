# Self-Healing Engineering Agent

Chat with this agent from Agentverse or ASI:One to investigate a GitHub issue and propose a tested pull request.
It runs on a dedicated Docker-capable host and connects to Agentverse through a mailbox. It is **not**
executed inside Agentverse hosted-agent infrastructure.

## Commands

- `fix issue #123 in owner/repo` — investigate an allowlisted public repository.
- `show <run-id>` — inspect evidence and the proposed diff.
- `approve <run-id> <full-diff-sha256>` — from the original sender, publish the verified PR.

The agent runs baseline tests, adds a regression test, verifies it fails, applies a fix, and verifies the
configured tests pass before offering approval. It does not merge PRs. If the test environment is not
ready or the checks fail, it stops and reports why.

**Current limits:** text-only issues; no attachments, OCR, private repository checkout, or live API replay.
Only repositories explicitly enabled by the operator are accepted. Do not paste secrets into chat.
