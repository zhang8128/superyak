import type { Claim, ContextRef, Evaluation, ProfileRef, Snapshot } from "@lighthouse/protocol";

export interface Obstruction {
  code: string;
  message: string;
  paths: string[];
}

export type OperationResult<T> = { ok: true; value: T } | { ok: false; obstruction: Obstruction };

export interface ProjectionRequest {
  root: string;
  id: string;
  issuer: string;
  issuedAt: string;
}

export interface InstitutionAdapter {
  readonly profile: ProfileRef;
  project(request: ProjectionRequest): Promise<Snapshot>;
  restrictSnapshot(snapshot: Snapshot, context: ContextRef): Promise<OperationResult<Snapshot>>;
  restrictClaim(claim: Claim, context: ContextRef): Promise<OperationResult<Claim>>;
  evaluate(snapshot: Snapshot, claim: Claim): Promise<Evaluation>;
}
