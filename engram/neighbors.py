"""Opt-in Lighthouse receiver. Local recall never depends on a neighbor."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time

from lighthouse_client import LighthouseClient, NeighborUnavailable, fuse_traces, validate_read, validate_trace
from lighthouse_policy import PolicyRequest
from lighthouse_protocol import artifact_digest, canonical_json, content_digest, recall_frame, read_frame
from permissions import annotation_line
from lighthouse_receipts import build_receipt, write_receipt
from lighthouse_receiver_config import NAME, context_ref, load_receiver_policy, load_settings, valid_publishers

PROFILE = "urn:lighthouse:profile:engram-recall-trace"
CLAIM_TYPE = "application/vnd.engram.recall-rank-claim+json"
MAX_CONTENT_BYTES = 32768


def _empty(code):
    return dict(sources=[], selected=[], delivered=[], receipt_id=None,
                degraded=True, diagnostics=[{"code": code}])


def _say_unreached(response, code):
    """An asked-for neighbor that couldn't be consulted: an empty result naming why, and `neighbors` in degraded."""
    response["neighbors"] = _empty(code)
    response.setdefault("degraded", []).append("neighbors")
    return response


def neighbor_arm(*, query, context, purpose, k, storage, session_id, recall_id,
                 receiver, publishers, socket_path, policy_path, timeout_s=2.0, now=None):
    """Consult only explicit peers and persist a content-free receipt before delivery.

    ``now`` is an injectable clock, never a wire-supplied authorization time.
    A recall grant denied for every publisher returns an empty result naming each publisher's decision code
    (the top code when they share one, else RECEIVER_RULES_DENIED). `diagnostics[0]` is the top-level code;
    the per-publisher entries follow it; other failures return diagnostics.
    """
    import math
    if (not isinstance(receiver, str) or not NAME.fullmatch(receiver)
            or not valid_publishers(publishers)
            or not isinstance(query, str) or not 1 <= len(query) <= 4096
            or not isinstance(purpose, str) or not 1 <= len(purpose) <= 256
            or type(k) is not int or not 1 <= k <= 5
            or type(timeout_s) not in (int, float) or not math.isfinite(timeout_s)
            or not 0 < timeout_s <= 10):
        return _empty("INVALID_REQUEST")
    try:
        if context != context_ref(context["id"]):
            return _empty("INVALID_CONTEXT")
    except (ValueError, TypeError, KeyError):
        return _empty("INVALID_CONTEXT")
    clock = now or (lambda: datetime.now(timezone.utc))
    deadline = time.monotonic() + timeout_s
    client = LighthouseClient(socket_path, timeout_s=timeout_s)
    sources, snapshots, unavailable, decisions, diagnostics = [], [], [], [], []
    traces, lookup = {}, {}
    selected, delivered = [], []

    def authorize(publisher, actions, phase):
        policy = load_receiver_policy(policy_path, receiver)
        results = {}
        for action in actions:
            decision = policy.decide(PolicyRequest(
                publisher=publisher, profile=PROFILE, domain="memory.recall", action=action,
                context_id=context["id"], claim_type=CLAIM_TYPE, purpose=purpose,
                audience="self", at=clock()))
            results[action] = decision
            decisions.append(dict(publisher=publisher, action=action, phase=phase, **decision.to_json()))
        return policy, results

    def permits(results):
        return all(d.effect == "allow" for d in results.values())

    def remaining():
        if time.monotonic() >= deadline:
            raise NeighborUnavailable("TIMEOUT")

    try:
        # A bad policy is rejected even when its malformed rule would not match.
        load_receiver_policy(policy_path, receiver)
    except Exception:
        return _empty("RECEIVER_POLICY_INVALID")

    attempted = False
    denied = []
    for name in publishers:
        publisher = f"urn:engram:{name}"
        decision, weight = None, 0
        try:
            policy, grants = authorize(publisher, ["recall"], "query")
            decision = grants["recall"]
            if not permits(grants):
                denied.append(dict(publisher=publisher, code=decision.code or "NO_MATCHING_ALLOW"))
                continue
            attempted = True
            weight = policy.artifact.get("extensions", {}).get("engram:weight", {}).get(publisher, 1)
            remaining()
            reply = client.call(recall_frame(receiver=receiver, publisher=name, context=context,
                                purpose=purpose, query=query, k=20, at=clock().isoformat()), deadline=deadline)
            snapshot = validate_trace(reply, publisher=publisher, query=query, context=context, k=20)
            snapshots.append(snapshot)
            outcome = ("policy-denied" if snapshot["decision"]["effect"] != "allow"
                       else "matched" if snapshot["candidates"] else "absent")
            sources.append(dict(publisher=publisher, role="remote", weight=weight,
                                storeDigest=content_digest(canonical_json(snapshot)),
                                policyDecision=decision.to_json(), traceOutcome=outcome))
            traces[publisher] = (weight, snapshot["candidates"])
            for candidate in snapshot["candidates"]:
                lookup[(publisher, candidate["memoryId"])] = candidate
        except Exception as error:
            code = getattr(error, "code", "NEIGHBOR_ERROR")
            diagnostics.append(dict(publisher=publisher, code=code))
            if decision is not None and decision.effect == "allow":
                unavailable.append(dict(publisher=publisher, weight=weight,
                                        policyDecision=decision.to_json(), code=code))
    if not attempted:
        if diagnostics:
            return _empty("RECEIVER_POLICY_INVALID")
        if denied:
            codes = {d["code"] for d in denied}
            result = _empty(denied[0]["code"] if len(codes) == 1 else "RECEIVER_RULES_DENIED")
            result["diagnostics"].extend(denied)
            return result
        return None

    try:
        selected = fuse_traces(traces, k=k)
        for snapshot in snapshots:
            publisher = snapshot["publisher"]
            chosen = [dict(item, **{key: value for key, value in lookup[(publisher, item["memoryId"])].items()
                                   if key not in item})
                      for item in selected if item["publisher"] == publisher]
            if not chosen:
                continue
            try:
                _, grants = authorize(publisher, ["recall", "read", "inject_context"], "read")
                if not permits(grants):
                    continue
                remaining()
                reply = client.call(read_frame(receiver=receiver, publisher=publisher.removeprefix("urn:engram:"),
                                    context=context, purpose=purpose, turn_id=snapshot["turnId"],
                                    memory_ids=[item["memoryId"] for item in chosen]), deadline=deadline)
                verified = validate_read(reply, selected=chosen)
                delivered.extend(verified)
            except Exception as error:
                diagnostics.append(dict(publisher=publisher, code=getattr(error, "code", "NEIGHBOR_ERROR")))

        # Recheck every delivering peer after all I/O; withdrawal may occur while
        # another peer is being read. This is the authorization point for response construction.
        final_allowed = set()
        for publisher in dict.fromkeys(item["publisher"] for item in delivered):
            try:
                remaining()
                _, grants = authorize(publisher, ["recall", "read", "inject_context"], "delivery")
                if permits(grants):
                    final_allowed.add(publisher)
            except Exception as error:
                diagnostics.append(dict(publisher=publisher, code=getattr(error, "code", "NEIGHBOR_ERROR")))
        delivered = [item for item in delivered if item["publisher"] in final_allowed]
        order = {(item["publisher"], item["memoryId"]): i for i, item in enumerate(selected)}
        delivered.sort(key=lambda item: order[(item["publisher"], item["memoryId"])])
        content_bytes, bounded = 0, []
        for item in delivered:
            size = len(item["content"].encode("utf-8"))
            if content_bytes + size > MAX_CONTENT_BYTES:
                diagnostics.append(dict(publisher=item["publisher"], code="CONTENT_BUDGET"))
                continue
            content_bytes += size
            bounded.append(item)
        delivered = bounded
        permitted = [i["permission"] for i in delivered if isinstance(i.get("permission"), dict)]
        delivered = [{**i, "permission": annotation_line(i["permission"])} if isinstance(i.get("permission"), dict) else i
                     for i in delivered]
        recall_rules = {source["policyDecision"]["ruleId"] for source in sources}
        receipt = build_receipt(receiver=receiver, turn_id=recall_id, context=context, purpose=purpose,
                                sources=sources, selected=selected,
                                delivered=[dict(publisher=i["publisher"], memoryId=i["memoryId"],
                                                readDecision=i["decision"]) for i in delivered],
                                receiver_rule=next(iter(recall_rules)) if len(recall_rules) == 1 else None,
                                issued_at=clock().isoformat())
        receipt["extensions"] = {"engram:traceSnapshots": snapshots,
                                 "engram:unavailableSources": unavailable,
                                 "engram:receiverDecisions": decisions,
                                 "engram:diagnostics": diagnostics,
                                 "engram:sourceDigestBasis": "canonical-received-trace-v1"}
        if permitted:
            receipt["extensions"]["engram:permissions"] = {
                "receipts": sorted({p["receipt"] for p in permitted}),
                "records": sorted({r for p in permitted for e in p["allowed_by"] for r in e["records"]})}
        receipt["digest"] = artifact_digest(receipt)
        receipt_id = write_receipt(storage, receipt, session_id=session_id, recall_id=recall_id)
    except Exception:
        return dict(_empty("RECEIPT_FAILED"), sources=sources, selected=selected)
    return dict(sources=sources, selected=selected, delivered=delivered, receipt_id=receipt_id,
                degraded=bool(diagnostics), diagnostics=diagnostics)


