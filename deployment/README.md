# Agentverse deployment: mailbox agent on a worker host

**Deployment model:** Agentverse is the registration, discovery, mailbox, and ASI:One chat surface.
`agents.gateway` and the Docker test runner live on your always-on Linux VM. Do **not** paste the whole
application into an Agentverse hosted-agent editor: hosted agents do not provide this application's
Git checkout, persistent filesystem, or Docker execution. A hosted, chat-only front end with a separately
authenticated worker can be built later, but is a different architecture.

## Prerequisites

1. A Linux VM with Python **3.10–3.13**, Git, Docker daemon, outbound HTTPS to Agentverse, ASI:One,
   GitHub, and Docker registry. Tests themselves run with Docker `--network none`.
2. A dedicated service account with access to Docker and a private, persistent state directory.
   **Docker socket access is effectively root-equivalent:** run this on an isolated VM, not a shared host.
3. A prebuilt, preferably digest-pinned test image with the target repo's dependencies installed.
4. An ASI:One API key, a stable agent seed phrase, and a short-lived GitHub credential scoped to the
   allowlisted repository (Issues read, Contents read/write, PRs read/write, Metadata read).
   Keep credentials in a protected environment file, never in source control or Agentverse profile.
5. An Agentverse account to register the mailbox agent and test ASI:One discovery.

## Start

Install the project into a 3.12 virtual environment on the VM, then set the variables in `.env.example`
plus `HEALER_DOCKER_IMAGE` and `HEALER_TEST_ARGV`. Use a private persistent path for
`HEALER_STATE_DIR` (not `/tmp`). A process supervisor such as systemd should run
`/path/to/.venv/bin/python -m agents.gateway` with the repository as its working directory and restart it
on failure. Ensure the secrets file is readable only by the service account. Keep the same
`AGENT_SEED_PHRASE` across restarts: changing it changes the agent address.

Check the startup logs for mailbox connection, registration, and the local Agent Inspector link. Open
the Inspector and select **Connect → Mailbox**. In Agentverse verify the agent is Active and its profile
and Chat Protocol manifest are visible. `AGENTVERSE.md` is its short marketplace description. An
Agentverse API key is only needed if you choose programmatic registration; it is not required by the
application itself for the Inspector-based mailbox flow.

## Acceptance test

1. From Agentverse chat or ASI:One, send `fix issue #N in owner/repo` for a safe, allowlisted test repo.
2. Confirm acknowledgement, investigation result, run ID, and diff hash arrive in the same chat.
3. Send `show <run-id>` and compare the diff with `git -C <state>/<run-id>/checkout diff HEAD` on the VM.
4. Try an incorrect hash and a different sender; neither may publish a PR.
5. Approve with the original sender and full hash. Check that exactly one branch and PR exist and that
   its evidence/verification report matches the run.
6. Restart the process and confirm the agent reconnects at the **same address**, state remains present,
   and a published run cannot be approved again.

If Docker is unavailable, the run must fail before approval; this machine currently has a Docker client
but **no daemon**, so the end-to-end test must run on a properly configured VM.

## Operations and limits

Monitor process health, Agentverse Active status, mailbox delivery, disk space, Docker availability,
GitHub rate limits, and failed runs. Back up the state directory securely; it contains repository data
and evidence. Rotate GitHub and ASI:One keys without changing the agent seed. Restrict access to the
service account and the Docker daemon. Avoid putting a public HTTP submit endpoint on the VM: mailbox
connectivity uses an outbound channel. A live Agentverse/ASI:One verification is still required before
calling this deployment complete.

References: [uAgent creation and mailbox registration](https://innovationlab.fetch.ai/resources/docs/agent-creation/uagent-creation),
[Chat Protocol](https://innovationlab.fetch.ai/resources/docs/agent-communication/agent-chat-protocol).
