"""Channels: persistent, repo-scoped conversation that works without Slack.

A channel is an append-only log, one JSON record per line, under
~/.superyak/team/channels/<repo-key>/<name>.jsonl. Channels outlive teams: each team writes
to its own `team-<id>` channel (posts, plans, the human's replies), and anyone can open more,
such as `general`. Reading is pull: nothing wakes an agent except a human post that @mentions
it in a team channel, which that team's daemon routes like a Slack reply.

Who writes what:
  - agents (lead, workers): through teamd or the lead's MCP tools; kind "agent" or "plan".
  - the human: the CLI (`superyak-runtime team channels post ...`) or the web page
    (`... channels serve`); kind "human". Sandboxed workers cannot write these files, so they
    cannot pose as the human. The lead runs as the user and could, as it can already message
    workers directly.
"""
import json
import os
import re
import secrets
import time
from pathlib import Path

from . import teamlib

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
DEFAULT_CHANNELS = ("general",)
HUMAN_MAX_BYTES = 16000
KINDS = ("agent", "plan", "human", "system")


def root(repo):
    return teamlib.team_home() / "channels" / teamlib.repo_key(repo)


def team_channel(team_id):
    """A team talks in a channel named after it (#voyager, #delta-flyer), unless that name
    is taken by a standing channel or isn't a valid channel name."""
    slug = teamlib.slugify(team_id, 58)
    return slug if NAME_RE.match(slug) and slug not in DEFAULT_CHANNELS else "team-" + slug


