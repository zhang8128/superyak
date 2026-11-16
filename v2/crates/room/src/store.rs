use std::fs::{File, OpenOptions};
use std::path::Path;

use rusqlite::{Connection, OpenFlags};

use crate::{
    ItemId, ItemState, Room, RoomError,
    item::{item_view, parse},
    limits,
    offer::{OFFERS_COLUMNS, OFFERS_TABLE},
};

const SCHEMA: &str = "
CREATE TABLE meta (
    schema_version INTEGER NOT NULL,
    daily_turns INTEGER NOT NULL,
    concurrent INTEGER NOT NULL
);
CREATE TABLE items (
    ordinal INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    repo TEXT NOT NULL,
    base_commit TEXT NOT NULL,
    after_ids TEXT NOT NULL,
    state TEXT NOT NULL,
    lease_no INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE checks (
    item TEXT PRIMARY KEY REFERENCES items(id),
    spec TEXT NOT NULL,
    frozen TEXT
);
CREATE TABLE attempts (
    id TEXT PRIMARY KEY,
    item TEXT NOT NULL REFERENCES items(id),
    lease_no INTEGER NOT NULL,
    worker TEXT NOT NULL,
    started INTEGER NOT NULL,
    expires INTEGER NOT NULL,
    state TEXT NOT NULL,
    submitted_commit TEXT,
    UNIQUE(item, lease_no)
);
CREATE TABLE steps (
    attempt TEXT NOT NULL REFERENCES attempts(id),
    seq INTEGER NOT NULL,
    tool TEXT NOT NULL,
    target TEXT NOT NULL,
    path TEXT,
    blob TEXT,
    ok INTEGER NOT NULL,
    tokens_in INTEGER,
    tokens_out INTEGER,
    seen_ms INTEGER,
    result_ms INTEGER,
    PRIMARY KEY(attempt, seq)
);
CREATE TABLE verdicts (
    attempt TEXT PRIMARY KEY REFERENCES attempts(id),
    passed INTEGER NOT NULL,
    exit_code INTEGER NOT NULL,
    timed_out INTEGER NOT NULL,
    artifact TEXT NOT NULL,
    check_hash TEXT NOT NULL,
    output_sha256 TEXT NOT NULL,
    recorded INTEGER NOT NULL
);
CREATE TABLE step_files (attempt TEXT NOT NULL, seq INTEGER NOT NULL, ordinal INTEGER NOT NULL,
    path TEXT NOT NULL, blob TEXT NOT NULL, PRIMARY KEY(attempt, seq, ordinal),
    FOREIGN KEY(attempt, seq) REFERENCES steps(attempt, seq));
CREATE TABLE measured (attempt TEXT PRIMARY KEY REFERENCES attempts(id), ended TEXT NOT NULL,
    exit_code INTEGER, tokens_complete INTEGER NOT NULL, fresh_in INTEGER, cache_write INTEGER,
    cache_read INTEGER, output INTEGER, reasoning INTEGER, steps_seen INTEGER NOT NULL,
    unknown_steps INTEGER NOT NULL, unknown_changes INTEGER NOT NULL, sandbox_ms INTEGER NOT NULL,
    worker_ms INTEGER NOT NULL,
    seal_ms INTEGER NOT NULL, bring_ms INTEGER NOT NULL, check_ms INTEGER, recheck_ms INTEGER,
    active_ms INTEGER NOT NULL);
CREATE TABLE changes (attempt TEXT NOT NULL REFERENCES attempts(id), ordinal INTEGER NOT NULL,
    path TEXT NOT NULL, change TEXT NOT NULL, PRIMARY KEY(attempt, ordinal));
CREATE TABLE budget_days (day INTEGER PRIMARY KEY, used INTEGER NOT NULL);
CREATE TABLE disagreements (
    ordinal INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    item TEXT NOT NULL REFERENCES items(id),
    detail TEXT NOT NULL,
    UNIQUE(kind, item)
);
";

const MIGRATE_V1: &str = r#"CREATE TABLE step_files (attempt TEXT NOT NULL, seq INTEGER NOT NULL, ordinal INTEGER NOT NULL,
    path TEXT NOT NULL, blob TEXT NOT NULL, PRIMARY KEY(attempt, seq, ordinal),
    FOREIGN KEY(attempt, seq) REFERENCES steps(attempt, seq));
CREATE TABLE measured (attempt TEXT PRIMARY KEY REFERENCES attempts(id), ended TEXT NOT NULL,
    exit_code INTEGER, tokens_complete INTEGER NOT NULL, fresh_in INTEGER, cache_write INTEGER,
    cache_read INTEGER, output INTEGER, reasoning INTEGER, steps_seen INTEGER NOT NULL,
    unknown_steps INTEGER NOT NULL, unknown_changes INTEGER NOT NULL, sandbox_ms INTEGER NOT NULL,
    worker_ms INTEGER NOT NULL,
    seal_ms INTEGER NOT NULL, bring_ms INTEGER NOT NULL, check_ms INTEGER, recheck_ms INTEGER,
    active_ms INTEGER NOT NULL);
