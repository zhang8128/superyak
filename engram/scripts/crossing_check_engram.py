"""Ship home and crossing plan, Task 13: Engram's two halves of the end-to-end crossing check, run as subprocesses by
peer/tests/test_crossing_e2e.py (B4: two environments; the peer and Engram talk only over the daemon socket and
crossing.sock, as in production). Everything here is a throwaway home under the directories it is given.

    publisher HOME --socket S --ref REF       build the publisher's home (house `why`, three shared memories, a ledger
                                              under enforce with remote-stores registered and S1's two allows, and
                                              the policy grant written by grant-remote), then serve the daemon on S
    prepare HOME                              make the receiver's store (instance `tardis`) and print its instance_id
    ask HOME --crossing-socket C --peer P --ship SHIP --receiver-ship R --query Q
                                              write the receiver's settings and policy, run attach_neighbors once, and
                                              print what it delivered and the records' disclosure ids, as JSON
    unshare HOME --memory ID                  withdraw one shared memory from the publisher's house

It holds a fixed-vector embedder of its own, since FakeEmbeddings lives in a test module."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import signal
import sqlite3
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ANDY = "person:andy"
HOME = "place:home/andy"
OUTSIDE = "place:outside-home"
AGENT = "agent:remote-stores"
SOURCE, HOUSE = "S", "HOUSE"
CONTEXT_ID = "memory/technical"
TEXTS = {1: "m1: shared: rivers need bridges across the valley floor",
         2: "m2: a visit to the clinic on the third floor",
         3: "m3: a note about the garden and its old stone wall"}


class FixedEmbeddings:
    """One-hot 768-vectors by the text's character sum: a query equal to a memory's text finds it."""

    def embed(self, texts, prefix=None):
        out = []
        for text in texts:
            vec = [0.0] * 768
            vec[sum(map(ord, text)) % 768] = 1.0
            out.append(vec)
        return out


def memory_id(n: int) -> str:
    return str(uuid.UUID(int=n))


def _house(home: Path):
    from storage import Storage
    inst = home / ".engram" / "instances" / "why"
    inst.mkdir(parents=True)
    store = Storage(str(inst / "graph.db"))
    store.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('instance_id', ?)", (HOUSE,))
    embed = FixedEmbeddings()
    rows = []
    for n, text in TEXTS.items():
        store.add_episode(memory_id(n), "s", text, embedding=embed.embed([text])[0])
        rows.append((f"share-{n}", memory_id(n), "engram", f"m{n}", "episode", "commons", "e2e",
                     hashlib.sha256(text.encode()).hexdigest(), "2026-11-01", SOURCE, None))
    store.conn.executemany(
        "INSERT INTO shared_memories (share_id, memory_id, source_instance, source_id, layer, audience, reason, "
        "content_digest, shared_at, source_instance_id, record_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    store.conn.commit()
    store.close()
    lighthouse = home / ".engram" / "instances" / "lighthouse"
    lighthouse.mkdir(parents=True)
    con = sqlite3.connect(lighthouse / "graph.db")
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.commit()
    con.close()
    return inst


def _ledger(home: Path, now: int) -> None:
    """S1's records, with the actions deciding inject_context needs (recall, read, inject_context)."""
    from permission_ledger import Ledger
    from permissions import Act, parse_selector
    led = Ledger.create(home, "andy", now=now - 120)

    def do(kind, **args):
        led.perform(Act(kind, args), actor=ANDY, channel="terminal", now=now - 60)
    do("register-store", instance_id=SOURCE, name="engram", owner=ANDY, place=HOME, imprint_of=None)
    do("register-store", instance_id=HOUSE, name="published house", owner=ANDY, place=HOME, imprint_of=None)
    do("register-place", place=OUTSIDE, name="Outside home")
    do("register-agent", agent=AGENT, acts_for=HOME)
    do("put-agent", agent=AGENT, place=OUTSIDE)
    for layer in (HOME, OUTSIDE):
        objects = {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*", "collections": "*",
                   "memories": ["mem:S/episode/m1"]}   # m1 alone crosses; m2 and m3 the ledger keeps home
        sel = parse_selector({"audience": ["commons"], "requesters": [AGENT], "objects": objects,
                              "actions": ["recall", "read", "inject_context"], "purposes": ["session-recall"]})
        do("allow", layer=layer, selector=sel, valid_from=now - 60, valid_until=now + 300 * 86400, reason="e2e")
    do("gate", mode="enforce")
    led.close()


