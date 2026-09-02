import { compareCanonicalJson, contextRefSchema } from "@lighthouse/protocol";
import { z } from "zod";
import type { RecallTurnJudgment } from "./types.js";

const nonEmptyString = z.string().min(1);
const memoryRefSchema = z.object({ publisher: nonEmptyString, memoryId: nonEmptyString }).strict();

const labelTurnSchema = z
  .object({
    turnId: nonEmptyString,
    context: contextRefSchema,
    purpose: nonEmptyString,
    relevant: z.array(memoryRefSchema),
    forbidden: z.array(memoryRefSchema),
  })
  .strict();

const labelsDocumentSchema = z
  .object({
    formatVersion: z.literal("1.0"),
    instance: nonEmptyString,
    turns: z.array(labelTurnSchema),
  })
  .strict();

export interface LabelsDocument {
  formatVersion: "1.0";
  instance: string;
  turns: RecallTurnJudgment[];
}

export function parseLabelsDocument(input: unknown): LabelsDocument {
  const parsed = labelsDocumentSchema.parse(input);
  const keys = new Set<string>();
  for (const turn of parsed.turns) {
    const key = JSON.stringify([turn.turnId, turn.context.id]);
    if (keys.has(key)) throw new Error(`DUPLICATE_LABEL_TURN: ${turn.turnId}`);
    keys.add(key);
    if (turn.relevant.length === 0) throw new Error(`EMPTY_RELEVANCE_JUDGMENT: ${turn.turnId}`);
  }
  return {
    formatVersion: parsed.formatVersion,
    instance: parsed.instance,
    turns: parsed.turns.toSorted((left, right) =>
      compareCanonicalJson([left.turnId, left.context.id], [right.turnId, right.context.id]),
    ),
  };
}
