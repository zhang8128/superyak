mod common;

use room::{Room, RoomError};

#[test]
fn open_refuses_a_missing_store() {
    let d = tempfile::tempdir().unwrap();
    assert!(matches!(Room::open(d.path()), Err(RoomError::Missing(_))));
    assert_eq!(std::fs::read_dir(d.path()).unwrap().count(), 0);
    assert!(matches!(
        Room::open_read_only(d.path()),
        Err(RoomError::Missing(_))
    ));
    assert_eq!(std::fs::read_dir(d.path()).unwrap().count(), 0);
}

#[test]
fn a_second_writer_is_locked_out() {
    let d = tempfile::tempdir().unwrap();
    let first = Room::init(d.path()).unwrap();
    assert!(matches!(Room::open(d.path()), Err(RoomError::Locked)));
    assert!(Room::open_read_only(d.path()).is_ok());
    drop(first);
    assert!(Room::open(d.path()).is_ok());
}

#[test]
fn a_newer_schema_is_refused() {
    let d = tempfile::tempdir().unwrap();
    drop(Room::init(d.path()).unwrap());
    let conn = rusqlite::Connection::open(d.path().join("room.sqlite3")).unwrap();
    conn.execute("UPDATE meta SET schema_version = 3", [])
        .unwrap();
    drop(conn);
    assert!(matches!(
        Room::open(d.path()),
        Err(RoomError::NewerSchema { found: 3, known: 2 })
    ));
}

#[test]
fn a_truncated_store_is_damaged() {
    let d = tempfile::tempdir().unwrap();
    drop(Room::init(d.path()).unwrap());
    let path = d.path().join("room.sqlite3");
    let bytes = std::fs::read(&path).unwrap();
    std::fs::write(&path, &bytes[..bytes.len() / 2]).unwrap();
    assert!(matches!(Room::open(d.path()), Err(RoomError::Damaged(_))));
    assert_eq!(std::fs::read(&path).unwrap().len(), bytes.len() / 2);
}

#[test]
fn init_refuses_an_existing_store() {
    let d = tempfile::tempdir().unwrap();
    let _room = Room::init(d.path()).unwrap();
    assert!(matches!(Room::init(d.path()), Err(RoomError::Refused(_))));
}

#[test]
fn writer_uses_wal() {
    let d = tempfile::tempdir().unwrap();
    let _room = Room::init(d.path()).unwrap();
    let conn = rusqlite::Connection::open(d.path().join("room.sqlite3")).unwrap();
    let journal: String = conn
        .query_row("PRAGMA journal_mode", [], |r| r.get(0))
        .unwrap();
    assert_eq!(journal, "wal");
    assert!(Room::open_read_only(d.path()).is_ok());
}

#[test]
fn an_empty_or_wrong_schema_is_refused_as_damaged() {
    for sql in [
        "",
        "CREATE TABLE meta(schema_version INTEGER); INSERT INTO meta VALUES (1)",
    ] {
        let d = tempfile::tempdir().unwrap();
        let conn = rusqlite::Connection::open(d.path().join("room.sqlite3")).unwrap();
        conn.execute_batch(sql).unwrap();
        drop(conn);
        assert!(matches!(Room::open(d.path()), Err(RoomError::Damaged(_))));
    }
}

// The stage 1 schema is deliberately frozen here.
const V1: &str = r#"
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
CREATE TABLE budget_days (day INTEGER PRIMARY KEY, used INTEGER NOT NULL);
CREATE TABLE disagreements (
    ordinal INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    item TEXT NOT NULL REFERENCES items(id),
    detail TEXT NOT NULL,
    UNIQUE(kind, item)
);
"#;

/// A store as the stage 1 program left it: the stage 1 schema and one of everything, in WAL mode, as its writer
/// always set it.
fn version_1(dir: &std::path::Path) -> rusqlite::Connection {
    let c = rusqlite::Connection::open(dir.join("room.sqlite3")).unwrap();
    let mode: String = c
        .query_row("PRAGMA journal_mode=WAL", [], |r| r.get(0))
        .unwrap();
    assert_eq!(mode, "wal");
    c.execute_batch(V1).unwrap();
    c.execute_batch("INSERT INTO meta VALUES (1,40,1);
        INSERT INTO items VALUES (1,'i000000000000','fixture','/fixture','0000000000000000000000000000000000000000','[]','failed',1,1);
        INSERT INTO attempts VALUES ('a000000000000','i000000000000',1,'script:fixture',100,1900,'failed',NULL);
        INSERT INTO steps VALUES ('a000000000000',0,'read','outside',NULL,NULL,1,NULL,NULL);
        INSERT INTO verdicts VALUES ('a000000000000',0,1,0,'0000000000000000000000000000000000000000','1111111111111111111111111111111111111111111111111111111111111111','2222222222222222222222222222222222222222222222222222222222222222',101);").unwrap();
    c.execute(
        "INSERT INTO checks(item,spec) VALUES ('i000000000000',?1)",
        [serde_json::to_string(&common::check()).unwrap()],
    )
    .unwrap();
    c
}

#[test]
fn a_version_1_store_is_brought_forward_when_opened_for_writing() {
    let d = tempfile::tempdir().unwrap();
    let c = version_1(d.path());
    let queries = [
        "SELECT * FROM items",
        "SELECT * FROM attempts",
        "SELECT attempt,seq,tool,target,path,blob,ok,tokens_in,tokens_out FROM steps",
        "SELECT * FROM verdicts",
        "SELECT * FROM checks",
    ];
    let read = |sql: &str| {
        let mut q = c.prepare(sql).unwrap();
        let columns = q.column_count();
        q.query_map([], |row| {
            (0..columns)
                .map(|i| row.get::<_, rusqlite::types::Value>(i))
                .collect::<Result<Vec<_>, _>>()
        })
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap()
    };
    let before: Vec<_> = queries.iter().map(|q| read(q)).collect();
    let r = Room::open(d.path()).unwrap();
    let after: Vec<_> = queries.iter().map(|q| read(q)).collect();
    assert_eq!(after, before);
    assert_eq!(r.items().unwrap().len(), 1);
    assert_eq!(
        r.walk(&room::AttemptId("a000000000000".into()))
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        c.query_row("SELECT schema_version FROM meta", [], |r| r
            .get::<_, u32>(0))
            .unwrap(),
        2
    );
    for table in ["items", "attempts", "steps", "verdicts"] {
        assert_eq!(
            c.query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r
                .get::<_, u32>(0))
                .unwrap(),
            1
        );
    }
    for table in ["step_files", "measured", "changes"] {
        assert_eq!(
            c.query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r
                .get::<_, u32>(0))
                .unwrap(),
            0
        );
    }
    let times: (Option<u32>, Option<u32>) = c
        .query_row("SELECT seen_ms,result_ms FROM steps", [], |r| {
            Ok((r.get(0)?, r.get(1)?))
        })
        .unwrap();
    assert_eq!(times, (None, None));
}

