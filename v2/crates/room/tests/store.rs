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
    conn.execute("UPDATE meta SET schema_version = 2", [])
        .unwrap();
    drop(conn);
    assert!(matches!(
        Room::open(d.path()),
        Err(RoomError::NewerSchema { found: 2, known: 1 })
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