CREATE TABLE changes (attempt TEXT NOT NULL REFERENCES attempts(id), ordinal INTEGER NOT NULL,
    path TEXT NOT NULL, change TEXT NOT NULL, PRIMARY KEY(attempt, ordinal));
ALTER TABLE steps ADD COLUMN seen_ms INTEGER;
ALTER TABLE steps ADD COLUMN result_ms INTEGER;
UPDATE meta SET schema_version=2;
"#;

/// From version 2 to 3: what each turn was offered (`offer::OFFERS_TABLE`), and nothing else.
const MIGRATE_V2: &str = "UPDATE meta SET schema_version=3;";

impl Room {
    /// Create a new room; never replace an existing store, including a damaged one.
    pub fn init(dir: &Path) -> Result<Self, RoomError> {
        let path = dir.join("room.sqlite3");
        if path.exists() {
            return Err(RoomError::Refused("the room already exists".into()));
        }
        std::fs::create_dir_all(dir).map_err(db)?;
        let lock = writer_lock(dir)?;
        // Claim the pathname atomically after acquiring the writer lock.
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .map_err(|e| RoomError::Refused(format!("cannot create room: {e}")))?;
        let mut conn =
            Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_WRITE).map_err(db)?;
        configure(&conn)?;
        let tx = conn.transaction().map_err(db)?;
        tx.execute_batch(SCHEMA).map_err(db)?;
        tx.execute_batch(OFFERS_TABLE).map_err(db)?;
        tx.execute(
            "INSERT INTO meta VALUES (?1, ?2, ?3)",
            (
                limits::SCHEMA_VERSION,
                limits::DAILY_TURNS,
                limits::CONCURRENT_TURNS,
            ),
        )
        .map_err(db)?;
        tx.commit().map_err(db)?;
        Ok(Self {
            conn,
            dir: dir.into(),
            _lock: Some(lock),
            lease_secs: limits::LEASE_SECS,
            offers: true,
        })
    }

    /// Open an existing valid room for writing, without ever creating a database.
    pub fn open(dir: &Path) -> Result<Self, RoomError> {
        Self::open_existing(dir, false)
    }

    /// Readers neither acquire the room writer lock nor enable writable SQLite flags.
    pub fn open_read_only(dir: &Path) -> Result<Self, RoomError> {
        Self::open_existing(dir, true)
    }

    fn open_existing(dir: &Path, read_only: bool) -> Result<Self, RoomError> {
        let path = dir.join("room.sqlite3");
        if !path.exists() {
            return Err(RoomError::Missing(path));
        }
        let lock = if read_only {
            None
        } else {
            Some(writer_lock(dir)?)
        };
        let flags = if read_only {
            OpenFlags::SQLITE_OPEN_READ_ONLY
        } else {
            OpenFlags::SQLITE_OPEN_READ_WRITE
        };
        let mut conn = Connection::open_with_flags(path, flags).map_err(damaged)?;
        let version = validate(&conn)?;
        // The room's settings hold for everything this connection writes, the migration first of all.
        if !read_only {
            configure(&conn)?;
        }
        // A store of version 2 lacks only what turns were offered. Read as it is, every turn of it reads as
        // given nothing recorded; opened for writing, it is brought forward.
        let offers = if version == limits::SCHEMA_VERSION {
            true
        } else if read_only {
            if version == 1 {
                return Err(RoomError::OlderSchema {
                    found: 1,
                    known: limits::SCHEMA_VERSION,
                });
            }
            false
        } else {
            let tx = conn
                .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
                .map_err(db)?;
            if version == 1 {
                tx.execute_batch(MIGRATE_V1).map_err(db)?;
            }
            tx.execute_batch(OFFERS_TABLE).map_err(db)?;
            tx.execute_batch(MIGRATE_V2).map_err(db)?;
            validate(&tx)?;
            tx.commit().map_err(db)?;
            true
        };
        Ok(Self {
            conn,
            dir: dir.into(),
            _lock: lock,
            lease_secs: limits::LEASE_SECS,
            offers,
        })
    }

    /// The room-owned checks, turn directories and stop file live below this path.
    pub fn dir(&self) -> &Path {
        &self.dir
    }

    /// Remove an idle item and its history, overwriting deleted content and truncating the WAL.
    /// A checkpoint error can occur after the deletion commits; it must not be treated as erasure.
    pub fn erase_item(&mut self, id: &ItemId) -> Result<(), RoomError> {
        let tx = self.conn.transaction().map_err(db)?;
        let view = item_view(&tx, id)?;
        if matches!(view.state, ItemState::Leased | ItemState::Checking) {
            return Err(RoomError::Refused("a running item cannot be erased".into()));
        }
        // An item that others wait on stays: removing it would leave them blocked for good, and
        // dropping it from their lists would let work start whose condition was never met.
        let waiting = {
            let mut q = tx
                .prepare("SELECT id,after_ids FROM items WHERE id<>?1 ORDER BY ordinal")
                .map_err(db)?;
            let rows = q
                .query_map([&id.0], |r| {
                    Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
                })
                .map_err(db)?
                .collect::<Result<Vec<_>, _>>()
                .map_err(db)?;
            let mut waiting = Vec::new();
            for (other, after) in rows {
                if parse::<Vec<ItemId>>(&after)?.contains(id) {
                    waiting.push(other);
                }
            }
            waiting
        };
        if !waiting.is_empty() {
            return Err(RoomError::Refused(format!(
                "erase what waits on this item first: {}",
                waiting.join(", ")
            )));
        }
        tx.pragma_update(None, "secure_delete", true).map_err(db)?;
        for sql in [
            "DELETE FROM offers WHERE attempt IN (SELECT id FROM attempts WHERE item=?1)",
            "DELETE FROM step_files WHERE attempt IN (SELECT id FROM attempts WHERE item=?1)",
            "DELETE FROM measured WHERE attempt IN (SELECT id FROM attempts WHERE item=?1)",
            "DELETE FROM changes WHERE attempt IN (SELECT id FROM attempts WHERE item=?1)",
            "DELETE FROM steps WHERE attempt IN (SELECT id FROM attempts WHERE item=?1)",
            "DELETE FROM verdicts WHERE attempt IN (SELECT id FROM attempts WHERE item=?1)",
            "DELETE FROM attempts WHERE item=?1",
            "DELETE FROM checks WHERE item=?1",
            "DELETE FROM disagreements WHERE item=?1",
            "DELETE FROM items WHERE id=?1",
        ] {
            tx.execute(sql, [&id.0]).map_err(db)?;
        }
        tx.commit().map_err(db)?;
        let busy: u32 = self
            .conn
            .query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |r| r.get(0))
            .map_err(db)?;
        if busy != 0 {
            return Err(RoomError::Db(
                "item deleted, but a busy WAL checkpoint prevented complete erasure".into(),
            ));
        }
        Ok(())
    }
}