def attach_neighbors(response, *, query, context_id, purpose, storage, session_id, receiver, engram_home):
    """Final MCP response seam; opt-in settings and declared context are both required. A recall that names no
    context is inert. One that names a context but reaches no neighbor, because this server has no named receiver
    or that receiver isn't enabled, says so in `neighbors` and `degraded`, so a caller never takes local results
    alone for a search of shared memory (Rio Grande's Engram test, 2026-11-03)."""
    if context_id is None:
        return response
    if not receiver:
        return _say_unreached(response, "NO_RECEIVER")
    try:
        if not isinstance(receiver, str) or not NAME.fullmatch(receiver):
            raise ValueError("INVALID_RECEIVER")
        context = context_ref(context_id)
        instance = Path(engram_home) / ".engram" / "instances" / receiver
        settings = load_settings(instance / "lighthouse-receiver.toml")
        if settings is None:
            return _say_unreached(response, "RECEIVER_DISABLED")
        # The server may fall back to its default DB when a named store is absent.
        if Path(storage.db_path).resolve() != (instance / "graph.db").resolve():
            raise ValueError("RECEIVER_STORE_MISMATCH")
        result = neighbor_arm(query=query, context=context, purpose=purpose, storage=storage,
                              session_id=session_id, recall_id=response["recall_id"], receiver=receiver, **settings)
    except Exception:
        result = _empty("RECEIVER_CONFIG_INVALID")
    if result is not None:
        response["neighbors"] = result
        if result["degraded"]:
            response.setdefault("degraded", []).append("neighbors")
    return response
