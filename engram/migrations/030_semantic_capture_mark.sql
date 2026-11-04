-- The capture mark (fix:share-refuses-captured-memories). A semantic's links cannot say what it was built from:
-- compression links only the episodes similar to its summary, and moving an episode to cold storage cascades its
-- links away. So every writer stamps the semantic when it is made, reinforced or linked, in a column no cascade
-- touches: 1 when a captured prompt (an episode with source 'auto') was in its cluster or among its sources, 0 when
-- none was. It never goes down. No default: every row made before this migration reads NULL, meaning unknown, and
-- share refuses it.
ALTER TABLE semantics ADD COLUMN touched_capture INTEGER CHECK (touched_capture IN (0, 1));
