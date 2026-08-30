import { z } from "zod";

const nonEmptyString = z.string().min(1);
const namespacedExtensionKey = z.string().regex(/^[A-Za-z][A-Za-z0-9+.-]*:/);

export const digestSchema = z
  .object({
    algorithm: nonEmptyString,
    value: nonEmptyString,
  })
  .strict();

export const attestationSchema = z
  .object({
    algorithm: nonEmptyString,
    keyId: nonEmptyString,
    signature: nonEmptyString,
  })
  .strict();

export const profileRefSchema = z
  .object({
    id: nonEmptyString,
    version: nonEmptyString,
    digest: digestSchema.optional(),
  })
  .strict();

export const signatureRefSchema = z
  .object({
    id: nonEmptyString,
    version: nonEmptyString,
    digest: digestSchema.optional(),
  })
  .strict();

export const contextRefSchema = z
  .object({
    id: nonEmptyString,
    path: z.array(nonEmptyString),
  })
  .strict();

export const evaluationSchema = z.enum(["satisfied", "violated", "indeterminate"]);
export const witnessOutcomeSchema = z.enum([
  "preserved",
  "partial",
  "approximate",
  "unmapped",
  "conflict",
  "invalid",
]);
export const fidelitySchema = z.enum(["exact", "partial", "approximate"]);
export const artifactKindSchema = z.enum([
  "LighthouseDescriptor",
  "Snapshot",
  "Claim",
  "BridgeDescriptor",
  "TranslationWitness",
  "ConnectionPolicy",
]);

const descriptorPayloadSchema = z
  .object({
    name: nonEmptyString,
    protocolVersions: z.array(nonEmptyString).min(1),
    profiles: z.array(profileRefSchema),
    actions: z.array(nonEmptyString),
    artifactEndpoints: z.array(
      z.object({ kind: artifactKindSchema, locator: nonEmptyString }).strict(),
    ),
  })
  .strict();

const snapshotPayloadSchema = z
  .object({
    profile: profileRefSchema,
    signature: signatureRefSchema,
    context: contextRefSchema,
    model: z.json(),
    lineage: z.array(digestSchema),
  })
  .strict();

const claimPayloadSchema = z
  .object({
    profile: profileRefSchema,
    signature: signatureRefSchema,
    context: contextRefSchema,
    sentenceMediaType: nonEmptyString,
    sentence: z.json(),
    snapshotDigests: z.array(digestSchema),
    provenance: z.array(digestSchema),
    validFrom: z.iso.datetime({ offset: true }).optional(),
    validUntil: z.iso.datetime({ offset: true }).optional(),
  })
  .strict();

const approximationSchema = z
  .object({
    metric: nonEmptyString,
    tolerance: z.number().finite().nonnegative(),
    evidenceProcedure: nonEmptyString,
  })
  .strict();

const bridgePayloadSchema = z
  .object({
    source: profileRefSchema,
    target: profileRefSchema,
    domain: z
      .object({
        contexts: z.array(nonEmptyString).min(1),
        claimMediaTypes: z.array(nonEmptyString).min(1),
      })
      .strict(),
    fidelity: fidelitySchema,
    implementation: nonEmptyString,
    dependencies: z.array(digestSchema),
    approximation: approximationSchema.optional(),
  })
  .strict()
  .superRefine((payload, context) => {
    if (payload.fidelity === "approximate" && payload.approximation === undefined) {
      context.addIssue({
        code: "custom",
        message: "approximation is required when fidelity is approximate",
        path: ["approximation"],
      });
    }
    if (payload.fidelity !== "approximate" && payload.approximation !== undefined) {
      context.addIssue({
        code: "custom",
        message: "approximation is only valid when fidelity is approximate",
        path: ["approximation"],
      });
    }
  });

const diagnosticSchema = z
  .object({
    code: nonEmptyString,
    message: nonEmptyString,
    paths: z.array(z.string()),
  })
  .strict();

const witnessPayloadSchema = z
  .object({
    sourceClaimDigest: digestSchema,
    targetClaimDigest: digestSchema.optional(),
    sourceSnapshotDigests: z.array(digestSchema),
    targetSnapshotDigests: z.array(digestSchema).optional(),
    bridgeDigest: digestSchema,
    bridgeLineage: z.array(digestSchema),
    outcome: witnessOutcomeSchema,
    mappedPaths: z.array(z.string()),
    unmappedPaths: z.array(z.string()),
    sourceEvaluation: evaluationSchema,
    targetEvaluation: evaluationSchema.optional(),
    evidenceDigests: z.array(digestSchema),
    approximation: approximationSchema.optional(),
    diagnostics: z.array(diagnosticSchema),
  })
  .strict();