def publisher(args) -> int:
    import lighthouse_daemon
    from policy_gen import build_publisher_policy, grant_remote, write_receiver_policy
    home = Path(args.home)
    now = int(time.time())
    inst = _house(home)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))
    write_receiver_policy(inst / "lighthouse-policy.json", build_publisher_policy(
        publisher="why", receivers=[], groups={}, issued_at=stamp, valid_from=stamp,
        valid_until=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 30 * 86400))))
    grant_remote(home, "why", args.ref, context=CONTEXT_ID, audiences=["commons"], purpose="session-recall")
    _ledger(home, now)
    pub = lighthouse_daemon.PublisherStore(name="why", db_path=inst / "graph.db",
                                           policy_path=inst / "lighthouse-policy.json",
                                           disclosures_path=inst / "lighthouse-disclosures.db")
    daemon = lighthouse_daemon.PublisherDaemon({"why": pub}, Path(args.socket), FixedEmbeddings(), engram_home=home)
    signal.signal(signal.SIGTERM, lambda *_: daemon.stop())
    import threading
    thread = threading.Thread(target=daemon.serve_forever, daemon=True)
    thread.start()
    if not daemon.wait_ready(10):
        print("the daemon did not start", file=sys.stderr)
        return 1
    print(json.dumps({"ready": True, "sidecar": str(pub.disclosures_path)}), flush=True)
    thread.join()
    return 0


def prepare(args) -> int:
    from storage import Storage
    inst = Path(args.home) / ".engram" / "instances" / "tardis"
    inst.mkdir(parents=True)
    store = Storage(str(inst / "graph.db"))
    try:
        print(json.dumps({"instance_id": store.instance_identity()["instance_id"]}))
    finally:
        store.close()
    return 0


def ask(args) -> int:
    import neighbors
    import remote_deliveries
    from lighthouse_protocol import artifact_digest
    from storage import Storage
    home = Path(args.home)
    inst = home / ".engram" / "instances" / "tardis"
    ref = f"urn:superyak:{args.peer}:ship:{args.ship}"
    rule = dict(id="crossing", effect="allow", publishers=[ref], profiles=["urn:lighthouse:profile:engram-recall-trace"],
                domains=["memory.recall"], actions=["recall", "read", "inject_context"], contexts=[CONTEXT_ID],
                claimMediaTypes=["application/vnd.engram.recall-rank-claim+json"], purposes=["session-recall"],
                audiences=["self"], validFrom="2026-01-01T00:00:00Z", validUntil="2030-01-01T00:00:00Z",
                requiredEvidence=[], requiredAttestations=[])
    policy = dict(protocolVersion="0.1", kind="ConnectionPolicy", id="urn:policy:tardis", issuedAt="2026-01-01T00:00:00Z",
                  issuer="urn:engram:tardis", payloadMediaType="application/vnd.lighthouse.connection-policy+json",
                  payload={"rules": [rule]}, extensions={})
    policy["digest"] = artifact_digest(policy)
    (inst / "receiver-policy.json").write_text(json.dumps(policy))
    (inst / "lighthouse-receiver.toml").write_text(
        f'enabled = true\npublishers = []\npolicy_path = "receiver-policy.json"\ntimeout_s = 10\n'
        f'crossing_socket = "{args.crossing_socket}"\nreceiver_ship = "{args.receiver_ship}"\n'
        f'[[remote_publishers]]\npeer_id = "{args.peer}"\nship = "{args.ship}"\ncontext = "{CONTEXT_ID}"\n')
    store = Storage(str(inst / "graph.db"))
    try:
        response = neighbors.attach_neighbors({"results": [], "recall_id": str(uuid.uuid4())}, query=args.query,
                                              context_id=CONTEXT_ID, purpose="session-recall", storage=store,
                                              session_id="e2e", receiver="tardis", engram_home=home)
        result = response.get("neighbors", {})
        receipts = [json.loads(row[0])["receipt"]["extensions"].get("engram:readDisclosures", [])
                    for row in store.conn.execute(
                        "SELECT context FROM memory_log WHERE event_type='lighthouse_receipt' ORDER BY timestamp")]
    finally:
        store.close()
    path = remote_deliveries.path_for(inst / "graph.db")
    recorded = []
    if path.exists():
        with sqlite3.connect(path) as db:
            recorded = sorted({row[0] for row in db.execute("SELECT disclosure_id FROM remote_deliveries")})
    print(json.dumps({"delivered": [i["content"] for i in result.get("delivered", [])],
                      "diagnostics": result.get("diagnostics", []), "receipts": receipts, "recorded": recorded}))
    return 0


def unshare(args) -> int:
    con = sqlite3.connect(Path(args.home) / ".engram" / "instances" / "why" / "graph.db")
    removed = con.execute("DELETE FROM shared_memories WHERE memory_id = ?", (args.memory,)).rowcount
    con.commit()
    con.close()
    print(json.dumps({"unshared": removed}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="crossing_check_engram.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("publisher")
    p.add_argument("home")
    p.add_argument("--socket", required=True)
    p.add_argument("--ref", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("home")
    p = sub.add_parser("ask")
    p.add_argument("home")
    for name in ("--crossing-socket", "--peer", "--ship", "--receiver-ship", "--query"):
        p.add_argument(name, required=True)
    p = sub.add_parser("unshare")
    p.add_argument("home")
    p.add_argument("--memory", required=True)
    args = parser.parse_args(argv)
    return {"publisher": publisher, "prepare": prepare, "ask": ask, "unshare": unshare}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
