-- 022: HOLA write-time innovation — per-episode distance from the compressed
-- (semantic) layer at write time. Feeds the compress-time core-promotion gate.
-- NULL = no signal (cold start / pre-migration). Spec:
-- docs/superpowers/specs/2026-07-07-hola-innovation-design.md
ALTER TABLE episodes ADD COLUMN innovation REAL;
