import { digestJson, type JsonValue } from "@lighthouse/protocol";
import type { RecallSelectionReceipt, RecallSelectionReceiptContent } from "./types.js";

export function sealRecallReceipt(content: RecallSelectionReceiptContent): RecallSelectionReceipt {
  return {
    ...content,
    digest: digestJson(content as unknown as JsonValue),
  };
}
