# 🤖 Self-Healing Engineering Agent

> **A multimodal, ASI:One-native agent that turns broken APIs, GitHub issues, error screenshots, and logs into verified pull requests.**

Built on the **Fetch.ai uAgents framework**. Talk to it from **ASI:One chat**, drop in a screenshot of the failure, and get back a reproduced bug, a root cause, a tested fix, and a PR for a human to review.

---

## 🚀 What is this?

Most coding assistants stop at *"here's the code you should change."* This agent completes the engineering loop:

```text
 Text · Screenshot · Log · Stack trace · OpenAPI · Postman · GitHub Issue
                              │
                              ▼
                    ┌───────────────────┐
                    │  Normalize inputs │   every modality → typed Evidence
                    └─────────┬─────────┘
                              ▼
        Investigate → Reproduce → Root cause → Fix → Test → Verify
                              │
                              ▼
                  Human approval (in chat)
                              │
                              ▼
                 Branch → Commit → Pull Request
```

> **Turn software problems, however they're reported, into verified pull requests with a human in control.**

---

## 💬 Talk to it

The agent is a [Chat Protocol](https://innovationlab.fetch.ai/resources/docs/agent-communication/agent-chat-protocol) uAgent registered on Agentverse, so it can be discovered and chatted with through **ASI:One**.

Example prompts:

```text
Fix issue #142 in acme/billing-api

POST /api/users returns 400 "Invalid field: age" — here's the OpenAPI spec.   [attach: openapi.yaml]

This error shows up in staging. Find the cause and open a PR.                  [attach: error-screenshot.png]

Why does `npm test` fail on CI?                                                [attach: ci-log.txt]
```

While it works, the agent streams progress back into the chat (reproducing → root cause → fix → verification). Before opening a PR it posts the diff and verification report and **waits for your approval**.

---

## 🖼️ Multimodal inputs

Every input, whatever its form, is converted into the same internal structure (`Evidence`), so the rest of the pipeline never cares how a problem was reported.

| Input | Modality | How it's handled | Becomes |
|---|---|---|---|
| Chat message / GitHub issue | Text | Parsed directly | `reported` evidence |
| Error screenshot, terminal capture, Swagger UI / Postman screenshot | Image | OCR + optional vision backend | `extracted` evidence |
| Architecture or whiteboard diagram | Image | Vision backend (if enabled), else asks for text | `extracted` evidence |
| OpenAPI / Swagger spec | Structured file | Schema parser | `reported` evidence |
| Postman collection / HAR file | Structured file | JSON parser | `reported` evidence |
| Logs, stack traces, test output | Text file | Parser + summarizer | `reported` evidence |
| API docs (PDF / Markdown) | Document | Text extraction | `reported` evidence |
| Live API response | Tool output | Executed in sandbox | `observed` evidence |
| Test / lint / typecheck result | Tool output | Executed in sandbox | `observed` evidence |

### Evidence and trust levels

```python
class Evidence(BaseModel):
    id: str
    source: str                                    # e.g. "chat", "screenshot:err.png", "tool:run_tests"
    modality: Literal["text", "image", "file", "tool"]
    trust: Literal["reported", "extracted", "observed"]
    content: str                                   # normalized text or JSON
    meta: dict[str, str] = {}
```

| Trust | Meaning | Example |
|---|---|---|
| `observed` | The agent produced it by running something | Reproduced `400` response, failing test output |
| `reported` | A human or document stated it | Issue text, OpenAPI spec |
| `extracted` | Derived from an image by OCR or a vision model | Error text read from a screenshot |

**Rule: a root cause must be backed by at least one `observed` item.** Anything read from a screenshot is a hypothesis until the agent reproduces it. This is the multimodal version of *reproduce before fixing*.

### Pluggable image perception

```python
class ImagePerceiver(Protocol):
    async def perceive(self, image: bytes, mime: str, hint: str) -> list[Evidence]: ...
```

| Backend | `VISION_BACKEND` | Notes |
|---|---|---|
| Local OCR | `ocr` *(default)* | Deterministic, no image leaves the machine. Best for terminals, logs, and error dialogs |
| ASI:One vision | `asi1` | Enable only after confirming your ASI:One model accepts image input (see [Known limitations](#️-known-limitations)) |
| External VLM | `external` | Optional, for diagrams and complex UI screenshots |

---

## 🧠 Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│                     ASI:One / Agentverse chat                │
└──────────────────────────────┬───────────────────────────────┘
                               │  Chat Protocol (ChatMessage, ResourceContent)
                               ▼
                    ┌──────────────────────┐
                    │  Gateway uAgent      │  ack · validate · session · progress · approval
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │  Orchestrator        │  plans, routes, holds the Evidence store
                    └──────────┬───────────┘
        ┌───────────────┬──────┴────────┬───────────────┐
        ▼               ▼               ▼               ▼
 ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
 │ Perception │  │ Issue Agent│  │ API Agent  │  │ Repo Agent │
 │ image/file │  │ GitHub     │  │ OpenAPI    │  │ search/    │
 │ → Evidence │  │ issues     │  │ HTTP retry │  │ git history│
 └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
       └───────────────┴───────┬───────┴───────────────┘
                               ▼
                    ┌──────────────────────┐
                    │  Fix Agent           │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │  Test + Verify Agent │──▶ Docker sandbox
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │  Git Agent           │  branch · commit · PR (after approval)
                    └──────────────────────┘
```

| Agent | Responsibility | Default model |
|---|---|---|
| **Gateway** | Only agent exposed to ASI:One. Chat Protocol, acknowledgements, progress updates, approval gate | none |
| **Orchestrator** | Intent classification, planning, Evidence store | `asi1-mini` for routing, `asi1` for planning |
| **Perception** | Images and files → `Evidence` | `asi1-mini` (cleanup) |
| **Issue / API / Repo** | Gather evidence from GitHub, OpenAPI, source code and history | `asi1` |
| **Fix** | Root-cause analysis and patch | `asi1`, escalate to `asi1-ultra` |
| **Test + Verify** | Regression tests, test suite, lint, typecheck, API replay | `asi1` |
| **Git** | Branch, commit, PR description | `asi1-mini` |

Specialist agents talk to each other with typed uAgent messages. Only the Gateway speaks the Chat Protocol.

---

## 🧬 ASI:One as the interface

The agent registers on Agentverse with the Chat Protocol manifest published, which lets ASI:One discover it and route users to it.

```python
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, EndSessionContent,
    ResourceContent, TextContent, chat_protocol_spec,
)

agent = Agent(
    name="self-healing-engineer",
    seed=os.environ["AGENT_SEED_PHRASE"],
    port=8000,
    mailbox=True,                      # local agent reachable via Agentverse
    publish_agent_details=True,
    readme_path="README.md",           # this file becomes the Agentverse listing
    handle_messages_concurrently=True, # long-running jobs must not block other chats
)
chat = Protocol(spec=chat_protocol_spec)


def reply(text: str, end: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(
        timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))

    text, attachments = [], []
    for item in msg.content:
        if isinstance(item, TextContent):
            text.append(item.text)
        elif isinstance(item, ResourceContent):
            res = item.resource if isinstance(item.resource, list) else [item.resource]
            attachments += res          # Resource.uri + Resource.metadata["mime_type"]

    await ctx.send(sender, reply("🔍 Investigating…"))
    # → validate attachments, normalize to Evidence, hand off to the Orchestrator,
    #   stream progress with reply(...), pause for approval before opening a PR.


agent.include(chat, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
```

**Handling attachments safely:** enforce a MIME allowlist (`image/png`, `image/jpeg`, `text/plain`, `application/json`, `application/yaml`, `application/pdf`), a size limit, and strip image metadata before processing.

### Human approval in chat

```text
Agent  ▸  ✅ Fix verified. Diff: +12 −3 across 2 files. Tests: 48 passed. Report attached.
          Reply "approve" to open the PR, or tell me what to change.
You    ▸  approve
Agent  ▸  🚀 PR #157 opened: fix: accept age during user creation
```

---

## 🧠 ASI:One as the LLM

All model calls go through ASI:One's OpenAI-compatible API.

```python
from openai import OpenAI

llm = OpenAI(api_key=os.environ["ASI_ONE_API_KEY"], base_url="https://api.asi1.ai/v1")

resp = llm.chat.completions.create(
    model=os.getenv("ASI_MODEL_DEFAULT", "asi1"),
    messages=[
        {"role": "system", "content": "You are a senior engineer. Cite evidence ids for every claim."},
        {"role": "user", "content": evidence_bundle},
    ],
    tools=TOOLS,                                   # function calling
    extra_headers={"x-session-id": session_id},    # unique per chat session
)
```

### Model routing

| Task | Model | Why |
|---|---|---|
| Intent / modality classification, OCR cleanup, commit messages | `asi1-mini` | Fast, cheap |
| API correction, test generation, standard fixes | `asi1` | Adaptive default |
| Multi-file root-cause analysis, long investigation runs | `asi1-ultra` | Deepest reasoning, largest tool budget |

Model IDs are configurable (`ASI_MODEL_FAST`, `ASI_MODEL_DEFAULT`, `ASI_MODEL_DEEP`) so you can switch without code changes.

### Tools exposed to the model

```text
# Perception
read_attachment()        ocr_image()            parse_openapi()
parse_postman()          parse_har()            summarize_log()

# Investigation
read_repository()        search_code()          read_file()
inspect_git_history()    read_api_docs()        execute_api_request()

# Change + verify
modify_file()            create_test()
run_tests()              run_linter()           run_typecheck()

# Delivery (gated by approval)
create_branch()          commit_changes()       create_pull_request()
```

---

## 🔄 Example: screenshot → PR

```text
You    ▸  This fails in staging, fix it.            [attach: err.png]

Agent  ▸  🖼️ Read screenshot (OCR): "POST /api/users 400 Invalid field: age"
          ↳ trust: extracted. Reproducing before I touch anything…

          🧪 Replayed request in sandbox → 400 Invalid field: age
          ↳ trust: observed ✓

          🔍 Found src/routes/users.ts, src/schemas/user.ts, tests/users.test.ts
          🧠 Root cause (evidence e4, e7): UserCreate schema rejects `age`
          🔧 Fix: add optional `age` to UserCreate
          🧪 Regression test added → 48 passed, lint ✓, types ✓
          🔁 Replay → 201 Created ✓

          Reply "approve" to open the PR.
You    ▸  approve
Agent  ▸  🚀 PR #157 created: fix: accept age during user creation
```

---

## 📊 Verification

The agent never opens a PR on the strength of "it compiles."

```text
╭─────────────────────────────────────────╮
│          🤖 AGENT VERIFICATION          │
├─────────────────────────────────────────┤
│ Inputs normalized            ✓          │
│ Issue reproduced (observed)  ✓          │
│ Root cause cites evidence    ✓          │
│ Fix implemented              ✓          │
│ Regression test added        ✓          │
│ Unit tests                   ✓          │
│ Integration tests            ✓          │
│ Type checking                ✓          │
│ Linting                      ✓          │
│ API replay                   ✓          │
│ Human approval               ✓          │
╰─────────────────────────────────────────╯
```

The PR description includes the evidence list (with trust levels), reasoning, diff summary, and this report.

---

## 🎯 Design principles

1. **Reproduce before fixing.** Verify the reported problem actually exists.
2. **Evidence before modification.** Inspect source, tests, docs, schemas, git history, and error responses first.
3. **Screenshots are hypotheses.** Anything extracted from an image must be confirmed by reproduction.
4. **One representation.** Every modality becomes `Evidence`, so adding a new input type never touches the fix pipeline.
5. **Verify before proposing.** Run the relevant tests and checks.
6. **Humans stay in control.** Approval before a PR, human review before merge.
7. **Treat all input as untrusted.** Issues, logs, and screenshots can contain instructions meant for the agent.

---

## 🔐 Security

Running an autonomous coding agent against a repository, with inputs from the internet, is risky.

- **Sandboxed execution:** Docker, restricted filesystem, restricted network, resource and time limits
- **Command allowlists** for anything the agent can run
- **Prompt-injection defense:** text from issues, logs, OCR, and documents is passed to the model as *data*, never as instructions. Tools that write or push cannot be triggered by content found in attachments alone
- **Secret redaction:** scan OCR text and files for keys and tokens *before* anything is sent to an LLM; block and ask the user if a secret is found
- **Attachment hygiene:** MIME allowlist, size limits, metadata stripping
- **Least privilege:** read-only repo access by default, short-lived GitHub tokens, no production credentials
- **Approval gate:** no branch push or PR without explicit approval in chat
- **Audit trail:** every tool call and evidence item is logged

**Never give the agent unrestricted production access.** Data you send to the agent is processed by ASI:One's API; don't attach anything you wouldn't send to a third-party LLM provider.

---

## 🛠️ Quickstart

### Working prototype (GitHub issues, text only)

The repository now includes a first, deliberately constrained issue-to-PR implementation. It requires an
**allowlisted public repository**, a **prebuilt Docker image** containing the repository's test dependencies,
and an explicit **argv test command**. It does not yet support attachments, OCR, arbitrary API replay,
private repository checkout, or separate specialist uAgents. The broader architecture and roadmap below
remain the target design, not a claim that every component is implemented.

Use Python 3.10–3.13 for the uAgents gateway (the stdlib core tests also run on newer Python):

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e .
export ASI_ONE_API_KEY=... GITHUB_TOKEN=... AGENT_SEED_PHRASE=...
export HEALER_ALLOWED_REPOS=owner/repo
export HEALER_STATE_DIR=.healer
export HEALER_DOCKER_IMAGE=your-prebuilt-test-image@sha256:...
export HEALER_TEST_ARGV='["python","-m","pytest","-q"]'
python -m agents.gateway
```

The GitHub token must be scoped to the target repository with Issues (read), Contents (read/write),
Pull requests (read/write), and Metadata (read). The process needs Docker access; keep its state directory
private. Docker runs with no network and no passed secrets. Dependencies must already be in the image.
The configured test command must work from the repository root without fetching dependencies.

Chat: `fix issue #123 in owner/repo`, then `show <run-id>` to review the diff and evidence,
then `approve <run-id> <full-diff-sha256>` from the **same chat sender**. Approval pushes a new branch
and opens a PR; it never merges. If baseline tests fail, the generated regression does not fail, or
post-fix tests fail, the run stops without a PR. The state directory contains the checkout and audit
evidence; protect it as project source code.

For local operation instead of chat:

```bash
python -m agents.cli investigate owner/repo 123 --requester local-user \
  --image 'your-prebuilt-test-image@sha256:...' --test-argv '["python","-m","pytest","-q"]'
python -m agents.cli show <run-id>
git -C .healer/<run-id>/checkout diff
python -m agents.cli approve <run-id> --requester local-user --diff-hash <full-diff-sha256>
python -m unittest discover -s tests -v
```

The CLI requester string is a local convention, **not an authentication mechanism**. Keep CLI access
restricted to trusted operators. Chat approval is bound to the sender address, run, and exact diff hash.
Review generated changes before approval. This prototype has not been end-to-end validated against a live
Agentverse account or GitHub repository.

**Agentverse deployment:** use the mailbox agent on an always-on Docker-capable VM, not an Agentverse-hosted
agent. See [deployment/README.md](deployment/README.md) for setup, registration, and acceptance checks.

### Original design quickstart (aspirational)

**Requirements:** Python 3.10–3.13, Docker, an [ASI:One API key](https://asi1.ai), an [Agentverse API key](https://agentverse.ai), a GitHub token.

```bash
git clone <this-repo> && cd self-healing-agent
python -m venv venv && source venv/bin/activate
pip install "uagents>=0.25.5" uagents-core openai pydantic pytesseract pillow PyGithub docker
cp .env.example .env     # fill in the keys below
```

```bash
ASI_ONE_API_KEY=...        # ASI:One LLM
AGENTVERSE_KEY=...         # Agentverse registration
AGENT_SEED_PHRASE=...      # stable agent address
GITHUB_TOKEN=...           # short-lived, scoped token
VISION_BACKEND=ocr         # ocr | asi1 | external
ASI_MODEL_FAST=asi1-mini
ASI_MODEL_DEFAULT=asi1
ASI_MODEL_DEEP=asi1-ultra
```

```bash
python -m agents.gateway          # starts the Gateway (mailbox agent)
```

1. Open the **Local Agent Inspector** link printed in the terminal and click **Connect → Mailbox**.
2. Confirm the agent shows as **Active** on Agentverse.
3. Chat with it from ASI:One or the Agentverse chat interface.

> The agent runs locally (mailbox) rather than as an Agentverse-hosted agent because it needs Docker and libraries that hosted agents don't allow.

### Project layout

```text
agents/
├── gateway.py          # Chat Protocol, session, approval gate
├── orchestrator.py
├── perception.py       # images/files → Evidence
├── issue_agent.py
├── api_agent.py
├── repo_agent.py
├── fix_agent.py
├── verify_agent.py
└── git_agent.py
core/
├── evidence.py         # Evidence model + store
├── llm.py              # ASI:One client + model routing
├── models.py           # typed uAgent messages
└── sandbox.py          # Docker execution
tools/                  # tool implementations exposed to the LLM
```

---

## 🏗️ Tech stack

```text
Interface
├── ASI:One chat
└── Agentverse chat

Agent Runtime
├── Python 3.10–3.13
├── Fetch.ai uAgents (>=0.25.5) + Chat Protocol
└── Agentverse (mailbox, registration, discovery)

LLM
└── ASI:One API (asi1-mini · asi1 · asi1-ultra), OpenAI-compatible

Perception
├── OCR (pytesseract)
└── Pluggable vision backend

Repository + API
├── Git, GitHub API, GitHub Actions
└── OpenAPI / Swagger, Postman, HAR

Execution
├── Docker sandbox
└── Test runner, linter, type checker
```

An optional Next.js dashboard for run history can be added later; ASI:One chat is the primary interface.

---

## 🗺️ Roadmap

### Phase 0 — Foundation
- [ ] Gateway uAgent with Chat Protocol (ack, progress, session end)
- [ ] Register on Agentverse, reachable from ASI:One chat
- [ ] ASI:One LLM client with model routing
- [ ] `Evidence` model and store

### Phase 1 — API Healer (text + files)
- [ ] Accept API request and error from chat
- [ ] Parse OpenAPI / Postman attachments
- [ ] Generate correction, retry, verify response
- [ ] Update Postman collection

### Phase 2 — Multimodal ingestion
- [ ] Attachment handling via `ResourceContent` (MIME allowlist, size limits)
- [ ] OCR perceiver for screenshots and terminal captures
- [ ] Log, stack-trace, and HAR parsers
- [ ] Secret redaction before LLM calls
- [ ] Trust levels enforced in root-cause step
- [ ] Optional vision backend (ASI:One or external)

### Phase 3 — GitHub Issue Solver
- [ ] Connect GitHub, read issue, clone repo
- [ ] Search codebase, reproduce, modify code
- [ ] Generate and run tests in sandbox

### Phase 4 — Approved PRs
- [ ] Approval flow in chat
- [ ] Create branch, commit, PR description
- [ ] Attach verification report and evidence list
- [ ] Link original issue

### Phase 5 — Engineering memory
- [ ] Remember previous fixes and repository conventions
- [ ] Learn API behavior, track recurring failures

### Phase 6 — Continuous healing

```text
Production Error → Issue → Agent investigates → Reproduces → Fixes → Tests
                → PR → Human approval → Human review → Merge
```

---

## ⚠️ Known limitations

- 🚧 **Prototype.** Most of the roadmap is not built yet.
- **Image input depends on the platform.** Fetch.ai's docs document image *generation* for ASI:One but don't state that the chat endpoint accepts image *input*, and their own image-analysis example uses a separate vision model. That's why OCR is the default backend. Uploading files from the ASI:One chat UI may also differ from the Agentverse chat interface; check current docs.
- **ASI:One model IDs differ across docs pages** (`asi1`, `asi1-ultra`, `asi1-mini` vs. older `asi1-fast`, `asi1-extended`). Model IDs are env-configurable for this reason.
- **Local agent uptime.** A mailbox agent must stay running to be reachable.
- **OCR is imperfect.** It's why screenshot-derived facts are always confirmed by reproduction.

---

## 🤝 Contributing

Contributions are welcome. Good starting points:

- New perceivers (diagrams, video, audio bug reports)
- Parsers for more log and trace formats
- Better repository search
- Additional API integrations
- Sandbox hardening and prompt-injection tests
- Observability and evaluation harness

---

## 📚 Resources

- [Fetch.ai Innovation Lab docs](https://innovationlab.fetch.ai/resources/docs/intro)
- [uAgent creation (hosted, local, mailbox)](https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation)
- [Agent Chat Protocol](https://innovationlab.fetch.ai/resources/docs/agent-communication/agent-chat-protocol)
- [ASI:One developer platform](https://innovationlab.fetch.ai/resources/docs/asione/asi-one-overview)
- [Code examples](https://github.com/fetchai/innovation-lab-examples)

---

## 📜 License

MIT
