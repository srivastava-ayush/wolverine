"""ASI:One Chat Protocol entry point. Approval is tied to sender and full diff hash."""
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agents.orchestrator import Orchestrator
from core.security import git, redact
from core.state import Store


def parse_command(text: str, agent_address: str | None = None):
    """Accept a plain command, an issue URL, or a pasted Markdown command."""
    text = text.strip()
    # ASI:One addresses direct agent chats by prepending @<our agent address>.
    # Strip only our own address. In particular, do not permit arbitrary prose
    # around an approval command.
    if agent_address:
        target = re.match(r"^@([a-z0-9]+)[:：]?\s+", text, re.I)
        if target and target[1] == agent_address:
            text = text[target.end():].strip()
    if text.startswith("```") and text.endswith("```"):
        text = re.sub(r"^```(?:text)?\s*", "", text, flags=re.I).removesuffix("```").strip()
    text = text.strip("`\"'“” ").rstrip(".! ")
    issue = re.fullmatch(r"fix\s+issue\s+#?(\d+)\s+in\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text, re.I)
    if issue:
        return "fix", issue[2], int(issue[1])
    url = re.fullmatch(r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/(\d+)/?", text, re.I)
    if url:
        return "fix", url[1], int(url[2])
    # ASI:One sometimes wraps the user's request in explanatory prose before
    # forwarding it. Only allow this loose matching for investigation, never
    # for show/approve, which remain exact and identity-bound.
    embedded = re.findall(r"\bfix\s+issue\s+#?(\d+)\s+in\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text, re.I)
    urls = re.findall(r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/(\d+)", text, re.I)
    candidates = {(repo, int(number)) for number, repo in embedded} | {(repo, int(number)) for repo, number in urls}
    if len(candidates) == 1:
        repo, number = candidates.pop()
        return "fix", repo, number
    approval = re.fullmatch(r"approve\s+([0-9a-f]{32})\s+([0-9a-f]{64})", text, re.I)
    if approval:
        return "approve", approval[1], approval[2]
    inspection = re.fullmatch(r"show\s+([0-9a-f]{32})", text, re.I)
    if inspection:
        return "show", inspection[1]
    # ASI:One may forward a read-only inspection inside extra prose. Access is
    # still restricted to the original sender in the handler below.
    inspections = set(re.findall(r"\bshow\s+([0-9a-f]{32})\b", text, re.I))
    if len(inspections) == 1:
        return "show", inspections.pop()
    return None


def create_agent():
    from uagents import Agent, Protocol
    from uagents_core.contrib.protocols.chat import (
        ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec,
    )

    store = Store(Path(os.getenv("HEALER_STATE_DIR", ".healer")))
    agent = Agent(name="self-healing-engineer", seed=os.environ["AGENT_SEED_PHRASE"],
                  port=8000, mailbox=True, publish_agent_details=True,
                  readme_path=str(Path(__file__).resolve().parent.parent / "AGENTVERSE.md"),
                  handle_messages_concurrently=True)
    chat = Protocol(spec=chat_protocol_spec)

    def reply(text):
        return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                           content=[TextContent(type="text", text=text)])

    @chat.on_message(ChatMessage)
    async def on_chat(ctx, sender: str, msg):
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc),
                                                   acknowledged_msg_id=msg.msg_id))
        text = " ".join(item.text for item in msg.content if isinstance(item, TextContent)).strip()
        if not text:
            ctx.logger.info("Received a ChatMessage without TextContent; acknowledged without processing")
            return
        command = parse_command(text, agent.address)
        try:
            if command and command[0] == "fix":
                argv = json.loads(os.environ["HEALER_TEST_ARGV"])
                image = os.environ["HEALER_DOCKER_IMAGE"]
                await ctx.send(sender, reply("Investigating in an isolated checkout. I will not publish without your approval."))
                run = await asyncio.to_thread(Orchestrator(store).investigate, command[1], command[2], sender, argv, image)
                if run.status == "awaiting_approval":
                    await ctx.send(sender, reply(
                        f"Run {run.id}: regression failed, configured tests now pass.\n"
                        f"Reason: {run.summary}\nDiff SHA-256: {run.diff_hash}\n"
                        f"Send `show {run.id}` to inspect the diff and evidence. "
                        f"Reply `approve {run.id} {run.diff_hash}` to open a PR."))
                else:
                    await ctx.send(sender, reply(f"Run {run.id} failed: {run.error}"))
            elif command and command[0] == "approve":
                run = await asyncio.to_thread(Orchestrator(store).approve, command[1], sender, command[2])
                await ctx.send(sender, reply(f"PR opened: {run.pr_url}"))
            elif command and command[0] == "show":
                run = store.load(command[1])
                if run.requester != sender or run.status != "awaiting_approval":
                    raise ValueError("No proposal available for this sender")
                diff = git(store.directory(run.id) / "checkout", "diff", "HEAD", "--", ".")
                if len(diff) > 18000:
                    raise ValueError("Diff too long for chat; review locally with healer show")
                report = "\n".join(f"{e.id} {e.trust}: {e.content[:600]}" for e in run.evidence)
                await ctx.send(sender, reply(redact(f"Evidence:\n{report}\n\nProposed diff:\n{diff}\n\nApprove with `approve {run.id} {run.diff_hash}`")))
            else:
                ctx.logger.info("Unrecognized chat command (length=%d, content_types=%s)",
                                len(text), [type(item).__name__ for item in msg.content])
                contains_command = bool(re.search(r"fix\s+issue", text, re.I))
                contains_url = "github.com/" in text and "/issues/" in text
                hint = f"Received {len(text)} characters; issue command present: {contains_command}; GitHub issue URL present: {contains_url}."
                await ctx.send(sender, reply(f"I couldn't recognize the request. {hint} Send `fix issue #2 in srivastava-ayush/drawz` in this agent chat."))
        except Exception as exc:
            await ctx.send(sender, reply(f"Unable to proceed: {redact(str(exc))[:500]}"))

    @chat.on_message(ChatAcknowledgement)
    async def on_acknowledgement(ctx, sender: str, msg):
        # Chat replies receive acknowledgements too; do not answer an ack with
        # another ChatMessage or the participants will loop indefinitely.
        ctx.logger.debug("Chat message acknowledged by %s", sender)

    agent.include(chat, publish_manifest=True)
    return agent


if __name__ == "__main__":
    create_agent().run()
