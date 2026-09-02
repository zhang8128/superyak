#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { type AuthorizationRequest, evaluateConnectionPolicy } from "@lighthouse/calculus";
import {
  type ConnectionPolicy,
  canonicalize,
  type JsonValue,
  parseArtifact,
  verifyArtifactDigest,
} from "@lighthouse/protocol";
import { runRecallCli } from "@lighthouse/recall-evaluation";
import { runReferenceConformance } from "./reference.js";

export interface CliIo {
  stdout(text: string): void;
  stderr(text: string): void;
}

function emit(io: CliIo, channel: "stderr" | "stdout", value: unknown): void {
  io[channel](`${canonicalize(value as JsonValue)}\n`);
}

function usage(io: CliIo, message: string): number {
  emit(io, "stderr", { ok: false, code: "USAGE", message });
  return 2;
}

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await readFile(file, "utf8"));
}

async function runValidate(args: string[], io: CliIo): Promise<number> {
  const file = args[0];
  if (file === undefined || args.length !== 1) return usage(io, "validate requires one file");
  try {
    const artifact = parseArtifact(await readJson(file));
    const verification = verifyArtifactDigest(artifact);
    if (!verification.ok) {
      emit(io, "stderr", { ok: false, code: verification.code, id: artifact.id });
      return 1;
    }
    emit(io, "stdout", {
      ok: true,
      kind: artifact.kind,
      id: artifact.id,
      digest: artifact.digest,
    });
    return 0;
  } catch (error) {
    emit(io, "stderr", {
      ok: false,
      code: "SCHEMA_INVALID",
      message: error instanceof Error ? error.message : String(error),
    });
    return 1;
  }
}

async function runProof(args: string[], io: CliIo): Promise<number> {
  const fixturesIndex = args.indexOf("--fixtures");
  const fixtureRoot = fixturesIndex === -1 ? undefined : args[fixturesIndex + 1];
  if (fixtureRoot === undefined) return usage(io, "prove requires --fixtures <directory>");
  const report = await runReferenceConformance({
    fixtureRoot,
    invalidBridge: args.includes("--invalid-bridge"),
  });
  emit(io, "stdout", report);
  return report.passed ? 0 : 1;
}

const requestKeys = [
  "action",
  "at",
  "attestations",
  "audience",
  "claimMediaType",
  "context",
  "domain",
  "evidence",
  "profile",
  "publisher",
  "purpose",
] as const;

function parseAuthorizationRequest(value: unknown): AuthorizationRequest {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Authorization request must be an object");
  }
  const record = value as Record<string, unknown>;
  if (Object.keys(record).sort().join("\0") !== [...requestKeys].sort().join("\0")) {
    throw new Error("Authorization request has missing or unknown fields");
  }
  for (const key of requestKeys) {
    if (key === "evidence" || key === "attestations") continue;
    if (typeof record[key] !== "string" || record[key].length === 0) {
      throw new Error(`Authorization request ${key} must be a non-empty string`);
    }
  }
  if (
    !Array.isArray(record.evidence) ||
    !record.evidence.every((item) => typeof item === "string") ||
    !Array.isArray(record.attestations) ||
    !record.attestations.every((item) => typeof item === "string")
  ) {
    throw new Error("Authorization request evidence and attestations must be string arrays");
  }
  return record as unknown as AuthorizationRequest;
}

async function runAuthorize(args: string[], io: CliIo): Promise<number> {
  const policyFile = args[0];
  const requestFile = args[1];
  if (policyFile === undefined || requestFile === undefined || args.length !== 2) {
    return usage(io, "authorize requires <policy-file> <request-file>");
  }
  try {
    const artifact = parseArtifact(await readJson(policyFile));
    if (artifact.kind !== "ConnectionPolicy") throw new Error("Policy file has the wrong kind");
    if (!verifyArtifactDigest(artifact).ok) throw new Error("Policy digest does not verify");
    const policy: ConnectionPolicy = artifact;
    const request = parseAuthorizationRequest(await readJson(requestFile));
    const decision = evaluateConnectionPolicy(policy, request);
    emit(io, "stdout", decision);
    return decision.allowed ? 0 : 1;
  } catch (error) {
    emit(io, "stderr", {
      ok: false,
      code: "AUTHORIZATION_INPUT_INVALID",
      message: error instanceof Error ? error.message : String(error),
    });
    return 1;
  }
}

export async function runCli(args: string[], io: CliIo): Promise<number> {
  const [command, ...rest] = args;
  if (command === "validate") return runValidate(rest, io);
  if (command === "prove") return runProof(rest, io);
  if (command === "authorize") return runAuthorize(rest, io);
  if (command === "recall") {
    return runRecallCli(rest, { stdout: io.stdout, stderr: io.stderr });
  }
  return usage(io, "Expected validate, prove, authorize, or recall");
}

const entrypoint = process.argv[1];
if (entrypoint !== undefined && import.meta.url === pathToFileURL(entrypoint).href) {
  process.exitCode = await runCli(process.argv.slice(2), {
    stdout: (text) => process.stdout.write(text),
    stderr: (text) => process.stderr.write(text),
  });
}