fn writer_lock(dir: &Path) -> Result<File, RoomError> {
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(dir.join("LOCK"))
        .map_err(db)?;
    lock.try_lock().map_err(|e| match e {
        std::fs::TryLockError::WouldBlock => RoomError::Locked,
        std::fs::TryLockError::Error(e) => db(e),
    })?;
    Ok(lock)
}

fn configure(conn: &Connection) -> Result<(), RoomError> {
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;")
        .map_err(db)
}

fn validate(conn: &Connection) -> Result<u32, RoomError> {
    let integrity: String = conn
        .query_row("PRAGMA integrity_check", [], |r| r.get(0))
        .map_err(damaged)?;
    if integrity != "ok" {
        return Err(RoomError::Damaged(integrity));
    }
    let version: u32 = conn
        .query_row("SELECT schema_version FROM meta", [], |r| r.get(0))
        .map_err(damaged)?;
    if version > limits::SCHEMA_VERSION {
        return Err(RoomError::NewerSchema {
            found: version,
            known: limits::SCHEMA_VERSION,
        });
    }
    if version == 0 {
        return Err(RoomError::Damaged(format!(
            "unsupported schema version {version}"
        )));
    }
    let count: u32 = conn
        .query_row("SELECT count(*) FROM meta", [], |r| r.get(0))
        .map_err(damaged)?;
    if count != 1 {
        return Err(RoomError::Damaged(
            "expected exactly one metadata row".into(),
        ));
    }
    // Prepare against every table and column before accepting or migrating a store.
    for query in [
        "SELECT schema_version, daily_turns, concurrent FROM meta",
        "SELECT ordinal,id,title,repo,base_commit,after_ids,state,lease_no,attempts FROM items",
        "SELECT item,spec,frozen FROM checks",
        "SELECT id,item,lease_no,worker,started,expires,state,submitted_commit FROM attempts",
        "SELECT attempt,seq,tool,target,path,blob,ok,tokens_in,tokens_out FROM steps",
        "SELECT attempt,passed,exit_code,timed_out,artifact,check_hash,output_sha256,recorded FROM verdicts",
        "SELECT day,used FROM budget_days",
        "SELECT ordinal,kind,item,detail FROM disagreements",
    ] {
        conn.prepare(query).map_err(damaged)?;
    }
    if version >= 2 {
        for query in [
            "SELECT seen_ms,result_ms FROM steps",
            "SELECT attempt,seq,ordinal,path,blob FROM step_files",
            "SELECT attempt,ended,exit_code,tokens_complete,fresh_in,cache_write,cache_read,output,reasoning,steps_seen,unknown_steps,unknown_changes,sandbox_ms,worker_ms,seal_ms,bring_ms,check_ms,recheck_ms,active_ms FROM measured",
            "SELECT attempt,ordinal,path,change FROM changes",
        ] {
            conn.prepare(query).map_err(damaged)?;
        }
    }
    if version >= 3 {
        conn.prepare(&format!("SELECT {OFFERS_COLUMNS} FROM offers"))
            .map_err(damaged)?;
    }
    Ok(version)
}

pub(crate) fn db(e: impl std::fmt::Display) -> RoomError {
    RoomError::Db(e.to_string())
}

fn damaged(e: impl std::fmt::Display) -> RoomError {
    RoomError::Damaged(e.to_string())
}
