"""Disposable real-socket Lighthouse crossing; human usefulness is not measured."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import uuid

from lighthouse_daemon import CLAIM_TYPE, DOMAIN, PROFILE, PublisherDaemon, PublisherStore
from lighthouse_protocol import artifact_digest, canonical_json
from lighthouse_receipts import validate_receipt
from neighbors import neighbor_arm
from sharing import share, unshare
from storage import Storage


CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}
PURPOSE = "session-recall"
RECEIVER = "pilot-receiver"
PUBLISHER = "pilot-publisher"
ALLOWED_CONTENT = "Synthetic bridge maintenance: inspect the upstream support."
DENIED_CONTENT = "Synthetic restricted crossing: the eastern support is closed."
QUERY = "Synthetic bridge maintenance guidance"


class SyntheticEmbeddings:
    """Small deterministic fixture vectors; never load a model or use a network."""

    def embed(self, texts, prefix=None):
        result = []
        for text in texts:
            vector = [0.0] * 768
            vector[hashlib.sha256(text.encode()).digest()[0]] = 1.0
            result.append(vector)
        return result


def _write_json(path, artifact):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(artifact) + "\n")


def _write_policy(path, *, issuer, peer, actions, effect="allow", audiences=None):
    artifact = {
        "protocolVersion": "0.1", "kind": "ConnectionPolicy",
        "id": f"urn:engram:{issuer}:pilot-policy",
        "issuedAt": "2026-09-06T00:00:00Z", "issuer": f"urn:engram:{issuer}",
        "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
        "payload": {"rules": [{
            "id": "pilot-grant", "effect": effect,
            "publishers": [f"urn:engram:{peer}"], "profiles": [PROFILE],
            "domains": [DOMAIN], "actions": list(actions),
            "contexts": [CONTEXT["id"]], "claimMediaTypes": [CLAIM_TYPE],
            "purposes": [PURPOSE], "audiences": ["self"],
            "validFrom": "2020-01-01T00:00:00Z", "validUntil": "2100-01-01T00:00:00Z",
            "requiredEvidence": [], "requiredAttestations": [],
        }]},
    }
    if audiences is not None:
        artifact["extensions"] = {"engram:audiences": {f"urn:engram:{peer}": audiences}}
    artifact["digest"] = artifact_digest(artifact)
    # Only this pilot's newly created policies are ever replaced.
    replacement = path.with_suffix(".next")
    _write_json(replacement, artifact)
    replacement.replace(path)


def _seed_stores(directory):
    source = Storage(str(directory / "source.db"))
    published = Storage(str(directory / "publisher.db"))
    records = []
    embeddings = SyntheticEmbeddings()
    try:
        for content, audience in ((ALLOWED_CONTENT, "commons"),
                                  (DENIED_CONTENT, "group:restricted")):
            memory_id = str(uuid.uuid4())
            source.add_episode(memory_id, None, content, lane="personal",
                               embedding=embeddings.embed([content])[0])
            records.append(share(
                source_storage=source, published_storage=published,
                source_instance="pilot-private", source_id=memory_id,
                layer="episode", audience=audience, reason="synthetic pilot",
            ))
        published.add_episode(
            str(uuid.uuid4()), None, "Synthetic unshared work stays private.",
            lane="work", embedding=embeddings.embed([QUERY])[0],
        )
    finally:
        source.close()
        published.close()
    return records


def _export_receipt(storage, receipt_id, path):
    for entry in storage.get_log_entries(event_type="lighthouse_receipt"):
        receipt = json.loads(entry["context"])["receipt"]
        if receipt["id"] == receipt_id:
            validate_receipt(receipt)
            _write_json(path, receipt)
            return
    raise RuntimeError("RECEIPT_NOT_PERSISTED")


def run_pilot(output: Path) -> dict:
    """Create a new disposable directory and verify all crossings before reporting."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    stores = output / "stores"
    stores.mkdir()
    receipts = output / "receipts"
    receipts.mkdir()
    allowed, forbidden = _seed_stores(stores)
    source_path = stores / "source.db"
    private_before = source_path.read_bytes()
    publisher_policy = output / "publisher-policy.json"
    receiver_policy = output / "receiver-policy.json"

    def publisher_grant(effect="allow"):
        _write_policy(publisher_policy, issuer=PUBLISHER, peer=RECEIVER,
                      actions=("recall", "read"), effect=effect, audiences=["commons"])

    def receiver_grant(actions=("recall", "read", "inject_context")):
        _write_policy(receiver_policy, issuer=RECEIVER, peer=PUBLISHER, actions=actions)

    publisher_grant()
    receiver_grant()
    publisher = PublisherStore(
        PUBLISHER, stores / "publisher.db", publisher_policy, stores / "disclosures.db"
    )
    receiver = Storage(str(stores / "receiver.db"))
    scenarios = {}
    try:
        # macOS Unix sockets need a short absolute path, regardless of --output.
        with tempfile.TemporaryDirectory(prefix="lh-pilot-", dir="/tmp") as socket_dir:
            daemon = PublisherDaemon(
                {PUBLISHER: publisher}, Path(socket_dir) / "s.sock", SyntheticEmbeddings()
            )
            thread = threading.Thread(target=daemon.serve_forever, daemon=True)
            thread.start()
            try:
                if not daemon.wait_ready(timeout=5):
                    raise RuntimeError("PUBLISHER_START_FAILED")

                def crossing(name, selected_count, delivered_count):
                    before = publisher.db_path.read_bytes()
                    result = neighbor_arm(
                        query=QUERY, context=CONTEXT, purpose=PURPOSE, k=1,
                        storage=receiver, session_id=None, recall_id=f"pilot-{name}",
                        receiver=RECEIVER, publishers=[PUBLISHER],
                        socket_path=daemon.socket_path, policy_path=receiver_policy,
                    )
                    if (result is None or result["degraded"]
                            or len(result["selected"]) != selected_count
                            or len(result["delivered"]) != delivered_count):
                        raise RuntimeError("CROSSING_FAILED")
                    if any(item["memoryId"] == forbidden.memory_id
                           for item in result["selected"] + result["delivered"]):
                        raise RuntimeError("DENIED_AUDIENCE_DISCLOSED")
                    if delivered_count and (
                        result["delivered"][0]["memoryId"] != allowed.memory_id
                        or result["delivered"][0]["content"] != ALLOWED_CONTENT
                        or result["delivered"][0]["lane"] != "personal"
                    ):
                        raise RuntimeError("DELIVERY_MISMATCH")
                    if publisher.db_path.read_bytes() != before:
                        raise RuntimeError("PUBLISHER_STORE_CHANGED")
                    receipt_file = f"receipts/{name}.json"
                    _export_receipt(receiver, result["receipt_id"], output / receipt_file)
                    scenarios[name] = dict(
                        selectedCount=selected_count, deliveredCount=delivered_count,
                        receiptFile=receipt_file, receiptId=result["receipt_id"],
                        publisherBytesUnchanged=True,
                    )

                crossing("allowed", 1, 1)
                receiver_grant(actions=("recall",))
                crossing("denied", 1, 0)
                receiver_grant()
                publisher_grant(effect="deny")
                crossing("policy_withdrawn", 0, 0)
                publisher_grant()
                writer = Storage(str(publisher.db_path))
                try:
                    if not unshare(published_storage=writer, share_id=allowed.share_id):
                        raise RuntimeError("UNSHARE_FAILED")
                finally:
                    writer.close()
                crossing("unshared", 0, 0)
            finally:
                daemon.stop()
                thread.join(timeout=5)
                if thread.is_alive():
                    raise RuntimeError("PUBLISHER_STOP_FAILED")
    finally:
        receiver.close()
    if source_path.read_bytes() != private_before:
        raise RuntimeError("PRIVATE_SOURCE_CHANGED")
    report = dict(
        formatVersion="1.0", transport="local-unix-socket", synthetic=True,
        humanUsefulnessEvaluated=False, scenarios=scenarios,
        checks=dict(allowedDelivery=True, receiverDenial=True, policyWithdrawal=True,
                    unshareWithdrawal=True, deniedAudienceAbsent=True,
                    publisherUnchangedDuringRequests=True, privateSourceUnchanged=True),
    )
    _write_json(output / "report.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New disposable output directory")
    args = parser.parse_args(argv)
    try:
        report = run_pilot(args.output)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"lighthouse_pilot: {error}\n")
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
