import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { canonicalize, type JsonValue } from "@lighthouse/protocol";
import { parseLabelsDocument } from "./labels.js";
import { parsePreregistration } from "./preregistration.js";
import { runReferenceRecallProof } from "./reference.js";
import { exportCorpusDigest, runShadowEvaluation } from "./shadow.js";

export interface RecallCliIo {
  stdout(value: string): void;
  stderr(value: string): void;
}

const USAGE =
  "Usage: recall-proof proof --fixtures <path> | recall-proof shadow --preregistration <file> --export <file> --labels <file> | recall-proof digest --export <file>";

function emit(target: RecallCliIo["stdout"], value: JsonValue): void {
  target(`${canonicalize(value)}\n`);
}

function usage(io: RecallCliIo): number {
  emit(io.stderr, {
    ok: false,
    code: "USAGE",
    message: USAGE,
  });
  return 1;
}

function flag(args: string[], name: string): string | undefined {
  const index = args.indexOf(name);
  return index === -1 ? undefined : args[index + 1];
}

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await readFile(file, "utf8"));
}

async function runProof(args: string[], io: RecallCliIo): Promise<number> {
  const fixtures = flag(args, "--fixtures");
  if (args.length !== 2 || fixtures === undefined) return usage(io);
  try {
    const report = await runReferenceRecallProof(fixtures);
    emit(io.stdout, report as unknown as JsonValue);
    return report.passed ? 0 : 1;
  } catch (error) {
    emit(io.stderr, {
      ok: false,
      code: "RECALL_PROOF_FAILED",
      message: error instanceof Error ? error.message : String(error),
    });
    return 1;
  }
}

async function runShadow(args: string[], io: RecallCliIo): Promise<number> {
  const preregistrationFile = flag(args, "--preregistration");
  const exportFile = flag(args, "--export");
  const labelsFile = flag(args, "--labels");
  if (preregistrationFile === undefined) {
    emit(io.stderr, {
      ok: false,
      code: "PREREGISTRATION_REQUIRED",
      message: "shadow refuses to run without --preregistration <file>",
    });
    return 1;
  }
  if (exportFile === undefined || labelsFile === undefined) return usage(io);
  try {
    const report = runShadowEvaluation({
      exportDocument: await readJson(exportFile),
      labels: parseLabelsDocument(await readJson(labelsFile)),
      preregistration: parsePreregistration(await readJson(preregistrationFile)),
      issuedAt: new Date().toISOString(),
    });
    emit(io.stdout, report as unknown as JsonValue);
    return 0;
  } catch (error) {
    emit(io.stderr, {
      ok: false,
      code: "SHADOW_FAILED",
      message: error instanceof Error ? error.message : String(error),
    });
    return 1;
  }
}

async function runDigest(args: string[], io: RecallCliIo): Promise<number> {
  const exportFile = flag(args, "--export");
  if (args.length !== 2 || exportFile === undefined) return usage(io);
  try {
    const corpusDigest = exportCorpusDigest(await readJson(exportFile));
    emit(io.stdout, {
      corpusDigest: { algorithm: corpusDigest.algorithm, value: corpusDigest.value },
    });
    return 0;
  } catch (error) {
    emit(io.stderr, {
      ok: false,
      code: "DIGEST_FAILED",
      message: error instanceof Error ? error.message : String(error),
    });
    return 1;
  }
}

export async function runRecallCli(args: string[], io: RecallCliIo): Promise<number> {
  const [command, ...rest] = args;
  if (command === "proof") return runProof(rest, io);
  if (command === "shadow") return runShadow(rest, io);
  if (command === "digest") return runDigest(rest, io);
  return usage(io);
}

const entrypoint = process.argv[1];
if (entrypoint !== undefined && import.meta.url === pathToFileURL(entrypoint).href) {
  process.exitCode = await runRecallCli(process.argv.slice(2), {
    stdout: (value) => process.stdout.write(value),
    stderr: (value) => process.stderr.write(value),
  });
}
