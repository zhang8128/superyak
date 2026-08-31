import path from "node:path";
import { describe, expect, it } from "vitest";
import { runRecallCli } from "../src/cli.js";

const fixtureRoot = path.resolve(import.meta.dirname, "../../../fixtures/engram");

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
      message: "Usage: recall-proof proof --fixtures <path>",
    });
  });
});
