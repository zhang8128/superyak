import { canonicalize, type ContextRef, type JsonValue, type Snapshot } from "@lighthouse/protocol";
import type { InstitutionAdapter, Obstruction } from "./adapter.js";

export type LawCheck =
  | { passed: true }
  | { passed: false; diagnostics: Array<{ code: string; message: string }> };

export function isSubcontext(parent: ContextRef, child: ContextRef): boolean {
  return parent.path.every((segment, index) => child.path[index] === segment);
}

function semanticProjection(snapshot: Snapshot): JsonValue {
  const projection = {
    profile: snapshot.payload.profile,
    signature: snapshot.payload.signature,
    context: snapshot.payload.context,
    model: snapshot.payload.model,
  };
  return projection as unknown as JsonValue;
}

function failedLaw(code: string, message: string): LawCheck {
  return { passed: false, diagnostics: [{ code, message }] };
}

function obstructionMessage(obstruction: Obstruction): string {
  return `${obstruction.code}: ${obstruction.message}`;
}

export async function checkRestrictionIdentity(
  adapter: InstitutionAdapter,
  snapshot: Snapshot,
): Promise<LawCheck> {
  const restricted = await adapter.restrictSnapshot(snapshot, snapshot.payload.context);
  if (!restricted.ok) {
    return failedLaw("RESTRICTION_IDENTITY_OBSTRUCTED", obstructionMessage(restricted.obstruction));
  }
  return canonicalize(semanticProjection(restricted.value)) === canonicalize(semanticProjection(snapshot))
    ? { passed: true }
    : failedLaw("RESTRICTION_IDENTITY_FAILED", "Identity restriction changed the semantic model");
}

export async function checkRestrictionComposition(
  adapter: InstitutionAdapter,
  snapshot: Snapshot,
  middle: ContextRef,
  inner: ContextRef,
): Promise<LawCheck> {
  const first = await adapter.restrictSnapshot(snapshot, middle);
  if (!first.ok) {
    return failedLaw("RESTRICTION_FIRST_STEP_OBSTRUCTED", obstructionMessage(first.obstruction));
  }
  const composed = await adapter.restrictSnapshot(first.value, inner);
  if (!composed.ok) {
    return failedLaw("RESTRICTION_SECOND_STEP_OBSTRUCTED", obstructionMessage(composed.obstruction));
  }
  const direct = await adapter.restrictSnapshot(snapshot, inner);
  if (!direct.ok) {
    return failedLaw("RESTRICTION_DIRECT_STEP_OBSTRUCTED", obstructionMessage(direct.obstruction));
  }
  return canonicalize(semanticProjection(composed.value)) ===
    canonicalize(semanticProjection(direct.value))
    ? { passed: true }
    : failedLaw(
        "RESTRICTION_COMPOSITION_FAILED",
        "Two-step restriction differs from direct restriction",
      );
}
