#!/usr/bin/env python3
"""Set up this computer to join the Superyak community: one idempotent script that a
person (or the join-superyak walkthrough in Claude Code) runs step by step.

  python3 scripts/onboard.py check          what is done, what is missing (JSON)
  python3 scripts/onboard.py run [STEP]     do the missing local steps (or one of them)

It only ever creates what is missing: it never overwrites a runtime configuration, a
command wrapper or an MCP registration that already exists, and never touches anyone
else's memory. Network access (Tailscale) and the access code stay with the person:
`superyak-runtime team join <url>` reads the code itself.

Steps: tools, setup, memory, runtime, wrapper, store, claude.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path.home()
RUNTIME_JSON = Path(os.environ.get("SUPERYAK_RUNTIME_CONFIG", HOME / ".config" / "superyak" / "runtime.json"))
WRAPPER = HOME / ".local" / "bin" / "superyak-runtime"
DEFAULT_MEMORY = HOME / "superyak-memory"
DEFAULT_INSTANCE = "main"
ENGRAM_PY = REPO / "engram" / ".venv" / "bin" / "python"
TEAM_ENV = REPO / "team" / ".venv"


def _have(cmd):
    return shutil.which(cmd) is not None


def _run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=kw.pop("timeout", 120), **kw)


def _runtime():
    try:
        return json.loads(RUNTIME_JSON.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def check():
    rt = _runtime() or {}
    memory = Path(rt.get("memory_home", DEFAULT_MEMORY))
    instance = rt.get("default_instance", DEFAULT_INSTANCE)
    linux = platform.system() == "Linux"
    claude_mcp = {}
    if _have("claude"):
        for name in ("engram", "superyak-team"):
            claude_mcp[name] = _run(["claude", "mcp", "get", name], timeout=60).returncode == 0
    tools = {"git": _have("git"), "make": _have("make"), "uv": _have("uv"),
             "python3.11+": sys.version_info >= (3, 11), "claude": _have("claude"),
             "tailscale": _have("tailscale")}
    if linux:
        tools["secret-tool"] = _have("secret-tool")
    steps = {
        "tools": {"done": all(tools.values()), "detail": tools,
                  "fix": "install what is false: uv (https://docs.astral.sh/uv/), Claude Code, "
                         "Tailscale" + (", secret-tool (libsecret)" if linux else "")},
        "setup": {"done": ENGRAM_PY.exists() and TEAM_ENV.exists(),
                  "fix": "onboard.py run setup (make setup-engram setup-team; several minutes)"},
        "memory": {"done": memory.is_dir(), "detail": str(memory)},
        "runtime": {"done": RUNTIME_JSON.exists(), "detail": str(RUNTIME_JSON)},
        "wrapper": {"done": WRAPPER.exists(), "detail": str(WRAPPER),
                    "on_path": str(WRAPPER.parent) in os.environ.get("PATH", "").split(os.pathsep)},
        "store": {"done": (memory / ".engram" / "instances" / instance / "graph.db").is_file(),
                  "detail": "%s/.engram/instances/%s" % (memory, instance)},
        "claude": {"done": bool(claude_mcp) and all(claude_mcp.values()), "detail": claude_mcp},
    }
    team_cfg = Path(os.environ.get("SUPERYAK_TEAM_CONFIG", HOME / ".superyak" / "team" / "config.json"))
    try:
        remote = json.loads(team_cfg.read_text()).get("remote_channels") or {}
    except (OSError, json.JSONDecodeError):
        remote = {}
    return {"repo": str(REPO), "platform": platform.system(), "steps": steps,
            "ready_to_join": all(s["done"] for s in steps.values()),
            "joined": {ch: {"url": c.get("url"), "as": c.get("as")} for ch, c in remote.items()},
            "team_mode_in_checkout": (REPO / "team" / "superyak_team" / "channels.py").exists()}


def run(only=None):
    done = []

    def step(name):
        return only in (None, name)

    if step("setup") and not (ENGRAM_PY.exists() and TEAM_ENV.exists()):
        r = subprocess.run(["make", "setup-engram", "setup-team"], cwd=REPO)   # all that joining needs
        if r.returncode != 0:
            return {"stopped_at": "setup", "did": done, "hint": "make setup-engram setup-team failed; see its output"}
        done.append("setup: installed dependencies")
    rt = _runtime()
    memory = Path((rt or {}).get("memory_home", DEFAULT_MEMORY))
    instance = (rt or {}).get("default_instance", DEFAULT_INSTANCE)
    if step("memory") and not memory.is_dir():
        memory.mkdir(parents=True)
        os.chmod(memory, 0o700)
        done.append("memory: created your memory home %s" % memory)
    if step("runtime") and rt is None:
        RUNTIME_JSON.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_JSON.write_text(json.dumps({"memory_home": str(memory.resolve()),
                                            "default_instance": instance}, indent=2) + "\n")
        done.append("runtime: wrote %s" % RUNTIME_JSON)
    if step("wrapper") and not WRAPPER.exists():
        WRAPPER.parent.mkdir(parents=True, exist_ok=True)
        WRAPPER.write_text("#!/bin/sh\nexec %s %s \"$@\"\n" % (ENGRAM_PY, REPO / "scripts" / "runtime.py"))
        WRAPPER.chmod(0o755)
        done.append("wrapper: installed %s" % WRAPPER)
    if step("store") and not (memory / ".engram" / "instances" / instance / "graph.db").is_file():
        if not ENGRAM_PY.exists():
            return {"stopped_at": "store", "did": done, "hint": "run the setup step first"}
        r = _run([str(ENGRAM_PY), str(REPO / "engram" / "cli.py"), "instance-create", instance],
                 cwd=REPO / "engram", env=dict(os.environ, ENGRAM_HOME=str(memory)))
        if r.returncode != 0:
            return {"stopped_at": "store", "did": done, "hint": r.stdout.strip() or r.stderr.strip()[-300:]}
        done.append("store: created your first memory store '%s'" % instance)
    if step("claude") and _have("claude"):
        regs = {"engram": ["-e", "ENGRAM_HARNESS=claude-code", "engram", "--", str(WRAPPER), "mcp"],
                "superyak-team": ["superyak-team", "--", str(WRAPPER), "team"]}
        for name, args in regs.items():
            if _run(["claude", "mcp", "get", name], timeout=60).returncode != 0:
                r = _run(["claude", "mcp", "add", "-s", "user"] + args, timeout=60)
                done.append("claude: registered %s%s" % (name, "" if r.returncode == 0 else
                                                         " FAILED: " + (r.stderr or r.stdout)[-200:]))
    after = check()
    return {"did": done or ["nothing to do"], "ready_to_join": after["ready_to_join"],
            "missing": [k for k, v in after["steps"].items() if not v["done"]]}


def main(argv):
    if not argv or argv[0] == "check":
        print(json.dumps(check(), indent=1))
        return 0
    if argv[0] == "run":
        print(json.dumps(run(argv[1] if len(argv) > 1 else None), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
