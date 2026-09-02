import { cp, mkdtemp, readdir, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { compareCanonicalJson } from "@lighthouse/protocol";
import { describe, expect, it } from "vitest";
import { generatePolicyFixtures } from "../../../scripts/generate-policy-fixtures.js";

const root = path.resolve(import.meta.dirname, "../../../fixtures/policy-conformance");

async function readDecision(directory: string, name: string) {
  return JSON.parse(await readFile(path.join(directory, "decisions", `${name}.json`), "utf8"));
}

describe("policy conformance fixtures", () => {
  it("regenerates byte-identically from sources and requests", async () => {
    const scratch = await mkdtemp(path.join(os.tmpdir(), "lighthouse-policy-fixtures-"));
    await cp(path.join(root, "sources"), path.join(scratch, "sources"), { recursive: true });
    await cp(path.join(root, "requests"), path.join(scratch, "requests"), { recursive: true });
    await generatePolicyFixtures(scratch);
    for (const directory of ["policies", "decisions"]) {
      const files = (await readdir(path.join(root, directory))).sort(compareCanonicalJson);
      expect((await readdir(path.join(scratch, directory))).sort(compareCanonicalJson)).toEqual(
        files,
      );
      for (const file of files) {
        expect(await readFile(path.join(scratch, directory, file), "utf8")).toBe(
          await readFile(path.join(root, directory, file), "utf8"),
        );
      }
    }
  });

  it("covers the required decision cases", async () => {
    expect((await readDecision(root, "no-matching-allow")).decision).toEqual({
      allowed: false,
      code: "NO_MATCHING_ALLOW",
    });
    expect((await readDecision(root, "explicit-deny")).decision).toEqual({
      allowed: false,
      code: "EXPLICIT_DENY",
      ruleId: "deny-blocks-inject",
    });
    expect((await readDecision(root, "deny-wins-specificity-tie")).decision).toEqual({
      allowed: false,
      code: "EXPLICIT_DENY",
      ruleId: "deny-agi-technical",
    });
    expect((await readDecision(root, "exact-beats-prefix")).decision).toEqual({
      allowed: true,
      ruleId: "allow-gil-technical-exact",
    });
    expect((await readDecision(root, "outside-validity")).decision).toEqual({
      allowed: false,
      code: "OUTSIDE_VALIDITY",
    });
    expect((await readDecision(root, "non-transitive-claw")).decision).toEqual({
      allowed: false,
      code: "NO_MATCHING_ALLOW",
    });
    expect((await readDecision(root, "action-recall")).decision.allowed).toBe(true);
    for (const action of ["read", "suggest", "derive", "retain", "reshare"]) {
      expect((await readDecision(root, `action-${action}`)).decision).toEqual({
        allowed: false,
        code: "NO_MATCHING_ALLOW",
      });
    }
    expect((await readDecision(root, "action-inject-context")).decision.code).toBe("EXPLICIT_DENY");
    expect((await readdir(path.join(root, "decisions"))).length).toBe(14);
  });
});
