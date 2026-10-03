#!/usr/bin/env python3
"""Stand-in for engram/cli.py in team tests: same commands and JSON output, no engram."""
import json
import os
import sys
from pathlib import Path

home = Path(os.environ["ENGRAM_HOME"]) / ".engram"
args = sys.argv[1:]
log = home / "calls.jsonl"
home.mkdir(parents=True, exist_ok=True)
with open(log, "a") as f:
    f.write(json.dumps(args) + "\n")
if os.environ.get("FAKE_ENGRAM_FAIL") == args[0]:
    print(json.dumps({"error": "boom"}))
    sys.exit(1)
if args[0] == "agent-create":
    db = home / "instances" / args[1] / "graph.db"
    created = not db.exists()
    db.parent.mkdir(parents=True, exist_ok=True)
    db.touch()
    print(json.dumps({"instance": args[1], "path": str(db), "created": created, "seed": args[3]}))
elif args[0] == "house-init":
    db = home / "instances" / "lighthouse" / "graph.db"
    created = not db.exists()
    db.parent.mkdir(parents=True, exist_ok=True)
    db.touch()
    print(json.dumps({"path": str(db), "created": created}))
elif args[0] == "shared":
    opts = dict(zip(args[1::2], args[2::2]))
    p = home / "shares.json"
    shares = json.loads(p.read_text()) if p.exists() else []
    shares = [s for s in shares if s["audience"] == opts["--audience"]
              and s["shared_at"] > opts.get("--after", "")
              and all(t.lower() in s["content"].lower() for t in opts.get("--query", "").split())]
    print(json.dumps({"shares": shares[:int(opts.get("--limit", 20))]}))
else:
    print(json.dumps({"error": "unknown command"}))
    sys.exit(2)
