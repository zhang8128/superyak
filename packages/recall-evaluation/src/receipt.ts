import {
  contextRefSchema,
  digestJson,
  digestSchema,
  type JsonValue,
  verifyJsonDigest,
} from "@lighthouse/protocol";
import { z } from "zod";
import type { RecallSelectionReceipt, RecallSelectionReceiptContent } from "./types.js";

const nonEmptyString = z.string().min(1);
const memoryRefSchema = z
  .object({
    publisher: nonEmptyString,
    memoryId: nonEmptyString,
  })
  .strict();

const rankedContributionSchema = z
  .object({
    ref: memoryRefSchema,
    contentDigest: digestSchema,
    sourceSnapshotDigest: digestSchema,
    rank: z.number().int().positive(),
    sourceWeight: z.number().finite().nonnegative(),
  })
  .strict();

const fusedCandidateSchema = z
  .object({
    ref: memoryRefSchema,
    contentDigest: digestSchema,
    score: z.number().finite().nonnegative(),
    contributions: z.array(rankedContributionSchema),
  })
  .strict();

const sourceDecisionSchema = z.union([
  z
    .object({
      publisher: nonEmptyString,
      role: z.literal("local"),
      allowed: z.literal(true),
      ruleId: z.literal("local:self"),
    })
    .strict(),
  z
    .object({
      publisher: nonEmptyString,
      role: z.literal("remote"),
      allowed: z.literal(true),
      ruleId: nonEmptyString,
    })
    .strict(),
  z
    .object({
      publisher: nonEmptyString,
      role: z.literal("remote"),
      allowed: z.literal(false),
      code: z.enum(["EXPLICIT_DENY", "NO_MATCHING_ALLOW", "OUTSIDE_VALIDITY"]),
      ruleId: nonEmptyString.optional(),
    })
    .strict(),
]);

const sourceAdmissionSchema = z
  .object({
    publisher: nonEmptyString,
    trace: z.enum(["matched", "absent", "context-mismatch"]),
    admission: z.enum([
      "admitted",
      "mode-excluded",
      "policy-denied",
      "zero-weight",
      "trace-unavailable",
    ]),
    candidateCount: z.number().int().nonnegative(),
  })
  .strict();

export const recallSelectionReceiptContentSchema = z
  .object({
    kind: z.literal("RecallSelectionReceipt"),
    version: z.literal("0.1"),
    experimentId: nonEmptyString,
    issuedAt: z.iso.datetime({ offset: true }),
    mode: z.enum(["local-only", "policy-scoped", "indiscriminate-control"]),
    turnId: nonEmptyString,
    action: z.literal("recall"),
    injected: z.literal(false),
    purpose: nonEmptyString,
    context: contextRefSchema,
    transformation: z.literal("weighted-rrf-v1"),
    selected: z.array(fusedCandidateSchema),
    sources: z.array(
      z
        .object({
          publisher: nonEmptyString,
          snapshotDigest: digestSchema,
          weight: z.number().finite().nonnegative(),
        })
        .strict(),
    ),
    decisions: z.array(sourceDecisionSchema),
    admissions: z.array(sourceAdmissionSchema),
  })
  .strict();

export const recallSelectionReceiptSchema = recallSelectionReceiptContentSchema.extend({
  digest: digestSchema,
});

export type RecallReceiptVerification =
  | { ok: true }
  | { ok: false; code: "INVALID_RECEIPT" | "DIGEST_MISMATCH" };

export function sealRecallReceipt(content: RecallSelectionReceiptContent): RecallSelectionReceipt {
  const parsed = recallSelectionReceiptContentSchema.parse(content);
  return {
    ...parsed,
    digest: digestJson(parsed as unknown as JsonValue),
  };
}

export function parseRecallReceipt(input: unknown): RecallSelectionReceipt {
  return recallSelectionReceiptSchema.parse(input);
}

export function verifyRecallReceiptDigest(input: unknown): RecallReceiptVerification {
  const parsed = recallSelectionReceiptSchema.safeParse(input);
  if (!parsed.success) return { ok: false, code: "INVALID_RECEIPT" };
  const { digest, ...content } = parsed.data;
  return verifyJsonDigest(content as unknown as JsonValue, digest)
    ? { ok: true }
    : { ok: false, code: "DIGEST_MISMATCH" };
}
