"""North-star test 5's transport, the receiving side in Atlas (docs/superpowers/specs/2026-11-22-claim-crossing-transport-
design.md, T3, T4 and T6). It reads one file the peer's `atlas-received` wrote, and returns the publication or notice
it carries, ready for held_claims, relation and apply_notice, or raises ValueError in words of its own.

What it checks, in order:
1. The file's sender agrees with its key: the SHA-256 of the signing key is the origin, in the envelope and in the
   delivered record. This is a consistency check. The signature itself is the peer's `atlas-verify`, since Atlas has no
   Ed25519 (A5).
2. Every artifact is issued as the sender's URI, urn:superyak:peer:<origin>. A carried entry is the receiver's own or the
   sender's, its claim and snapshot share one issuer, and one issued as the receiver's must be a claim this store really
   published, with that snapshot (R2). The receiver's URI comes from its caller's own publications, never from the file
   (A6). With none, every receiver-issued carried entry is refused (A4).
3. A notice is the sender's, and every Snapshot it names must be held, whether its own or received. An early notice
   names the Snapshot it waits for (A1). validate_notice then refuses one naming another issuer's Snapshot (R3, in
   sourced.py since 08d40fa2).
4. validate_sourced, for a publication."""
import base64
import hashlib

from .sourced import validate_notice, validate_sourced

KINDS = {"atlas.publication": "package", "atlas.notice": "notice"}


def peer_uri(peer_id):
    return f"urn:superyak:peer:{peer_id}"


def _origin(file):
    """Step 1: the origin the file's key proves, which its envelope and delivered record must both name."""
    if not isinstance(file, dict) or file.get("format") != "atlas-received" or file.get("version") != 1:
        raise ValueError("Not a received atlas file")
    envelope, delivered = file.get("envelope"), file.get("delivered")
    if not isinstance(envelope, dict) or not isinstance(delivered, dict) or envelope.get("action") not in KINDS:
        raise ValueError("Not a received atlas file")
    try:
        key = base64.b64decode(file.get("signing_key", ""), validate=True)
    except (ValueError, TypeError):
        raise ValueError("Not a received atlas file") from None
    origin = hashlib.sha256(key).hexdigest()
    if envelope.get("origin") != origin or delivered.get("origin") != origin:
        raise ValueError("The file's sender doesn't match its key")
    return origin, envelope


def _own(own_publications):
    """The receiver's URI and the (claim digest, snapshot digest) pairs it really published."""
    issuers = {p["descriptor"]["issuer"] for p in own_publications}
    if len(issuers) > 1:
        raise ValueError("The receiver's own publications name more than one issuer")
    published = {(c["digest"]["value"], p["snapshot"]["digest"]["value"]) for p in own_publications for c in p["claims"]}
    return (issuers.pop() if issuers else None), published


def received(file, own_publications, *, trusted_origins, received_publications=()):
    """One received file, checked (module docstring). `own_publications` are this store's own sourced publications.
    `received_publications` are ones already received, which a notice may name. `trusted_origins` is the caller's trust
    root, the `paired` list of the origins.json that atlas-received wrote beside the files (Rio Grande's read, 3): a
    file whose origin isn't in it is refused. Run the peer's atlas-verify on each file first: it checks the signature."""
    origin, envelope = _origin(file)
    if origin not in set(trusted_origins):  # required, never a default that trusts all (Serenity's re-read)
        raise ValueError("The file's sender is not one this store's peer had paired")
    sender = peer_uri(origin)
    own_uri, published = _own(own_publications)
    field = KINDS[envelope["action"]]
    body = (envelope.get("payload") or {}).get(field)
    if not isinstance(body, dict):
        raise ValueError("Not a received atlas file")
    if field == "notice":
        if body.get("issuer") != sender:
            raise ValueError("A notice must be issued by the peer that delivered it")
        held = list(own_publications) + list(received_publications)
        snapshots = {p["snapshot"]["digest"]["value"] for p in held} | {
            e["snapshot"]["digest"]["value"] for p in held for e in p.get("carried", [])}
        for named in body.get("payload", {}).get("snapshotDigests", []):
            if named.get("value") not in snapshots:
                raise ValueError(f"A notice names a snapshot not held here yet: {str(named.get('value'))[:12]}")
        validate_notice(body, held)
        return {"notice": body, "origin": origin, "delivered": file["delivered"]}
    own = [body.get("descriptor"), body.get("snapshot"), body.get("policy"), *body.get("claims", [])]
    if any(not isinstance(a, dict) or a.get("issuer") != sender for a in own):
        raise ValueError("A publication's artifacts must all be issued by the peer that delivered it")
    for entry in body.get("carried", []):
        claim, snapshot = entry.get("claim") or {}, entry.get("snapshot") or {}
        issuer = claim.get("issuer")
        if issuer != snapshot.get("issuer") or issuer not in {sender, own_uri} - {None}:
            raise ValueError("A carried claim must be the receiver's own or the sender's, with its own snapshot")
        if issuer == own_uri and ((claim.get("digest") or {}).get("value"),
                                  (snapshot.get("digest") or {}).get("value")) not in published:
            raise ValueError("A carried claim names this store as its issuer, but this store never published it")
    validate_sourced(body)
    return {"package": body, "origin": origin, "delivered": file["delivered"]}
