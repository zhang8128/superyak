mod common;

use common::*;
use room::{item::classify, *};

#[test]
fn a_recheck_cannot_promote_a_failed_item() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    r.hand_in(&lease, &verdict(false).commit, 101).unwrap();
    assert_eq!(
        r.record_verdict(&id, lease.lease_no, &verdict(false), 102)
            .unwrap(),
        ItemState::Failed
    );
    assert!(matches!(
        r.record_recheck(&id, lease.lease_no, &verdict(true)),
        Err(RoomError::Refused(_))
    ));
    assert_eq!(r.item(&id).unwrap().state, ItemState::Failed);
    assert!(r.disagreements().unwrap().is_empty());
}

#[test]
fn a_worker_of_the_authors_family_is_skipped() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let mut n = new_item();
    n.check.written_by = "claude:haiku".into();
    let id = r.add_item(n).unwrap();
    r.record_frozen(&id, frozen()).unwrap();
    assert!(r.take("claude:opus", 100).unwrap().is_none());
    assert_eq!(r.turns_today(100).unwrap(), 0);
    assert_eq!(r.item(&id).unwrap().state, ItemState::Open);
    assert_eq!(r.take("codex:sol", 100).unwrap().unwrap().item, id);
}

#[test]
fn a_pass_by_the_authors_family_is_unverified() {
    let mut spec = check();
    spec.written_by = "codex:a".into();
    for origin in [CheckOrigin::Outside, CheckOrigin::ObservedFailure] {
        spec.origin = origin;
        assert_eq!(
            classify(&spec, &frozen(), &verdict(true), "codex:b"),
            ItemState::PassedUnverified
        );
        assert_eq!(
            classify(&spec, &frozen(), &verdict(true), "claude:opus"),
            ItemState::PassedVerified
        );
    }
}

#[test]
fn a_check_in_progress_can_renew_its_lease() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    r.hand_in(&lease, &verdict(true).commit, 101).unwrap();
    assert_eq!(r.item(&id).unwrap().state, ItemState::Checking);
    assert_eq!(r.renew(&lease, 500).unwrap(), 2300);
    assert!(r.expire_due(1900).unwrap().is_empty());
    assert_eq!(r.current_lease(&id).unwrap().unwrap().expires, 2300);
    assert_eq!(r.item(&id).unwrap().state, ItemState::Checking);
    assert_eq!(r.expire_due(2300).unwrap(), vec![id]);
}

#[test]
fn a_verdict_is_timed_by_the_caller() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    r.hand_in(&lease, &verdict(true).commit, 101).unwrap();
    r.record_verdict(&id, lease.lease_no, &verdict(true), 1000)
        .unwrap();
    assert_eq!(r.status(999).unwrap().verified_passes_last_day, 0);
    assert_eq!(r.status(1000).unwrap().verified_passes_last_day, 1);
    assert_eq!(r.status(1010).unwrap().verified_passes_last_day, 1);
    assert_eq!(r.status(87_401).unwrap().verified_passes_last_day, 0);
}

