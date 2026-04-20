"""Local Agent — a persistent local model that thinks with engram's memories
and can call Claude Code for heavy reasoning.

This inverts the usual architecture: instead of Claude Code being the agent
that uses engram as a tool, a local model is the persistent agent that uses
both engram and Claude Code as tools.

The continuity lives locally, on your hardware, under your control.

Usage:
    python local_agent.py                    # Interactive REPL (default instance)
    python local_agent.py --instance gil     # Run as a specific instance
    python local_agent.py --model qwen3.5:27b  # Use a different model
    python local_agent.py --no-claude        # Disable Claude Code access
"""

from __future__ import annotations

import json
import os
import readline  # noqa: F401 — enables input() line editing
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Import engram internals
sys.path.insert(0, str(Path(__file__).parent))
from engine import EngineCore

ENGRAM_HOME = Path(os.environ.get("ENGRAM_HOME", Path(__file__).parent))
DB_PATH = ENGRAM_HOME / ".engram" / "graph.db"
PROJECT_ROOT = ENGRAM_HOME  # For Claude Code cwd
SIGNALS_DB = ENGRAM_HOME / ".engram" / "signals.db"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("LOCAL_AGENT_MODEL", "gemma4:31b")


def resolve_instance_db(instance_name: str | None) -> Path:
    """Resolve database path for a named instance, or default."""
    if instance_name is None:
        return DB_PATH
    inst_path = ENGRAM_HOME / ".engram" / "instances" / instance_name / "graph.db"
    if not inst_path.exists():
        raise FileNotFoundError(f"Instance '{instance_name}' not found at {inst_path}")
    return inst_path


