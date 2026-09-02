import { mkdtemp, readdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { canonicalize, compareCanonicalJson } from "@lighthouse/protocol";
import { describe, expect, it } from "vitest";
import { type CliIo, runCli } from "../src/cli.js";

const fixtureRoot = path.resolve(import.meta.dirname, "../../../fixtures");

function memoryIo() {
  const output = { stdout: "", stderr: "" };
  const io: CliIo = {
    stdout(text) {
      output.stdout += text;
    },
    stderr(text) {
      output.stderr += text;
    },
  };
  return { io, output };
}

describe("Lighthouse CLI", () => {
  it("returns zero and machine-readable JSON for the valid proof", async () => {
    const { io, output } = memoryIo();

    expect(await runCli(["prove", "--fixtures", fixtureRoot], io)).toBe(0);
    expect(JSON.parse(output.stdout)).toMatchObject({ passed: true, protocolVersion: "0.1" });
    expect(output.stderr).toBe("");
  });

  it("returns non-zero for invalid schema and digest", async () => {
    const temporary = await mkdtemp(path.join(os.tmpdir(), "lighthouse-cli-invalid-"));
    const invalidSchema = path.join(temporary, "invalid-schema.json");
    const invalidDigest = path.join(temporary, "invalid-digest.json");
    await writeFile(invalidSchema, "{}\n");
    const policy = JSON.parse(
      await readFile(path.join(fixtureRoot, "policy/workflow-policy.json"), "utf8"),
    );
    policy.digest.value = "0".repeat(64);
    await writeFile(invalidDigest, `${JSON.stringify(policy)}\n`);

    const schemaIo = memoryIo();
    const digestIo = memoryIo();
    expect(await runCli(["validate", invalidSchema], schemaIo.io)).toBe(1);
    expect(JSON.parse(schemaIo.output.stderr).code).toBe("SCHEMA_INVALID");
    expect(await runCli(["validate", invalidDigest], digestIo.io)).toBe(1);
    expect(JSON.parse(digestIo.output.stderr).code).toBe("DIGEST_MISMATCH");
  });

  it("returns non-zero when the candidate bridge fails a law", async () => {
    const { io, output } = memoryIo();

    expect(await runCli(["prove", "--fixtures", fixtureRoot, "--invalid-bridge"], io)).toBe(1);
    expect(JSON.parse(output.stdout).passed).toBe(false);
  });

  it("returns non-zero when local policy denies context injection", async () => {
    const { io, output } = memoryIo();

    expect(
      await runCli(
        [
          "authorize",
          path.join(fixtureRoot, "policy/workflow-policy.json"),
          path.join(fixtureRoot, "policy/inject-request.json"),
        ],
        io,
      ),
    ).toBe(1);
    expect(JSON.parse(output.stdout)).toEqual({
      allowed: false,
      code: "EXPLICIT_DENY",
      ruleId: "deny-crew-context-injection",
    });
  });

  it("writes decision fixtures byte-identical to what authorize prints", async () => {
    const root = path.resolve(import.meta.dirname, "../../../fixtures/policy-conformance");
    const policyFile = path.join(root, "policies", "local-city.json");
    const scratch = await mkdtemp(path.join(os.tmpdir(), "lighthouse-authorize-parity-"));
    const requests = (await readdir(path.join(root, "requests"))).sort(compareCanonicalJson);
    expect(requests).toHaveLength(14);
    for (const file of requests) {
      const document = JSON.parse(await readFile(path.join(root, "requests", file), "utf8"));
      const requestFile = path.join(scratch, file);
      await writeFile(requestFile, JSON.stringify(document.request));
      const out: string[] = [];
      await runCli(["authorize", policyFile, requestFile], {
        stdout: (text) => out.push(text),
        stderr: () => undefined,
      });
      const { decision } = JSON.parse(await readFile(path.join(root, "decisions", file), "utf8"));
      expect(out.join("")).toBe(`${canonicalize(decision)}\n`);
    }
  });

  it("routes recall subcommands and validates a RecallReceipt", async () => {
    const receiptsRoot = path.resolve(import.meta.dirname, "../../../fixtures/engram/receipts");
    const out: string[] = [];
    const err: string[] = [];
    const io = {
      stdout: (text: string) => out.push(text),
      stderr: (text: string) => err.push(text),
    };
    expect(await runCli(["validate", path.join(receiptsRoot, "injected-true.json")], io)).toBe(0);
    expect(JSON.parse(out[0] as string).kind).toBe("RecallReceipt");
    expect(
      await runCli(["validate", path.join(receiptsRoot, "invalid-injected-mismatch.json")], io),
    ).toBe(1);
    expect(JSON.parse(err[0] as string).code).toBe("SCHEMA_INVALID");
    expect(await runCli(["recall", "shadow"], io)).toBe(1);
    expect(JSON.parse(err[1] as string).code).toBe("PREREGISTRATION_REQUIRED");
  });
});