#[test]
fn a_version_1_store_opened_read_only_says_how() {
    let d = tempfile::tempdir().unwrap();
    version_1(d.path());
    let e = Room::open_read_only(d.path()).err().unwrap();
    assert!(e.to_string().contains("opening it once for writing"));
    assert!(matches!(e, RoomError::OlderSchema { found: 1, known: 2 }));
}

/// Another writer holding the store's write lock keeps the migration from starting, and the store stays as the
/// stage 1 program left it. With the store in WAL mode, as a real stage 1 store is, nothing before the migration
/// needs that lock: it is the migration's own transaction that is refused.
#[test]
fn a_held_write_lock_stops_the_migration_and_leaves_version_1_as_it_was() {
    let d = tempfile::tempdir().unwrap();
    let c = version_1(d.path());
    c.execute_batch("BEGIN IMMEDIATE").unwrap();
    assert!(Room::open(d.path()).is_err());
    assert_eq!(
        c.query_row("SELECT schema_version FROM meta", [], |r| r
            .get::<_, u32>(0))
            .unwrap(),
        1
    );
    c.prepare("SELECT attempt,seq,tool,target,path,blob,ok,tokens_in,tokens_out FROM steps")
        .unwrap();
    assert!(c.prepare("SELECT seen_ms FROM steps").is_err());
    assert!(c.prepare("SELECT * FROM measured").is_err());
    c.execute_batch("ROLLBACK").unwrap();
    assert!(Room::open(d.path()).is_ok());
}

#[test]
fn a_failed_migration_rolls_back_the_tables_it_already_created() {
    let d = tempfile::tempdir().unwrap();
    let c = version_1(d.path());
    c.execute_batch("CREATE TABLE changes(unexpected INTEGER)")
        .unwrap();
    assert!(Room::open(d.path()).is_err());
    assert_eq!(
        c.query_row("SELECT schema_version FROM meta", [], |r| r
            .get::<_, u32>(0))
            .unwrap(),
        1
    );
    assert!(c.prepare("SELECT * FROM step_files").is_err());
    assert!(c.prepare("SELECT * FROM measured").is_err());
    assert!(c.prepare("SELECT seen_ms FROM steps").is_err());
}

#[test]
fn every_version_2_table_and_column_is_validated() {
    let tables: &[(&str, &[&str])] = &[
        ("steps", &["seen_ms", "result_ms"]),
        ("step_files", &["attempt", "seq", "ordinal", "path", "blob"]),
        (
            "measured",
            &[
                "attempt",
                "ended",
                "exit_code",
                "tokens_complete",
                "fresh_in",
                "cache_write",
                "cache_read",
                "output",
                "reasoning",
                "steps_seen",
                "unknown_steps",
                "unknown_changes",
                "sandbox_ms",
                "worker_ms",
                "seal_ms",
                "bring_ms",
                "check_ms",
                "recheck_ms",
                "active_ms",
            ],
        ),
        ("changes", &["attempt", "ordinal", "path", "change"]),
    ];
    for (table, columns) in tables {
        for missing in *columns {
            let d = tempfile::tempdir().unwrap();
            drop(Room::init(d.path()).unwrap());
            let c = rusqlite::Connection::open(d.path().join("room.sqlite3")).unwrap();
            if *table == "steps" {
                c.execute(&format!("ALTER TABLE steps DROP COLUMN {missing}"), [])
                    .unwrap();
            } else {
                // Rebuild a damaged table without the column, including when it was part of a key.
                let definitions = columns
                    .iter()
                    .filter(|name| *name != missing)
                    .map(|name| format!("\"{name}\" TEXT"))
                    .collect::<Vec<_>>()
                    .join(",");
                c.execute_batch(&format!(
                    "DROP TABLE {table}; CREATE TABLE {table} ({definitions})"
                ))
                .unwrap();
            }
            assert!(
                matches!(Room::open_read_only(d.path()), Err(RoomError::Damaged(_))),
                "{table}.{missing}"
            );
            assert!(
                matches!(Room::open(d.path()), Err(RoomError::Damaged(_))),
                "{table}.{missing}"
            );
        }
    }
}
