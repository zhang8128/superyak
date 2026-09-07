export type {
  InstitutionAdapter,
  Obstruction,
  OperationResult,
  ProjectionRequest,
} from "./adapter.js";
export {
  type BridgeEnvelopeMetadata,
  composeBridges,
  identityBridge,
  type RuntimeBridge,
  type TranslationResult,
  translateWithWitness,
} from "./bridge.js";
export {
  type AuthorizationDecision,
  type AuthorizationRequest,
  evaluateConnectionPolicy,
} from "./policy.js";
export {
  checkRestrictionComposition,
  checkRestrictionIdentity,
  isSubcontext,
  type LawCheck,
} from "./restriction.js";