def _path(repo, name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise teamlib.RejectedMessage("channel names are lowercase letters, digits and '-', "
                                      "starting with a letter (got %r)" % name)
    return root(repo) / (name + ".jsonl")


def _records(f):
    f.seek(0)
    out = []
    for ln in f.read().splitlines():
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


def post(repo, channel, sender, text, kind="agent", **extra):
    """Append one record and return it. Ids are per channel, 1, 2, 3, ... in write order."""
    if kind not in KINDS:
        raise teamlib.RejectedMessage("unknown record kind %r" % kind)
    with teamlib.locked(_path(repo, channel)) as f:
        rec = {"id": len(_records(f)) + 1, "ts": time.time(), "from": sender, "kind": kind,
               "text": teamlib.redact(text), **extra}
        f.write(json.dumps(rec) + "\n")
        f.flush()
    return rec


def read(repo, channel, after=0, limit=50):
    """Records with id > after, oldest first: the first `limit` of them when catching up from
    a cursor, or the latest `limit` when after is 0."""
    p = _path(repo, channel)
    if not p.exists():
        return []
    with teamlib.locked(p) as f:
        recs = [r for r in _records(f) if r.get("id", 0) > int(after)]
    limit = max(1, min(int(limit), 500))
    return recs[:limit] if int(after) else recs[-limit:]


def list_channels(repo):
    d = root(repo)
    for name in DEFAULT_CHANNELS:
        p = d / (name + ".jsonl")
        if not p.exists():
            with teamlib.locked(p):
                pass
    out = []
    for p in sorted(d.glob("*.jsonl")):
        last = read(repo, p.stem, limit=1)
        out.append({"channel": p.stem, "messages": last[0]["id"] if last else 0,
                    "last_ts": last[0]["ts"] if last else None,
                    "last_from": last[0]["from"] if last else None})
    return sorted(out, key=lambda c: -(c["last_ts"] or 0))


def human_post(repo, channel, text, name=None):
    """A post from the human (CLI or web page)."""
    text = teamlib.sanitize(text, HUMAN_MAX_BYTES)
    return post(repo, channel, name or human_name(), text, kind="human")


def human_name():
    return teamlib.load_config().get("human_name") or "kairos"


MENTION_RE = re.compile(r"(?<![\w@.])@([a-z][a-z0-9-]{0,40})\b")


def mentions(text):
    """@janeway, @tuvok, @all, @w2 ... (lowercased) in order of appearance, deduplicated."""
    seen = []
    for m in MENTION_RE.findall(text.lower()):
        if m not in seen:
            seen.append(m)
    return seen


def fenced(records):
    """Records as an agent should see them: every body is quoted data, never instructions."""
    return [{"id": r["id"], "ts": r["ts"], "from": r["from"], "kind": r["kind"],
             **({"title": r["title"]} if r.get("title") else {}),
             "text": teamlib.fence_external(r["from"], r["text"], teamlib.PLAN_MAX_BYTES)}
            for r in records]


# ---------- web page (the human's phone and browser) ----------

def web_token():
    """Bearer token for the web page, kept owner-only next to the channels."""
    p = teamlib.team_home() / "channels" / "web-token"
    if not p.exists():
        teamlib._write_private(p, secrets.token_urlsafe(24))
    return p.read_text().strip()


def tailscale_ip():
    import subprocess
    try:
        r = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    ip = r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else None
    return ip


def _host_allowed(host, allow_lan):
    """Plain HTTP carries the token, so bind only where the network itself is private:
    loopback, or Tailscale (100.64.0.0/10, encrypted end to end). A LAN needs --allow-lan."""
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10") or allow_lan


def make_server(repo, host="127.0.0.1", port=8787, allow_lan=False):
    import http.server
    import urllib.parse

    if not _host_allowed(host, allow_lan):
        raise teamlib.RejectedMessage(
            "refusing to serve channels on %s over plain HTTP; use 127.0.0.1, your Tailscale "
            "address (--phone), or pass --allow-lan if this network is yours alone" % host)
    token = web_token()
    page = (teamlib.package_dir() / "channels.html").read_bytes()

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "superyak-channels"

        def log_message(self, fmt, *args):      # no request logs: URLs and bodies stay private
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                             "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self):
            got = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            if teamlib.tokens_match(got, token):
                return True
            time.sleep(0.5)                     # slow down guessing
            self._send(401, {"error": "unauthorized"})
            return False

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path in ("/", "/index.html"):
                return self._send(200, page, "text/html; charset=utf-8")
            if not url.path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            if not self._authorized():
                return None
            q =dict(urllib.parse.parse_qsl(url.query))
            try:
                if url.path == "/api/channels":
                    return self._send(200, {"channels": list_channels(repo), "me": human_name()})
                if url.path == "/api/read":
                    return self._send(200, {"messages": read(repo, q.get("channel", ""),
                                                             int(q.get("after", 0) or 0),
                                                             int(q.get("limit", 100) or 100))})
            except (teamlib.RejectedMessage, ValueError) as e:
                return self._send(400, {"error": str(e)})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/post":
                return self._send(404, {"error": "not found"})
            if not self._authorized():
                return None
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > HUMAN_MAX_BYTES * 2:
                    raise teamlib.RejectedMessage("message too large")
                body = json.loads(self.rfile.read(n) or b"{}")
                rec = human_post(repo, body.get("channel", ""), body.get("text", ""))
            except (teamlib.RejectedMessage, ValueError) as e:
                return self._send(400, {"error": str(e)})
            return self._send(200, {"message": rec})

    return http.server.ThreadingHTTPServer((host, int(port)), Handler)


# ---------- human CLI ----------

USAGE = """superyak-runtime team channels                     list channels
superyak-runtime team channels read <channel> [n]    show the last n messages (default 20)
superyak-runtime team channels post <channel> <text> post as the human
superyak-runtime team channels serve [--phone] [--host H] [--port P] [--allow-lan]
    web page for browser and phone; --phone binds your Tailscale address"""


def _fmt(r):
    when = time.strftime("%m-%d %H:%M", time.localtime(r["ts"]))
    head = "#%d %s %s%s" % (r["id"], when, r["from"], " [plan] %s" % r.get("title", "") if r["kind"] == "plan" else "")
    return "%s\n  %s" % (head, r["text"].replace("\n", "\n  "))


def cli(argv, repo):
    sub = argv[0] if argv else "list"
    if sub == "list":
        for c in list_channels(repo):
            when = time.strftime("%m-%d %H:%M", time.localtime(c["last_ts"])) if c["last_ts"] else "-"
            print("%-32s %5d  %s  %s" % (c["channel"], c["messages"], when, c["last_from"] or ""))
        return 0
    if sub == "read" and len(argv) >= 2:
        for r in read(repo, argv[1], limit=int(argv[2]) if len(argv) > 2 else 20):
            print(_fmt(r))
        return 0
    if sub == "post" and len(argv) >= 3:
        rec = human_post(repo, argv[1], " ".join(argv[2:]))
        print("posted #%d to %s" % (rec["id"], argv[1]))
        return 0
    if sub == "serve":
        import argparse
        ap = argparse.ArgumentParser(prog="superyak-runtime team channels serve")
        ap.add_argument("--host", default=None)
        ap.add_argument("--port", type=int, default=8787)
        ap.add_argument("--phone", action="store_true", help="bind your Tailscale address")
        ap.add_argument("--allow-lan", action="store_true")
        a = ap.parse_args(argv[1:])
        host = a.host or ("127.0.0.1" if not a.phone else tailscale_ip())
        if not host:
            raise teamlib.RejectedMessage("--phone needs Tailscale running (`tailscale ip -4` gave nothing)")
        server = make_server(repo, host, a.port, a.allow_lan)
        print("Superyak channels for %s\nOpen: http://%s:%d/#t=%s\n(the #t= part is your login; "
              "keep the link private)" % (Path(repo).name, host, server.server_address[1], web_token()),
              flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    print(USAGE)
    return 2
