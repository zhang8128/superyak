import { digestJson, type Digest, verifyJsonDigest } from "./digest.js";
import type { JsonValue } from "./json.js";
import {
  lighthouseArtifactSchema,
  type LighthouseArtifact,
  unsignedArtifactSchema,
  type UnsignedLighthouseArtifact,
} from "./schemas.js";

type DigestibleArtifact = LighthouseArtifact | UnsignedLighthouseArtifact;

export function artifactDigestContent(artifact: DigestibleArtifact): JsonValue {
  const { attestations: _attestations, ...withoutAttestations } = artifact;
  if ("digest" in withoutAttestations) {
    const { digest: _digest, ...content } = withoutAttestations;
    return content as JsonValue;
  }
  return withoutAttestations as JsonValue;
}

export function sealArtifact<T extends UnsignedLighthouseArtifact>(input: T): T & { digest: Digest } {
  const parsed = unsignedArtifactSchema.parse(input) as T;
  return {
    ...parsed,
    digest: digestJson(artifactDigestContent(parsed)),
  };
}

export function parseArtifact(input: unknown): LighthouseArtifact {
  return lighthouseArtifactSchema.parse(input);
}

export type DigestVerification = { ok: true } | { ok: false; code: "DIGEST_MISMATCH" };

export function verifyArtifactDigest(artifact: LighthouseArtifact): DigestVerification {
  return verifyJsonDigest(artifactDigestContent(artifact), artifact.digest)
    ? { ok: true }
    : { ok: false, code: "DIGEST_MISMATCH" };
}
