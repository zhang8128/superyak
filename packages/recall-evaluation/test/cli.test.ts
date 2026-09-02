import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { runRecallCli } from "../src/cli.js";
import {
  exportCorpusDigest,
  parseLabelsDocument,
  parsePreregistration,
  runShadowEvaluation,
} from "../src/index.js";

const fixtureRoot = path.resolve(import.meta.dirname, "../../../fixtures/engram");
const receiptsRoot = path.resolve(import.meta.dirname, "../../../fixtures/engram/receipts");

describe("recall proof CLI", () => {
  it("emits one passing machine-readable proof", async () => {
    const stdout: string[] = [];
    const stderr: string[] = [];

    const exitCode = await runRecallCli(["proof", "--fixtures", fixtureRoot], {
      stdout: (value) => stdout.push(value),
      stderr: (value) => stderr.push(value),
    });

    const report = JSON.parse(stdout.join(""));
    expect(exitCode).toBe(0);
    expect(stderr).toEqual([]);
    expect(stdout).toHaveLength(1);
    expect(stdout[0]?.endsWith("\n")).toBe(true);
    expect(report.passed).toBe(true);
    expect(report.checks).toHaveLength(14);
  });

  it("fails closed with a JSON usage diagnostic", async () => {
    const stdout: string[] = [];
    const stderr: string[] = [];

    const exitCode = await runRecallCli(["proof"], {
      stdout: (value) => stdout.push(value),
      stderr: (value) => stderr.push(value),
    });

    expect(exitCode).toBe(1);
    expect(stdout).toEqual([]);
    expect(JSON.parse(stderr.join(""))).toEqual({
      ok: false,
      code: "USAGE",
      message:
        "Usage: recall-proof proof --fixtures <path> | recall-proof shadow --preregistration <file> --export <file> --labels <file> | recall-proof digest --export <file>",
    });
  });

  it("runs a preregistered shadow evaluation", async () => {
    const stdout: string[] = [];
    const stderr: string[] = [];
    const exitCode = await runRecallCli(
      [
        "shadow",
        "--preregistration",
        path.join(receiptsRoot, "preregistration.json"),
        "--export",
        path.join(receiptsRoot, "receiver.engram.json"),
        "--labels",
        path.join(receiptsRoot, "receiver.labels.json"),
      ],
      { stdout: (value) => stdout.push(value), stderr: (value) => stderr.push(value) },
    );
    expect(exitCode).toBe(0);
    expect(stderr).toEqual([]);
    const report = JSON.parse(stdout.join(""));
    expect(report.kind).toBe("RecallShadowReport");
    expect(report.holdout.turns).toBe(2);
  });

  it("refuses to run shadow without a preregistration", async () => {
    const stderr: string[] = [];
    const exitCode = await runRecallCli(
      [
        "shadow",
        "--export",
        path.join(receiptsRoot, "receiver.engram.json"),
        "--labels",
        path.join(receiptsRoot, "receiver.labels.json"),
      ],
      { stdout: () => undefined, stderr: (value) => stderr.push(value) },
    );
    expect(exitCode).toBe(1);
    expect(JSON.parse(stderr.join("")).code).toBe("PREREGISTRATION_REQUIRED");
  });

  it("prints the corpus digest the shadow evaluation compares against", async () => {
    const exportFile = path.join(receiptsRoot, "receiver.engram.json");
    const stdout: string[] = [];
    const stderr: string[] = [];
    const exitCode = await runRecallCli(["digest", "--export", exportFile], {
      stdout: (value) => stdout.push(value),
      stderr: (value) => stderr.push(value),
    });
    expect(exitCode).toBe(0);
    expect(stderr).toEqual([]);
    expect(stdout).toHaveLength(1);
    const printed = JSON.parse(stdout[0] as string);
    expect(Object.keys(printed)).toEqual(["corpusDigest"]);

    const exportDocument = JSON.parse(await readFile(exportFile, "utf8"));
    const report = runShadowEvaluation({
      exportDocument,
      labels: parseLabelsDocument(
        JSON.parse(await readFile(path.join(receiptsRoot, "receiver.labels.json"), "utf8")),
      ),
      preregistration: parsePreregistration(
        JSON.parse(await readFile(path.join(receiptsRoot, "preregistration.json"), "utf8")),
      ),
      issuedAt: "2026-09-01T13:00:00Z",
    });
    expect(printed.corpusDigest).toEqual(report.corpusDigest);
    expect(printed.corpusDigest).toEqual(exportCorpusDigest(exportDocument));
  });

  it("emits scoped diagnostics when shadow or digest evaluation fails", async () => {
    const scratch = await mkdtemp(path.join(os.tmpdir(), "lighthouse-recall-cli-failures-"));
    const preregistration = JSON.parse(
      await readFile(path.join(receiptsRoot, "preregistration.json"), "utf8"),
    );
    preregistration.corpusDigest.value = "f".repeat(64);
    const mismatched = path.join(scratch, "preregistration.json");
    await writeFile(mismatched, JSON.stringify(preregistration));

    const shadowErrors: string[] = [];
    expect(
      await runRecallCli(
        [
          "shadow",
          "--preregistration",
          mismatched,
          "--export",
          path.join(receiptsRoot, "receiver.engram.json"),
          "--labels",
          path.join(receiptsRoot, "receiver.labels.json"),
        ],
        { stdout: () => undefined, stderr: (value) => shadowErrors.push(value) },
      ),
    ).toBe(1);
    expect(JSON.parse(shadowErrors.join(""))).toMatchObject({
      code: "SHADOW_FAILED",
      message: "CORPUS_DIGEST_MISMATCH",
    });

    const digestErrors: string[] = [];
    expect(
      await runRecallCli(["digest", "--export", path.join(receiptsRoot, "receiver.labels.json")], {
        stdout: () => undefined,
        stderr: (value) => digestErrors.push(value),
      }),
    ).toBe(1);
    expect(JSON.parse(digestErrors.join("")).code).toBe("DIGEST_FAILED");
  });
});
