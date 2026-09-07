import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import {
  type AuthorizationRequest,
  evaluateConnectionPolicy,
} from "../packages/calculus/src/index.js";
import { parseArtifact, sealArtifact } from "../packages/protocol/src/artifacts.js";
import {
  canonicalize,
  compareCanonicalJson,
  type JsonValue,
} from "../packages/protocol/src/json.js";
import type { ConnectionPolicy } from "../packages/protocol/src/schemas.js";

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await readFile(file, "utf8"));
}

async function writeCanonical(file: string, value: JsonValue): Promise<void> {
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, `${canonicalize(value)}\n`);
}

export async function generatePolicyFixtures(root: string): Promise<void> {
  const policies = new Map<string, ConnectionPolicy>();
  const sourceDirectory = path.join(root, "sources");
  for (const file of (await readdir(sourceDirectory))
    .filter((f) => f.endsWith(".policy.json"))
    .sort(compareCanonicalJson)) {
    const name = file.slice(0, -".policy.json".length);
    const sealed = parseArtifact(
      sealArtifact((await readJson(path.join(sourceDirectory, file))) as never),
    );
    if (sealed.kind !== "ConnectionPolicy") throw new Error(`NOT_A_POLICY: ${file}`);
    policies.set(name, sealed);
    await writeCanonical(
      path.join(root, "policies", `${name}.json`),
      sealed as unknown as JsonValue,
    );
  }
  const requestDirectory = path.join(root, "requests");
  for (const file of (await readdir(requestDirectory))
    .filter((f) => f.endsWith(".json"))
    .sort(compareCanonicalJson)) {
    const name = file.slice(0, -".json".length);
    const document = (await readJson(path.join(requestDirectory, file))) as {
      policy: string;
      request: AuthorizationRequest;
    };
    const policy = policies.get(document.policy);
    if (policy === undefined) throw new Error(`UNKNOWN_POLICY: ${document.policy}`);
    const decision = evaluateConnectionPolicy(policy, document.request);
    await writeCanonical(path.join(root, "decisions", `${name}.json`), {
      policy: document.policy,
      request: name,
      decision: decision as unknown as JsonValue,
    });
  }
}

const entrypoint = process.argv[1];
if (entrypoint !== undefined && import.meta.url === pathToFileURL(entrypoint).href) {
  await generatePolicyFixtures(path.resolve("fixtures/policy-conformance"));
}
