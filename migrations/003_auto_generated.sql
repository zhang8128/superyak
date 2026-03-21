-- Flag auto-generated semantics so recall can weight them lower
ALTER TABLE semantics ADD COLUMN auto_generated INTEGER DEFAULT 0;
