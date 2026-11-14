mod common;

use common::{open_item, verdict};
use room::{AttemptId, ItemState, Room, RoomError};

#[test]
fn releases_preserve_lease_numbers_without_using_item_attempts() {
    let dir = tempfile::tempdir().unwrap();
    let mut room = Room::init(dir.path()).unwrap();
    let id = open_item(&mut room);
    for number in 1..=4 {
        let lease = room.take("codex:test", 100).unwrap().unwrap();
        assert_eq!(lease.lease_no, number);
        if number % 2 == 0 {
            room.hand_in(&lease, &verdict(true).commit, 101).unwrap();
        }
        room.release(&lease, 102).unwrap();
        let item = room.item(&id).unwrap();
        assert_eq!(item.state, ItemState::Open);
        assert_eq!(item.attempts, 0);
        assert_eq!(item.lease_no, number);
        drop(room);
        room = Room::open(dir.path()).unwrap();
    }
    let next = room.take("codex:test", 103).unwrap().unwrap();
    assert_eq!(next.lease_no, 5);
    assert_eq!(room.item(&id).unwrap().attempts, 1);
    assert!(room.disagreements().unwrap().is_empty());
    let db = rusqlite::Connection::open(dir.path().join("room.sqlite3")).unwrap();
    let released: u32 = db
        .query_row(
            "SELECT count(*) FROM attempts WHERE state='released'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let verdicts: u32 = db
        .query_row("SELECT count(*) FROM verdicts", [], |r| r.get(0))
        .unwrap();
    assert_eq!(released, 4);
    assert_eq!(verdicts, 0);
}

#[test]
fn releasing_keeps_the_days_turn_spent() {
    let dir = tempfile::tempdir().unwrap();
    let mut room = Room::init(dir.path()).unwrap();
    open_item(&mut room);
    room.set_ceiling(1, 1).unwrap();
    let lease = room.take("codex:test", 100).unwrap().unwrap();
    assert_eq!(room.turns_today(100).unwrap(), 1);
    room.release(&lease, 101).unwrap();
    assert_eq!(room.turns_today(101).unwrap(), 1);
    assert!(matches!(
        room.take("codex:test", 102),
        Err(RoomError::Ceiling { used: 1, limit: 1 })
    ));
}

#[test]
fn stale_leases_cannot_release_an_item() {
    let dir = tempfile::tempdir().unwrap();
    let mut room = Room::init(dir.path()).unwrap();
    let id = open_item(&mut room);
    let first = room.take("codex:test", 100).unwrap().unwrap();
    assert!(matches!(
        room.release(&first, first.expires),
        Err(RoomError::Stale { .. })
    ));
    room.expire_due(first.expires).unwrap();
    let next = room.take("codex:test", first.expires).unwrap().unwrap();
    assert!(matches!(
        room.release(&first, first.expires),
        Err(RoomError::Stale {
            lease_no: 1,
            current: 2
        })
    ));
    let forged = room::Lease {
        attempt: AttemptId("other".into()),
        ..next.clone()
    };
    assert!(matches!(
        room.release(&forged, first.expires),
        Err(RoomError::Refused(_))
    ));
    let forged = room::Lease {
        worker: "claude:test".into(),
        ..next.clone()
    };
    assert!(matches!(
        room.release(&forged, first.expires),
        Err(RoomError::Refused(_))
    ));
    assert_eq!(room.item(&id).unwrap().state, ItemState::Leased);
    room.release(&next, first.expires).unwrap();
    assert!(matches!(
        room.release(&next, first.expires),
        Err(RoomError::Stale { .. })
    ));
    assert_eq!(room.item(&id).unwrap().attempts, 1);
}