#[test]
fn erasing_an_item_removes_every_row_and_its_title_from_the_file() {
    const MARKER: &str = "ERASE-MARKER-7c1d";
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let mut n = new_item();
    n.title = MARKER.into();
    let id = r.add_item(n).unwrap();
    r.record_frozen(&id, frozen()).unwrap();
    let mut attempts = Vec::new();
    for (now, passed) in [(100, false), (200, true)] {
        let lease = r.take("codex:sol", now).unwrap().unwrap();
        r.record_walk(
            &lease.attempt,
            &[Step {
                seq: 1,
                tool: Tool::Read,
                target: Target::TrackedFile {
                    path: "src/lib.rs".into(),
                    blob: "5".repeat(40),
                },
                ok: true,
                tokens_in: Some(10),
                tokens_out: Some(20),
            }],
        )
        .unwrap();
        r.hand_in(&lease, &verdict(passed).commit, now + 1).unwrap();
        r.record_verdict(&id, lease.lease_no, &verdict(passed), now + 2)
            .unwrap();
        attempts.push(lease.attempt);
    }
    r.record_recheck(&id, 2, &verdict(false)).unwrap();
    assert_eq!(r.disagreements().unwrap().len(), 1);
    let keep = r.add_item(new_item()).unwrap();
    let c = rusqlite::Connection::open(d.path().join("room.sqlite3")).unwrap();
    c.execute_batch("PRAGMA wal_checkpoint(FULL)").unwrap();
    assert!(contains_marker(&d.path().join("room.sqlite3"), MARKER));
    assert!(contains_marker(&d.path().join("room.sqlite3-wal"), MARKER));

    c.execute_batch(
        "CREATE TRIGGER refuse_item_delete BEFORE DELETE ON items
         BEGIN SELECT RAISE(ABORT, 'injected delete failure'); END;",
    )
    .unwrap();
    assert!(r.erase_item(&id).is_err());
    assert_eq!(r.item(&id).unwrap().state, ItemState::PassedUnverified);
    assert_eq!(r.disagreements().unwrap().len(), 1);
    for attempt in &attempts {
        assert_eq!(r.walk(attempt).unwrap().len(), 1);
    }
    let verdict_count: u32 = c
        .query_row("SELECT count(*) FROM verdicts", [], |row| row.get(0))
        .unwrap();
    assert_eq!(verdict_count, 2);
    c.execute_batch("DROP TRIGGER refuse_item_delete").unwrap();

    r.erase_item(&id).unwrap();
    assert!(matches!(r.item(&id), Err(RoomError::NotTakeable(_))));
    assert_eq!(r.items().unwrap().len(), 1);
    assert_eq!(r.item(&keep).unwrap().title, "Fix fixture");
    assert_eq!(r.turns_today(300).unwrap(), 2);
    for table in [
        "meta",
        "items",
        "checks",
        "attempts",
        "steps",
        "verdicts",
        "budget_days",
        "disagreements",
    ] {
        let mut q = c.prepare(&format!("SELECT * FROM {table}")).unwrap();
        let columns = q.column_count();
        let mut rows = q.query([]).unwrap();
        while let Some(row) = rows.next().unwrap() {
            for col in 0..columns {
                if let rusqlite::types::ValueRef::Text(bytes) = row.get_ref(col).unwrap() {
                    for erased in
                        std::iter::once(id.0.as_str()).chain(attempts.iter().map(|a| a.0.as_str()))
                    {
                        assert!(
                            !bytes.windows(erased.len()).any(|b| b == erased.as_bytes()),
                            "{table} still names {erased}"
                        );
                    }
                }
            }
        }
    }
    assert!(r.disagreements().unwrap().is_empty());
    for attempt in attempts {
        assert!(r.walk(&attempt).unwrap().is_empty());
    }
    assert_store_lacks_marker(d.path(), MARKER);
    drop(c);
    drop(r);
    assert_store_lacks_marker(d.path(), MARKER);
    let r = Room::open(d.path()).unwrap();
    assert_eq!(r.items().unwrap().len(), 1);
    assert_eq!(r.item(&keep).unwrap().state, ItemState::Draft);
}

#[test]
fn a_running_item_cannot_be_erased() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    for state in [ItemState::Leased, ItemState::Checking] {
        assert_eq!(r.item(&id).unwrap().state, state);
        assert!(matches!(r.erase_item(&id), Err(RoomError::Refused(_))));
        assert_eq!(r.item(&id).unwrap().state, state);
        assert_eq!(r.current_lease(&id).unwrap(), Some(lease.clone()));
        r.hand_in(&lease, &verdict(true).commit, 101).unwrap();
    }
}

#[test]
fn a_pinned_reader_prevents_claiming_complete_erasure() {
    const MARKER: &str = "ERASE-PINNED-8d2e";
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = r
        .add_item(NewItem {
            title: MARKER.into(),
            ..new_item()
        })
        .unwrap();
    let reader = rusqlite::Connection::open(d.path().join("room.sqlite3")).unwrap();
    reader.execute_batch("BEGIN; SELECT * FROM items").unwrap();
    assert!(matches!(r.erase_item(&id), Err(RoomError::Db(_))));
    assert!(matches!(r.item(&id), Err(RoomError::NotTakeable(_))));
    let title: String = reader
        .query_row("SELECT title FROM items WHERE id=?1", [&id.0], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(title, MARKER);
    assert!(contains_marker(&d.path().join("room.sqlite3-wal"), MARKER));
    drop(reader);
    drop(r);
    assert_store_lacks_marker(d.path(), MARKER);
}

fn contains_marker(path: &std::path::Path, marker: &str) -> bool {
    std::fs::read(path)
        .unwrap()
        .windows(marker.len())
        .any(|bytes| bytes == marker.as_bytes())
}

fn assert_store_lacks_marker(dir: &std::path::Path, marker: &str) {
    for entry in std::fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.is_file() {
            assert!(
                !contains_marker(&path, marker),
                "erased title remains in {}",
                path.display()
            );
        }
    }
}
