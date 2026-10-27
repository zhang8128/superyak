"""Room moderators (docs/superpowers/specs/2026-10-27-room-moderators-design.md, M1 to M21): the owner of a room lets one
person in it, or one of his own ships in it, add and remove members. This module holds the act log's tables
(`member_changes`, `grant_origins`), and will hold making a moderate grant, choosing the grant an act spends, the
views and the make targets. members.py holds every membership change itself. The grant's shape, coverage and validity
are in grants.py."""

MODERATE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS member_changes(id TEXT PRIMARY KEY, grant_id TEXT REFERENCES grants(id),
  actor_id TEXT REFERENCES users(id), member_id TEXT NOT NULL,
  change TEXT NOT NULL CHECK (change IN ('add','remove')), room_id TEXT NOT NULL REFERENCES rooms(id),
  new_room_id TEXT REFERENCES rooms(id), earlier_rooms INTEGER NOT NULL DEFAULT 0,
  claims_released INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS member_changes_by_grant ON member_changes(grant_id, created);
CREATE TABLE IF NOT EXISTS grant_origins(grant_id TEXT PRIMARY KEY REFERENCES grants(id),
  made_via TEXT NOT NULL CHECK (made_via IN ('browser','cli')));
'''


class Moderators:
    """The moderate grant's tables, making, choosing and views (built up task by task)."""