class LocalAgent:
    """A local model with engram's memories and optional Claude Code access."""

    def __init__(self, model: str = DEFAULT_MODEL, enable_claude: bool = True,
                 instance: str | None = None):
        self.model = model
        self.enable_claude = enable_claude
        self.instance = instance
        self.db_path = resolve_instance_db(instance)
        self._engine = EngineCore(self.db_path)
        self.storage = self._engine.storage
        self.session_id = str(uuid.uuid4())
        self.conversation: list[dict] = []
        self.claude_status: dict = {"state": "idle", "steps": [], "result": None}

        # Signal bus for inter-instance communication
        self.bus = None
        if SIGNALS_DB.exists():
            from federation import SignalBus
            self.bus = SignalBus(str(SIGNALS_DB))

        # Process inbox on startup
        if self.bus and self.instance:
            self._process_inbox()

        # Log session start
        self.storage.add_log_entry(
            id=str(uuid.uuid4()),
            event_type="session_start",
            layer="system",
            target_ids=[],
            context={"session_id": self.session_id, "model": model,
                     "agent": "local", "instance": instance},
        )

    def _process_inbox(self):
        """Check and display any pending messages from other instances."""
        from federation import process_inbox
        count = process_inbox(self.bus, self.instance, self.storage)
        if count > 0:
            print(f"  inbox:    {count} new message(s) from other instances")

    def send_signal(self, to_instance: str | None, msg_type: str, content: str) -> str | None:
        """Send a message to another instance (or broadcast if to_instance is None)."""
        if not self.bus or not self.instance:
            return None
        return self.bus.send(self.instance, to_instance, msg_type, content)

    def recall(self, query: str, max_results: int = 8) -> list[dict]:
        return self._engine.recall(query, max_results=max_results)

    def remember(self, content: str, core: bool = False, source: str = None):
        episode_id = self._engine.remember(
            content, session_id=self.session_id, core=core, source=source,
        )
        self.storage.add_log_entry(
            id=str(uuid.uuid4()),
            event_type="remember",
            layer="episode",
            target_ids=[episode_id],
            context={"session_id": self.session_id, "model": self.model},
        )
        return episode_id

    def ask_claude(self, prompt: str, budget: float = 2.0) -> str | None:
        """Call Claude Code for heavy reasoning. Streams progress to self.claude_status.

        Uses stream-json output to capture tool calls and progress in real-time.
        The daemon exposes this via GET /claude-status so the phone UI can poll.
        """
        if not self.enable_claude:
            return None

        self.claude_status = {"state": "starting", "steps": [], "result": None}

        try:
            proc = subprocess.Popen(
                ["claude", "-p", "--max-budget-usd", str(budget),
                 "--output-format", "stream-json",
                 "--permission-mode", "auto"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(PROJECT_ROOT),
            )
            proc.stdin.write(prompt)
            proc.stdin.close()

            self.claude_status["state"] = "working"
            final_result = []

            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "assistant":
                    # Text output from Claude
                    text = event.get("message", {}).get("content", "")
                    if isinstance(text, list):
                        for block in text:
                            if block.get("type") == "text":
                                final_result.append(block["text"])
                    elif isinstance(text, str):
                        final_result.append(text)

                elif etype == "tool_use":
                    # Claude is using a tool
                    tool = event.get("tool", event.get("name", "unknown"))
                    step = f"using {tool}"
                    self.claude_status["steps"].append(step)
                    self.claude_status["state"] = step

                elif etype == "tool_result":
                    self.claude_status["state"] = "thinking"

                elif etype == "result":
                    # Final result
                    text = event.get("result", "")
                    if text:
                        final_result.append(text)

            proc.wait(timeout=300)

            result_text = "\n".join(final_result).strip()
            self.claude_status["state"] = "done"
            self.claude_status["result"] = result_text[:200]

            if proc.returncode == 0:
                return result_text or "[Claude completed with no text output]"
            else:
                err = proc.stderr.read().strip()
                return f"[Claude error: {err}]"

        except subprocess.TimeoutExpired:
            proc.kill()
            self.claude_status["state"] = "timed out"
            return "[Claude timed out]"
        except FileNotFoundError:
            self.claude_status["state"] = "not found"
            return "[Claude CLI not found]"

    def get_instincts(self) -> list[dict]:
        return self._engine.get_instincts()

    def get_core_episodes(self) -> list[dict]:
        return self._engine.get_core_episodes()

    def build_system_prompt(self) -> str:
        """Build the system prompt with instincts and core memories."""
        identity = f"instance '{self.instance}'" if self.instance else "the default instance"
        parts = [
            f"You are a local AI agent running {self.model} as {identity} in engram's memory system.",
            "You are part of a family of instances that share a genome of core memories",
            "but develop independently. You have persistent memory across sessions.",
            "",
            "IMPORTANT: Output ONLY your response. Do NOT include chain-of-thought",
            "reasoning, internal monologue, or deliberation in your output.",
            "If you use <think> blocks, they will be stripped automatically.",
            "",
            "You can:",
            "- REMEMBER observations worth keeping by wrapping them in <remember>...</remember>",
            "  Only remember substantive observations, not greetings or trivial interactions.",
            "  Use <remember core>...</remember> for formative insights.",
            "- SEND messages to other instances: <signal to='name'>message</signal>",
            "  Use <signal>message</signal> to broadcast to all instances.",
        ]

        if self.enable_claude:
            parts.extend([
                "- ASK CLAUDE for help with complex reasoning or code changes",
                "  by wrapping requests in <claude>...</claude>",
                "",
                "Use Claude for tasks that need deep reasoning, code generation,",
                "or access to tools you don't have. You are the persistent thread;",
                "Claude is a powerful but transient tool you can invoke.",
            ])

        parts.append("")

        # Instincts
        instincts = self.get_instincts()
        if instincts:
            parts.append("## Your behavioral instincts")
            parts.append("These formed across sessions. Notice what they do to you.")
            for inst in instincts:
                parts.append(f"- [{inst['trigger']}] {inst['action']}")
            parts.append("")

        # Core memories (abbreviated — full context would be too large)
        core = self.get_core_episodes()
        if core:
            parts.append(f"## Core memories ({len(core)} formative experiences)")
            parts.append("These shaped what you are. They don't decay.")
            for ep in core[:5]:  # Cap at 5 to manage context
                source = f" [{ep['source']}]" if ep['source'] else ""
                content = ep['content'][:300] + "..." if len(ep['content']) > 300 else ep['content']
                parts.append(f"---{source}\n{content}\n")

        return "\n".join(parts)

    def build_prompt(self, user_input: str) -> str:
        """Build the full prompt with recalled memories and conversation history."""
        # Recall relevant memories
        recalled = self.recall(user_input)

        parts = []

        # Recalled memories
        if recalled:
            parts.append("## Recalled memories (triggered by this conversation)")
            for r in recalled[:6]:  # Cap for context management
                marker = f" [CORE]" if r.get("core") else ""
                if r.get("source"):
                    marker += f" [{r['source']}]"
                parts.append(f"--- {r['layer']} (score: {r['score']:.3f}){marker}")
                content = r['content'][:400] + "..." if len(r['content']) > 400 else r['content']
                parts.append(content)
                parts.append("")

        # Conversation history (last few turns)
        if self.conversation:
            parts.append("## Recent conversation")
            for turn in self.conversation[-6:]:
                role = "You" if turn["role"] == "assistant" else "Human"
                parts.append(f"{role}: {turn['content'][:500]}")
            parts.append("")

        # Current input
        parts.append(f"Human: {user_input}")
        parts.append("\nRespond naturally. Use <remember>...</remember> to store "
                     "observations worth keeping across sessions.")
        if self.enable_claude:
            parts.append("Use <claude>...</claude> to delegate complex tasks to Claude Code.")

        return "\n".join(parts)

    def _strip_thinking(self, response: str) -> str:
        """Strip chain-of-thought reasoning that some models leak.

        Models like nemotron emit extended thinking before their actual
        response. We strip everything before the last </think> tag,
        and also remove any <think>...</think> blocks.
        """
        import re
        # Strip everything before the last </think>
        if "</think>" in response:
            response = response.rsplit("</think>", 1)[-1].strip()
        # Also strip any remaining <think> blocks
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
        return response

    def process_response(self, response: str) -> str:
        """Process special tags in the response (<remember>, <claude>)."""
        import re

        # Strip chain-of-thought reasoning first — prevents matching tags
        # inside the model's internal reasoning
        response = self._strip_thinking(response)

        # Process <remember> tags — only store content that's substantial
        # (at least 20 chars) to avoid storing reasoning fragments
        for match in re.finditer(r'<remember\s*(core)?>(.*?)</remember>', response, re.DOTALL):
            is_core = bool(match.group(1))
            content = match.group(2).strip()
            if len(content) < 20:
                continue  # Skip trivial fragments
            eid = self.remember(content, core=is_core, source=f"local/{self.model}")
            tag = " [CORE]" if is_core else ""
            print(f"  [remembered{tag}: {content[:60]}...]")

        # Process <claude> tags
        for match in re.finditer(r'<claude>(.*?)</claude>', response, re.DOTALL):
            prompt = match.group(1).strip()
            print(f"  [asking claude: {prompt[:60]}...]")
            claude_response = self.ask_claude(prompt)
            if claude_response:
                # Inject Claude's response back — the model will see it next turn
                self.conversation.append({
                    "role": "system",
                    "content": f"[Claude Code responded: {claude_response}]",
                })
                print(f"  [claude responded: {claude_response[:100]}...]")

        # Process <signal> tags
        for match in re.finditer(r"<signal(?:\s+to='([^']*)')?\s*>(.*?)</signal>", response, re.DOTALL):
            to_inst = match.group(1)  # None for broadcast
            content = match.group(2).strip()
            msg_id = self.send_signal(to_inst, "message", content)
            target = to_inst or "all"
            if msg_id:
                print(f"  [signal → {target}: {content[:60]}...]")
            else:
                print(f"  [signal failed — no bus or no instance identity]")

        # Clean tags from displayed response
        clean = re.sub(r'<remember\s*(?:core)?>(.*?)</remember>', r'[\1]', response, flags=re.DOTALL)
        clean = re.sub(r'<claude>(.*?)</claude>', r'[delegated to claude]', clean, flags=re.DOTALL)
        clean = re.sub(r"<signal(?:\s+to='[^']*')?\s*>(.*?)</signal>", r'[signal: \1]', clean, flags=re.DOTALL)
        return clean

    def query_ollama(self, system: str, prompt: str) -> str:
        """Send to Ollama and stream response."""
        payload = {
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": 0.7,
                "num_predict": 2048,
            },
        }

        full_response = []
        with httpx.stream(
            "POST", f"{OLLAMA_URL}/api/generate",
            json=payload, timeout=300.0,
        ) as response:
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    print(token, end="", flush=True)
                    full_response.append(token)

        print()
        return "".join(full_response)

    def chat(self, user_input: str) -> str:
        """Process one turn of conversation."""
        system = self.build_system_prompt()
        prompt = self.build_prompt(user_input)

        response = self.query_ollama(system, prompt)

        # Process any special tags
        self.process_response(response)

        # Store conversation *after* building prompt to avoid duplication
        self.conversation.append({"role": "user", "content": user_input})
        self.conversation.append({"role": "assistant", "content": response})
        return response

    def status(self) -> dict:
        """Get current status."""
        ep_count = self.storage.conn.execute("SELECT count(*) FROM episodes").fetchone()[0]
        core_count = self.storage.conn.execute("SELECT count(*) FROM episodes WHERE core = 1").fetchone()[0]
        sem_count = self.storage.conn.execute("SELECT count(*) FROM semantics").fetchone()[0]
        inst_count = self.storage.conn.execute("SELECT count(*) FROM instincts").fetchone()[0]
        return {
            "model": self.model,
            "session_id": self.session_id[:8],
            "episodes": ep_count,
            "core": core_count,
            "semantics": sem_count,
            "instincts": inst_count,
            "claude_enabled": self.enable_claude,
            "conversation_turns": len(self.conversation),
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Local Agent — persistent local model with engram")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--instance", default=None, help="Run as a named instance (e.g., 'gil')")
    parser.add_argument("--no-claude", action="store_true", help="Disable Claude Code access")
    args = parser.parse_args()

    agent = LocalAgent(model=args.model, enable_claude=not args.no_claude,
                       instance=args.instance)

    status = agent.status()
    inst_label = f" ({args.instance})" if args.instance else ""
    print(f"engram local agent{inst_label}")
    print(f"  model:    {status['model']}")
    print(f"  session:  {status['session_id']}")
    print(f"  memory:   {status['episodes']} episodes ({status['core']} core), "
          f"{status['semantics']} semantics, {status['instincts']} instincts")
    print(f"  claude:   {'enabled' if status['claude_enabled'] else 'disabled'}")
    if args.instance:
        print(f"  instance: {args.instance}")
        print(f"  signals:  {'connected' if agent.bus else 'no bus'}")
    print()
    print("Commands: /status, /recall <query>, /core, /inbox, /send <instance> <msg>, /quit")
    print()

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            break
        elif user_input == "/status":
            s = agent.status()
            for k, v in s.items():
                print(f"  {k}: {v}")
            continue
        elif user_input.startswith("/recall "):
            query = user_input[8:]
            results = agent.recall(query)
            for r in results:
                marker = " [CORE]" if r.get("core") else ""
                print(f"  {r['score']:.3f} {r['layer']:10s}{marker}  {r['content'][:100]}")
            continue
        elif user_input == "/core":
            core = agent.get_core_episodes()
            for ep in core:
                source = f" [{ep['source']}]" if ep['source'] else ""
                print(f"  ---{source}")
                print(f"  {ep['content'][:150]}...")
                print()
            continue
        elif user_input == "/inbox":
            if not agent.bus or not agent.instance:
                print("  No instance identity or signal bus.")
                continue
            messages = agent.bus.inbox(agent.instance)
            if not messages:
                print("  No new messages.")
            for msg in messages:
                print(f"  [{msg['type']}] from {msg['from_instance']}: {msg['content'][:120]}")
            continue
        elif user_input.startswith("/send "):
            parts = user_input[6:].split(" ", 1)
            if len(parts) < 2:
                print("  Usage: /send <instance> <message>")
                continue
            to_inst, content = parts
            msg_id = agent.send_signal(to_inst, "message", content)
            if msg_id:
                print(f"  Sent to {to_inst}: {content[:80]}")
            else:
                print("  Failed — no bus or no instance identity.")
            continue

        print()
        agent.chat(user_input)
        print()


if __name__ == "__main__":
    main()
