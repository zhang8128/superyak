import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { z } from "zod";
import { canonicalize, type JsonValue } from "../packages/protocol/src/json.js";
import {
  bridgeDescriptorSchema,
  claimSchema,
  connectionPolicySchema,
  lighthouseDescriptorSchema,
  snapshotSchema,
  translationWitnessSchema,
} from "../packages/protocol/src/schemas.js";

const schemaEntries = [
  ["bridge-descriptor.schema.json", bridgeDescriptorSchema],
  ["claim.schema.json", claimSchema],
  ["connection-policy.schema.json", connectionPolicySchema],
  ["lighthouse-descriptor.schema.json", lighthouseDescriptorSchema],
  ["snapshot.schema.json", snapshotSchema],
  ["translation-witness.schema.json", translationWitnessSchema],
] as const;

function addBridgeFidelityRules(schema: JsonValue): JsonValue {
  const document = schema as { [key: string]: JsonValue };
  const properties = document.properties as { [key: string]: JsonValue };
  const payload = properties.payload as { [key: string]: JsonValue };
  payload.allOf = [
    {
      if: {
        properties: { fidelity: { const: "approximate" } },
        required: ["fidelity"],
      },
      // biome-ignore lint/suspicious/noThenProperty: `then` is a required JSON Schema keyword.
      then: { required: ["approximation"] },
    },
    {
      if: {
        properties: { fidelity: { enum: ["exact", "partial"] } },
        required: ["fidelity"],
      },
      // biome-ignore lint/suspicious/noThenProperty: `then` is a required JSON Schema keyword.
      then: { not: { required: ["approximation"] } },
    },
  ];
  return document;
}

export async function generateSchemas(outputDirectory: string): Promise<void> {
  await mkdir(outputDirectory, { recursive: true });
  for (const [file, schema] of schemaEntries) {
    const generated = z.toJSONSchema(schema) as JsonValue;
    const jsonSchema =
      file === "bridge-descriptor.schema.json" ? addBridgeFidelityRules(generated) : generated;
    await writeFile(path.join(outputDirectory, file), `${canonicalize(jsonSchema)}\n`);
  }
}

const entrypoint = process.argv[1];
if (entrypoint !== undefined && import.meta.url === pathToFileURL(entrypoint).href) {
  await generateSchemas(path.resolve("schemas"));
}