const selectorList = z.array(nonEmptyString).min(1);
const policyRuleSchema = z
  .object({
    id: nonEmptyString,
    effect: z.enum(["allow", "deny"]),
    publishers: selectorList,
    profiles: selectorList,
    domains: selectorList,
    actions: selectorList,
    contexts: selectorList,
    claimMediaTypes: selectorList,
    purposes: selectorList,
    audiences: selectorList,
    validFrom: z.iso.datetime({ offset: true }),
    validUntil: z.iso.datetime({ offset: true }),
    requiredEvidence: z.array(nonEmptyString),
    requiredAttestations: z.array(nonEmptyString),
  })
  .strict();

const connectionPolicyPayloadSchema = z
  .object({
    rules: z.array(policyRuleSchema),
  })
  .strict();

const commonFields = {
  protocolVersion: z.literal("0.1"),
  id: nonEmptyString,
  issuedAt: z.iso.datetime({ offset: true }),
  issuer: nonEmptyString,
  payloadMediaType: nonEmptyString,
  attestations: z.array(attestationSchema).optional(),
  extensions: z.record(namespacedExtensionKey, z.json()).optional(),
};

function envelopeSchema<const Kind extends z.infer<typeof artifactKindSchema>, Payload extends z.ZodType>(
  kind: Kind,
  payload: Payload,
) {
  return z
    .object({
      ...commonFields,
      kind: z.literal(kind),
      payload,
      digest: digestSchema,
    })
    .strict();
}

function unsignedEnvelopeSchema<
  const Kind extends z.infer<typeof artifactKindSchema>,
  Payload extends z.ZodType,
>(kind: Kind, payload: Payload) {
  return z
    .object({
      ...commonFields,
      kind: z.literal(kind),
      payload,
    })
    .strict();
}

export const lighthouseDescriptorSchema = envelopeSchema(
  "LighthouseDescriptor",
  descriptorPayloadSchema,
);
export const snapshotSchema = envelopeSchema("Snapshot", snapshotPayloadSchema);
export const claimSchema = envelopeSchema("Claim", claimPayloadSchema);
export const bridgeDescriptorSchema = envelopeSchema("BridgeDescriptor", bridgePayloadSchema);
export const translationWitnessSchema = envelopeSchema(
  "TranslationWitness",
  witnessPayloadSchema,
);
export const connectionPolicySchema = envelopeSchema(
  "ConnectionPolicy",
  connectionPolicyPayloadSchema,
);

export const lighthouseArtifactSchema = z.discriminatedUnion("kind", [
  lighthouseDescriptorSchema,
  snapshotSchema,
  claimSchema,
  bridgeDescriptorSchema,
  translationWitnessSchema,
  connectionPolicySchema,
]);

export const unsignedArtifactSchema = z.discriminatedUnion("kind", [
  unsignedEnvelopeSchema("LighthouseDescriptor", descriptorPayloadSchema),
  unsignedEnvelopeSchema("Snapshot", snapshotPayloadSchema),
  unsignedEnvelopeSchema("Claim", claimPayloadSchema),
  unsignedEnvelopeSchema("BridgeDescriptor", bridgePayloadSchema),
  unsignedEnvelopeSchema("TranslationWitness", witnessPayloadSchema),
  unsignedEnvelopeSchema("ConnectionPolicy", connectionPolicyPayloadSchema),
]);

export type ProfileRef = z.infer<typeof profileRefSchema>;
export type SignatureRef = z.infer<typeof signatureRefSchema>;
export type ContextRef = z.infer<typeof contextRefSchema>;
export type Evaluation = z.infer<typeof evaluationSchema>;
export type WitnessOutcome = z.infer<typeof witnessOutcomeSchema>;
export type Fidelity = z.infer<typeof fidelitySchema>;
export type LighthouseDescriptor = z.infer<typeof lighthouseDescriptorSchema>;
export type Snapshot = z.infer<typeof snapshotSchema>;
export type Claim = z.infer<typeof claimSchema>;
export type BridgeDescriptor = z.infer<typeof bridgeDescriptorSchema>;
export type TranslationWitness = z.infer<typeof translationWitnessSchema>;
export type ConnectionPolicy = z.infer<typeof connectionPolicySchema>;
export type LighthouseArtifact = z.infer<typeof lighthouseArtifactSchema>;
export type UnsignedLighthouseArtifact = z.infer<typeof unsignedArtifactSchema>;
