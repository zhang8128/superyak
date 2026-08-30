export {
  type InstitutionAdapter,
  type Obstruction,
  type OperationResult,
  type ProjectionRequest,
} from "./adapter.js";
export {
  composeBridges,
  identityBridge,
  translateWithWitness,
  type BridgeEnvelopeMetadata,
  type RuntimeBridge,
  type TranslationResult,
} from "./bridge.js";
export {
  checkRestrictionComposition,
  checkRestrictionIdentity,
  isSubcontext,
  type LawCheck,
} from "./restriction.js";
