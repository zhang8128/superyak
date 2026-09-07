export interface ConformanceDiagnostic {
  code: string;
  message: string;
}

export interface ConformanceCheck {
  id: string;
  status: "passed" | "failed";
  artifactDigests: string[];
  diagnostics: ConformanceDiagnostic[];
}

export interface ConformanceReport {
  protocolVersion: "0.1";
  profileIds: string[];
  bridgeDigest: string;
  passed: boolean;
  checks: ConformanceCheck[];
}
