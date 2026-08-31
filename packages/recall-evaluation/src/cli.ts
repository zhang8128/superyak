import { pathToFileURL } from "node:url";
import { canonicalize, type JsonValue } from "@lighthouse/protocol";
import { runReferenceRecallProof } from "./reference.js";

export interface RecallCliIo {
  stdout(value: string): void;
  stderr(value: string): void;
}

function emit(target: RecallCliIo["stdout"], value: JsonValue): void {
  target(`${canonicalize(value)}\n`);
}

function usage(io: RecallCliIo): number {
  emit(io.stderr, {
    ok: false,
    code: "USAGE",
    message: "Usage: recall-proof proof --fixtures <path>",
  });
  return 1;
}

export async function runRecallCli(args: string[], io: RecallCliIo): Promise<number> {
  if (args.length !== 3 || args[0] !== "proof" || args[1] !== "--fixtures" || !args[2]) {
    return usage(io);
  }
  try {
    const report = await runReferenceRecallProof(args[2]);
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

const entrypoint = process.argv[1];
if (entrypoint !== undefined && import.meta.url === pathToFileURL(entrypoint).href) {
  process.exitCode = await runRecallCli(process.argv.slice(2), {
    stdout: (value) => process.stdout.write(value),
    stderr: (value) => process.stderr.write(value),
  });
}
