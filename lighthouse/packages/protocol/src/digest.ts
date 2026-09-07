import { createHash, timingSafeEqual } from "node:crypto";
import { canonicalize, type JsonValue } from "./json.js";

export interface Digest {
  algorithm: string;
  value: string;
}

export function digestJson(value: JsonValue): Digest {
  return {
    algorithm: "sha-256",
    value: createHash("sha256").update(canonicalize(value)).digest("hex"),
  };
}

export function verifyJsonDigest(value: JsonValue, expected: Digest): boolean {
  if (expected.algorithm !== "sha-256" || !/^[0-9a-f]{64}$/.test(expected.value)) {
    return false;
  }
  const actual = digestJson(value);
  return timingSafeEqual(Buffer.from(actual.value, "hex"), Buffer.from(expected.value, "hex"));
}
