import {
  ADNA_PORT_CLAIM_MEDIA_TYPE,
  ADNA_PROFILE,
} from "@lighthouse/adapter-adna";
import {
  HYPER_DEPENDENCY_MEDIA_TYPE,
  HYPER_LEASE_MEDIA_TYPE,
  HYPER_PROFILE,
} from "@lighthouse/adapter-hyper";
import type { BridgeEnvelopeMetadata, RuntimeBridge } from "@lighthouse/calculus";
import {
  digestJson,
  sealArtifact,
  type Claim,
  type JsonValue,
} from "@lighthouse/protocol";

export interface HyperAdnaTopicMapping {
  outputPort: string;
  inputPort: string;
  valueType: string;
}

export interface HyperAdnaMapping {
  id: string;
  producerNodes: Record<string, string>;
  consumerNodes: Record<string, string>;
  topics: Record<string, HyperAdnaTopicMapping>;
}

function asRecord(value: JsonValue): Record<string, JsonValue> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value
    : undefined;
}

function unmapped(message: string, paths: string[]) {
  return {
    ok: false as const,
    obstruction: { code: "BRIDGE_CLAIM_UNMAPPED", message, paths },
  };
}

export function createHyperAdnaBridge(
  mapping: HyperAdnaMapping,
  metadata: BridgeEnvelopeMetadata,
): RuntimeBridge {
  const descriptor = sealArtifact({
    kind: "BridgeDescriptor",
    protocolVersion: "0.1",
    ...metadata,
    payloadMediaType: "application/vnd.lighthouse.bridge+json",
    payload: {
      source: HYPER_PROFILE,
      target: ADNA_PROFILE,
      domain: {
        contexts: ["workflow/orders"],
        claimMediaTypes: [HYPER_DEPENDENCY_MEDIA_TYPE],
      },
      fidelity: "partial",
      implementation: "urn:lighthouse:implementation:hyper-adna-v0.1",
      dependencies: [digestJson(mapping as unknown as JsonValue)],
    },
  });

  return {
    descriptor,
    lineage: [descriptor],
    async translateClaim(claim: Claim) {
      if (claim.payload.sentenceMediaType === HYPER_LEASE_MEDIA_TYPE) {
        return unmapped("Hyper lease claims are outside the v0.1 bridge domain", [
          "payload.sentence",
        ]);
      }
      if (
        claim.payload.profile.id !== HYPER_PROFILE.id ||
        claim.payload.profile.version !== HYPER_PROFILE.version
      ) {
        return {
          ok: false,
          obstruction: {
            code: "BRIDGE_DOMAIN_MISMATCH",
            message: "The claim does not use the Hyper source profile",
            paths: ["payload.profile"],
          },
        };
      }
      if (claim.payload.sentenceMediaType !== HYPER_DEPENDENCY_MEDIA_TYPE) {
        return unmapped("The claim media type is outside the v0.1 bridge domain", [
          "payload.sentenceMediaType",
        ]);
      }
      const sentence = asRecord(claim.payload.sentence);
      const producerId = sentence?.producerId;
      const consumerId = sentence?.consumerId;
      const topic = sentence?.topic;
      if (
        typeof producerId !== "string" ||
        typeof consumerId !== "string" ||
        typeof topic !== "string"
      ) {
        return unmapped("The Hyper dependency sentence is malformed", ["payload.sentence"]);
      }
      const outputNodeId = mapping.producerNodes[producerId];
      const inputNodeId = mapping.consumerNodes[consumerId];
      const topicMapping = mapping.topics[topic];
      if (outputNodeId === undefined || inputNodeId === undefined || topicMapping === undefined) {
        return unmapped("The Hyper dependency has no declared aDNA mapping", [
          "payload.sentence.producerId",
          "payload.sentence.consumerId",
          "payload.sentence.topic",
        ]);
      }
      const { digest: _digest, attestations: _attestations, ...common } = claim;
      return {
        ok: true,
        value: sealArtifact({
          ...common,
          id: `${claim.id}:adna`,
          issuer: descriptor.issuer,
          payload: {
            ...claim.payload,
            profile: ADNA_PROFILE,
            signature: { id: "urn:lighthouse:signature:adna-lattice", version: "1.0.0" },
            sentenceMediaType: ADNA_PORT_CLAIM_MEDIA_TYPE,
            sentence: {
              outputNodeId,
              outputPort: topicMapping.outputPort,
              inputNodeId,
              inputPort: topicMapping.inputPort,
              valueType: topicMapping.valueType,
            },
            provenance: [...claim.payload.provenance, claim.digest],
          },
        }),
      };
    },
  };
}
