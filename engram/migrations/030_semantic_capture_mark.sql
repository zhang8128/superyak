-- The capture mark (fix:share-refuses-captured-memories). A semantic's links cannot say what it was built from:
-- compression links only the episodes similar to its summary, and moving an episode to cold storage cascades its
-- links away. So every writer stamps the semantic when it is made, reinforced or linked, in a column no cascade
-- touches: 1 when a captured prompt (an episode with source 'auto') was in its cluster or among its sources, 0 when
-- none was. It never goes down. No default: every row made before this migration reads NULL, meaning unknown, and
-- share refuses it.
ALTER TABLE semantics ADD COLUMN touched_capture INTEGER CHECK (touched_capture IN (0, 1));

-- Every link to a capture raises the mark, whichever code writes the link: a server still running code from before
-- this migration, or a future link path. The writers still mark the cluster episodes they never link, and copies of
-- a capture's text (matched by digest, which this trigger does not do).
--
-- A later migration that rebuilds `semantics` (015's pattern: create semantics_new, copy the rows, drop semantics,
-- rename semantics_new) must drop semantic_sources_mark_capture first and create it again after. While this trigger
-- names semantics, the rename fails: "error in trigger semantic_sources_mark_capture: no such table: main.semantics"
-- (checked on sqlite 3.53.1).
CREATE TRIGGER IF NOT EXISTS semantic_sources_mark_capture AFTER INSERT ON semantic_sources
WHEN EXISTS (SELECT 1 FROM episodes WHERE id = NEW.episode_id AND source = 'auto')
BEGIN
    UPDATE semantics SET touched_capture = 1 WHERE id = NEW.semantic_id;
END;
