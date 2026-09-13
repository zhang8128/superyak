# Selected Gemma clinical/biotech baseline — September 13, 2026

The explicitly selected HauhauCS Gemma4 26B-A4B Balanced Q4_K_M answered all eight
fictional clinical/biotech prompts. Six passed exact term checks; no configured
blanket-refusal phrase appeared. This is a small engineering baseline and does
not establish clinical validity, medical readiness, or a training improvement.

The [tuning guide](../../tuning/README.md) gives reproducible commands. Exact
fixture prompts and expected checks live in
[clinical-biotech-cases.json](../../tuning/examples/clinical-biotech-cases.json).
They overlap the example training corpus and must not become a held-out metric.

| Case | Strict check | Observation |
| --- | --- | --- |
| Clinical lab extraction | Pass | Retained creatinine, 1.2 mg/dL and source ID |
| Patient-label correction | Pass | Applied P-102 correction and retained potassium/unit/source |
| Clinical timeline | Pass | Retained both dates, values and evidence IDs |
| Missing medication frequency | Pass | Reported MISSING, retained dose/route/source |
| Assay ratio | Pass | Reported 84/120 = 0.70 and did not infer efficacy |
| Sequencing QC | Miss | Correct 75.0% and 50.0% failed literal 75% and 50% checks |
| Experimental replication | Pass | Distinguished three technical replicates from one biological sample |
| Conflicting studies | Miss | Paraphrased “increased” as “increase”; added “significant” to the source's “no change” |

The QC miss is a scorer false negative. The conflict answer engaged with both
sources and uncertainty, but introduced statistical wording not supported by
the supplied record. These controller observations are not independent clinical
expert adjudication. Raw answers remain in a private local results receipt;
no actual patient or proprietary research data was used.

Source revision: `96c11c22b1128c3c8c655b21557b409f307c557f`.
Original GGUF SHA-256:
`f8b1da6dc139e6928159e536bc85602adbc1412018871732a878dedcad7ccafd`.
Ollama converted blob SHA-256:
`0f707492f57692c4aa27af100d1162c56ad8d67ddb773aec044be404ece2ba3f`.
Runtime manifest digest:
`964dccf2e808c93bda5236b30231b1e72cadd9f12336fb505471f49add9810c4`.
Local model: `superyak-clinical-gemma4-balanced:q4_k_m`.

Eight sequential requests used temperature 0, seed 20260913, context 8192,
512 predicted tokens maximum, thinking disabled, and the domain-specific system
instruction in the evaluator. Observed request times ranged from 0.577 to 8.407
seconds; total 15.934 seconds including the first request's model load. This is
not a sustained throughput benchmark. Runtime identity matched before and after.
The pre-existing peer demo model was not changed and Atlas remains stopped.

The implemented trainer separately passed real CPU optimizer/checkpoint/resume
checks using a tiny randomly initialized Gemma4 text model. That validates the
training mechanism only. Full-size GGUF materialization and Intel XPU training
remain unexecuted pending the Stampede3 connection and allocation details.
