import { compareCanonicalJson, digestSchema } from "@lighthouse/protocol";
import { z } from "zod";

const nonEmptyString = z.string().min(1);

const preregistrationSchema = z
  .object({
    receiverPublisher: nonEmptyString,
    corpusDigest: digestSchema.refine((digest) => digest.algorithm === "sha-256"),
    holdoutTurnIds: z.array(nonEmptyString).min(1),
    cutoff: z.number().int().positive(),
    metrics: z.tuple([z.literal("rightTurnRecall"), z.literal("nDCG")]),
    bootstrap: z
      .object({
        samples: z.number().int().positive(),
        seed: z.number().int().nonnegative(),
      })
      .strict(),
  })
  .strict();

export type Preregistration = z.infer<typeof preregistrationSchema>;

export function parsePreregistration(input: unknown): Preregistration {
  const parsed = preregistrationSchema.parse(input);
  const seen = new Set<string>();
  for (const turnId of parsed.holdoutTurnIds) {
    if (seen.has(turnId)) throw new Error(`DUPLICATE_HOLDOUT_TURN: ${turnId}`);
    seen.add(turnId);
  }
  return {
    ...parsed,
    holdoutTurnIds: parsed.holdoutTurnIds.toSorted(compareCanonicalJson),
  };
}
