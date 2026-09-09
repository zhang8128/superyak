"""Exercise Python outputs against the sibling TypeScript Lighthouse kit."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from lighthouse_export import export_lighthouse_shadow, write_lighthouse_shadow
from lighthouse_protocol import artifact_digest, verify_artifact_digest
from lighthouse_receipts import build_receipt, write_receipt


def run_typescript(script: str, payload: dict) -> dict:
    kit = Path(os.environ.get(
        "LIGHTHOUSE_REPO", Path(__file__).resolve().parents[2] / "lighthouse"
    ))
    required = (
        "packages/protocol/src/index.ts", "node_modules/tsx/package.json",
        "packages/protocol/dist/index.js", "packages/calculus/dist/index.js",
    )
    if shutil.which("node") is None or any(
        not (kit / path).is_file() for path in required
    ):
        message = "Lighthouse runtime unavailable; run make setup-lighthouse"
        if os.environ.get("ENGRAM_REQUIRE_LIGHTHOUSE_INTEROP") == "1":
            pytest.fail(message)
        pytest.skip(message)
    completed = subprocess.run(
        ["node", "--import", "tsx", "--input-type=module", "--eval", script],
        cwd=kit, input=json.dumps(payload), capture_output=True, text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_technical_export_projects_only_receipts_within_its_root(tmp_db, tmp_path):
    for turn, path in (
        ("technical", ["memory", "technical"]),
        ("technical-child", ["memory", "technical", "python"]),
        ("research", ["memory", "research"]),
        ("parent", ["memory"]),
        ("lexical-prefix", ["memory", "technicality"]),
    ):
        receipt = build_receipt(
            receiver="engram", turn_id=turn,
            context={"id": "/".join(path), "path": path},
            purpose="session-recall", sources=[], selected=[], delivered=[],
            receiver_rule=None, issued_at="2026-09-01T00:00:00Z",
        )
        write_receipt(tmp_db, receipt, session_id=None, recall_id=turn)
    tmp_db.add_log_entry(
        id="invalid-receipt", event_type="lighthouse_receipt", layer="all",
        target_ids=[], context={"receipt": {"malformed": True}},
    )
    document, audit = export_lighthouse_shadow(
        Path(tmp_db.db_path), instance="engram-test"
    )
    destination = tmp_path / "scoped.engram.json"
    write_lighthouse_shadow(destination, document)

    result = run_typescript("""
        import { readFileSync } from 'node:fs';
        import { engramAdapter } from './adapters/engram/src/index.ts';
        import { verifyArtifactDigest } from './packages/protocol/src/index.ts';
        const { root } = JSON.parse(readFileSync(0, 'utf8'));
        const snapshot = await engramAdapter.project({
          root, id: 'urn:snapshot:scoped-export', issuer: 'urn:engram:test',
          issuedAt: '2026-09-01T00:00:00Z',
        });
        console.log(JSON.stringify({
          verification: verifyArtifactDigest(snapshot),
          turns: snapshot.payload.model.receipts.map(r => r.payload.turnId).sort(),
        }));
    """, {"root": str(destination)})

    assert result == {
        "verification": {"ok": True},
        "turns": ["technical", "technical-child"],
    }
    assert audit.receipts == 2
    assert audit.excluded_invalid_receipts == 1
    assert audit.excluded_outside_context_receipts == 3


@pytest.mark.parametrize("kind", ["ConnectionPolicy", "RecallReceipt"])
def test_unicode_extension_artifacts_verify_in_both_languages(kind):
    if kind == "ConnectionPolicy":
        artifact = json.loads((
            Path(__file__).parent / "fixtures/lighthouse/policy/policies/workflow-policy.json"
        ).read_text())
    else:
        artifact = build_receipt(
            receiver="engram", turn_id="unicode",
            context={"id": "memory/technical", "path": ["memory", "technical"]},
            purpose="session-recall", sources=[], selected=[], delivered=[],
            receiver_rule=None, issued_at="2026-09-01T00:00:00Z",
        )
    artifact["extensions"] = {
        "org.example:values": {
            "\ue000": 1, "\U00010000": 2,
            "array": [{"\ue000": "bmp", "\U00010000": "supplementary"}],
        }
    }
    artifact["digest"] = artifact_digest(artifact)

    result = run_typescript("""
        import { readFileSync } from 'node:fs';
        import {
          parseArtifact, sealArtifact, verifyArtifactDigest,
        } from './packages/protocol/src/index.ts';
        const artifact = parseArtifact(JSON.parse(readFileSync(0, 'utf8')));
        const { digest, attestations, ...unsigned } = artifact;
        console.log(JSON.stringify({
          verification: verifyArtifactDigest(artifact),
          sealed: sealArtifact(unsigned),
        }));
    """, artifact)

    assert result["verification"] == {"ok": True}
    assert result["sealed"]["digest"] == artifact["digest"]
    assert verify_artifact_digest(result["sealed"]) is True
