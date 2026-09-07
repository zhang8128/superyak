"""Ask — thin CLI client for the engram daemon.

Usage:
    python ask.py hello                         # Send a message
    python ask.py "what do you remember"        # Quoted messages
    python ask.py --status                      # Check daemon status
    python ask.py --recall "ostrom commons"     # Search memories
    python ask.py --core                        # List core memories
    python ask.py --remember "observation"      # Store a memory
    python ask.py --remember-core "insight"     # Store a core memory
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

DEFAULT_URL = "http://127.0.0.1:7432"


def main():
    parser = argparse.ArgumentParser(description="Ask the engram daemon")
    parser.add_argument("message", nargs="*", help="Message to send")
    parser.add_argument("--url", default=DEFAULT_URL, help="Daemon URL")
    parser.add_argument("--status", action="store_true", help="Show daemon status")
    parser.add_argument("--recall", metavar="QUERY", help="Search memories")
    parser.add_argument("--core", action="store_true", help="List core memories")
    parser.add_argument("--remember", metavar="TEXT", help="Store a memory")
    parser.add_argument("--remember-core", metavar="TEXT", help="Store a core memory")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    url = args.url

    try:
        if args.status:
            r = httpx.get(f"{url}/status", timeout=5.0)
            data = r.json()
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                for k, v in data.items():
                    print(f"  {k}: {v}")

        elif args.recall:
            r = httpx.get(f"{url}/recall", params={"q": args.recall}, timeout=30.0)
            data = r.json()
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                for result in data.get("results", []):
                    core = " [CORE]" if result.get("core") else ""
                    print(f"  {result['score']:.3f} {result['layer']:10s}{core}  "
                          f"{result['content'][:100]}")

        elif args.core:
            r = httpx.get(f"{url}/core", timeout=5.0)
            data = r.json()
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                print(f"{data['count']} core memories:")
                for ep in data.get("episodes", []):
                    source = f" [{ep['source']}]" if ep.get("source") else ""
                    print(f"  ---{source}")
                    print(f"  {ep['content'][:150]}...")
                    print()

        elif args.remember:
            r = httpx.post(f"{url}/remember", json={"content": args.remember}, timeout=5.0)
            data = r.json()
            print(f"  stored: {data.get('episode_id', '?')[:8]}")

        elif args.remember_core:
            r = httpx.post(f"{url}/remember",
                          json={"content": args.remember_core, "core": True}, timeout=5.0)
            data = r.json()
            print(f"  stored [CORE]: {data.get('episode_id', '?')[:8]}")

        elif args.message:
            message = " ".join(args.message)
            r = httpx.post(f"{url}/chat", json={"message": message}, timeout=300.0)
            data = r.json()
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                print(data.get("response", data.get("error", "no response")))

        else:
            parser.print_help()

    except httpx.ConnectError:
        print("error: can't connect to daemon. Start it with: uv run python daemon.py",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
