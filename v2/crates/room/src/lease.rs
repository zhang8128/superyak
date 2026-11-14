use rusqlite::{Connection, OptionalExtension};

use crate::{
    AttemptId, CheckSpec, Frozen, ItemId, ItemState, Lease, Room, RoomError, Ts, Verdict,
    item::{classify, dependencies_ready, hex_hash, item_view, key, new_id, parse},
    limits,
    store::db,
    types::family,
};

impl Room {
    /// Override future lease durations for this connection, without changing persistent policy.
    pub fn set_lease_secs(&mut self, secs: i64) -> Result<(), RoomError> {
        if secs < 1 {
            return Err(RoomError::Refused("lease duration must be positive".into()));
        }
        self.lease_secs = secs;
        Ok(())
    }

    pub fn take(&mut self, worker: &str, now: Ts) -> Result<Option<Lease>, RoomError> {
        let tx = self.conn.transaction().map_err(db)?;
        if self.dir.join("STOP").exists() {
            return Err(RoomError::Stopped);
        }
        let ids = {
            let mut q = tx.prepare("SELECT id FROM items WHERE state IN ('open','failed') AND attempts < ?1 ORDER BY ordinal").map_err(db)?;
            q.query_map([limits::MAX_ATTEMPTS], |r| r.get::<_, String>(0))
                .map_err(db)?
                .collect::<Result<Vec<_>, _>>()
                .map_err(db)?
        };
        for id in ids {
            let id = ItemId(id);
            let view = item_view(&tx, &id)?;
            let frozen: Option<String> = tx
                .query_row("SELECT frozen FROM checks WHERE item=?1", [&id.0], |r| {
                    r.get(0)
                })
                .map_err(db)?;
            if family(&view.written_by) == family(worker)
                || frozen.is_none()
                || !dependencies_ready(&tx, &view.after)?
            {
                continue;
            }
            if !crate::budget::reserve(&tx, now)? {
                tx.commit().map_err(db)?;
                return Ok(None);
            }
            let expires = expiry(now, self.lease_secs)?;
            let attempt = AttemptId(new_id(&tx, 'a')?);
            let lease_no = view.lease_no + 1;
            tx.execute("INSERT INTO attempts (id,item,lease_no,worker,started,expires,state) VALUES (?1,?2,?3,?4,?5,?6,'leased')",
                (&attempt.0, &id.0, lease_no, worker, now, expires)).map_err(db)?;
            tx.execute(
                "UPDATE items SET state='leased',lease_no=?1,attempts=attempts+1 WHERE id=?2",
                (lease_no, &id.0),
            )
            .map_err(db)?;
            tx.commit().map_err(db)?;
            return Ok(Some(Lease {
                item: id,
                attempt,
                lease_no,
                worker: worker.into(),
                expires,
            }));
        }
        tx.commit().map_err(db)?;
        Ok(None)
    }

    pub fn renew(&mut self, lease: &Lease, now: Ts) -> Result<Ts, RoomError> {
        let tx = self.conn.transaction().map_err(db)?;
        let active = validate_lease(&tx, lease, now)?;
        let expires = expiry(now, self.lease_secs)?.max(active.expires);
        tx.execute(
            "UPDATE attempts SET expires=?1 WHERE id=?2",
            (expires, &lease.attempt.0),
        )
        .map_err(db)?;
        tx.commit().map_err(db)?;
        Ok(expires)
    }

    pub fn hand_in(&mut self, lease: &Lease, commit: &str, now: Ts) -> Result<(), RoomError> {
        if !hex_hash(commit, &[40, 64]) {
            return Err(RoomError::Refused(
                "submission must name a Git commit hash".into(),
            ));
        }
        let tx = self.conn.transaction().map_err(db)?;
        let active = validate_lease(&tx, lease, now)?;
        if active.state == "checking" {
            tx.commit().map_err(db)?;
            return Ok(());
        }
        if active.state != "leased" {
            return Err(RoomError::NotTakeable("the turn is not running".into()));
        }
        tx.execute(
            "UPDATE attempts SET state='checking',submitted_commit=?1 WHERE id=?2",
            (commit, &lease.attempt.0),
        )
        .map_err(db)?;
        tx.execute(
            "UPDATE items SET state='checking' WHERE id=?1",
            [&lease.item.0],
        )
        .map_err(db)?;
        tx.commit().map_err(db)?;
        Ok(())
    }

    pub fn record_verdict(
        &mut self,
        item: &ItemId,
        lease_no: u32,
        v: &Verdict,
        now: Ts,
    ) -> Result<ItemState, RoomError> {
        if !hex_hash(&v.commit, &[40, 64])
            || !hex_hash(&v.check_hash, &[64])
            || !hex_hash(&v.output_sha256, &[64])
        {
            return Err(RoomError::Refused(
                "verdict must contain artifact and output hashes".into(),
            ));
        }
        let tx = self.conn.transaction().map_err(db)?;
        let view = item_view(&tx, item)?;
        if lease_no != view.lease_no {
            return Err(RoomError::Stale {
                lease_no,
                current: view.lease_no,
            });
        }
        let active = attempt(&tx, item, lease_no)?;
        if view.state != ItemState::Checking || active.state != "checking" {
            return Err(RoomError::NotTakeable(
                "no current submission to check".into(),
            ));
        }
        if active.submitted_commit.as_deref() != Some(&v.commit) {
            return Err(RoomError::Refused(
                "verdict does not name the submitted artifact".into(),
            ));
        }
        let (spec, frozen, base): (String,String,String) = tx.query_row("SELECT c.spec,c.frozen,i.base_commit FROM checks c JOIN items i ON i.id=c.item WHERE c.item=?1", [&item.0], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?))).map_err(db)?;
        let spec: CheckSpec = parse(&spec)?;
        let frozen: Frozen = parse(&frozen)?;
        let mut state = if v.commit == base {
            ItemState::Failed
        } else {
            classify(&spec, &frozen, v, &active.worker)
        };
        if state == ItemState::Failed && view.attempts >= limits::MAX_ATTEMPTS {
            state = ItemState::Abandoned;
            abandoned(&tx, item)?;
        }
        tx.execute("INSERT INTO verdicts (attempt,passed,exit_code,timed_out,artifact,check_hash,output_sha256,recorded) VALUES (?1,?2,?3,?4,?5,?6,?7,?8)",
            (&active.id, v.passed, v.exit_code, v.timed_out, &v.commit, &v.check_hash, &v.output_sha256, now)).map_err(db)?;
        tx.execute(
            "UPDATE attempts SET state='finished' WHERE id=?1",
            [&active.id],
        )
        .map_err(db)?;
        tx.execute(
            "UPDATE items SET state=?1 WHERE id=?2",
            (key(&state)?, &item.0),
        )
        .map_err(db)?;
        if state == ItemState::PassedVerified {
            refresh_dependencies(&tx)?;
        }
        tx.commit().map_err(db)?;
        Ok(state)
    }

    pub fn record_recheck(
        &mut self,
        item: &ItemId,
        lease_no: u32,
        v: &Verdict,
    ) -> Result<ItemState, RoomError> {
        let tx = self.conn.transaction().map_err(db)?;
        let view = item_view(&tx, item)?;
        if view.lease_no != lease_no {
            return Err(RoomError::Stale {
                lease_no,
                current: view.lease_no,
            });
        }
        if view.state != ItemState::PassedVerified {
            return Err(RoomError::Refused(
                "only a verified pass may be rechecked".into(),
            ));
        }
        let active = attempt(&tx, item, lease_no)?;
        let (passed, artifact, check_hash): (bool, String, String) = tx
            .query_row(
                "SELECT passed,artifact,check_hash FROM verdicts WHERE attempt=?1",
                [&active.id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()
            .map_err(db)?
            .ok_or_else(|| RoomError::NotTakeable("no recorded verdict to recheck".into()))?;
        if artifact != v.commit || check_hash != v.check_hash {
            return Err(RoomError::Refused(
                "recheck must name the recorded artifact and check".into(),
            ));
        }
        let state = if passed == v.passed {
            view.state
        } else {
            tx.execute(
                "UPDATE items SET state='passed_unverified' WHERE id=?1",
                [&item.0],
            )
            .map_err(db)?;
            tx.execute("INSERT OR IGNORE INTO disagreements (kind,item,detail) VALUES ('recheck_differs',?1,'recheck differs from the recorded verdict')", [&item.0]).map_err(db)?;
            refresh_dependencies(&tx)?;
            ItemState::PassedUnverified
        };
        tx.commit().map_err(db)?;
        Ok(state)
    }

    pub fn submission(&self, item: &ItemId) -> Result<Option<(u32, String)>, RoomError> {
        let (lease_no, commit): (u32,Option<String>) = self.conn.query_row("SELECT i.lease_no,a.submitted_commit FROM items i LEFT JOIN attempts a ON a.item=i.id AND a.lease_no=i.lease_no WHERE i.id=?1", [&item.0], |r| Ok((r.get(0)?,r.get(1)?))).optional().map_err(db)?.ok_or_else(|| RoomError::NotTakeable("unknown item".into()))?;
        Ok(commit.map(|commit| (lease_no, commit)))
    }

    /// Recover the stored identity and expiry of a running or checking attempt.
    pub fn current_lease(&self, item: &ItemId) -> Result<Option<Lease>, RoomError> {
        let view = item_view(&self.conn, item)?;
        if !matches!(view.state, ItemState::Leased | ItemState::Checking) {
            return Ok(None);
        }
        let active = attempt(&self.conn, item, view.lease_no)?;
        Ok(Some(Lease {
            item: item.clone(),
            attempt: AttemptId(active.id),
            lease_no: view.lease_no,
            worker: active.worker,
            expires: active.expires,
        }))
    }

    pub fn expire_due(&mut self, now: Ts) -> Result<Vec<ItemId>, RoomError> {
        let tx = self.conn.transaction().map_err(db)?;
        let due = {
            let mut q = tx.prepare("SELECT i.id,a.id,i.attempts FROM items i JOIN attempts a ON a.item=i.id AND a.lease_no=i.lease_no WHERE i.state IN ('leased','checking') AND a.state IN ('leased','checking') AND a.expires <= ?1 ORDER BY i.ordinal").map_err(db)?;
            q.query_map([now], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, u32>(2)?,
                ))
            })
            .map_err(db)?
            .collect::<Result<Vec<_>, _>>()
            .map_err(db)?
        };
        let mut ids = Vec::new();
        for (id, attempt, count) in due {
            let id = ItemId(id);
            let state = if count >= limits::MAX_ATTEMPTS {
                abandoned(&tx, &id)?;
                "abandoned"
            } else {
                "open"
            };
            tx.execute(
                "UPDATE attempts SET state='expired' WHERE id=?1",
                [&attempt],
            )
            .map_err(db)?;
            tx.execute("UPDATE items SET state=?1 WHERE id=?2", (state, &id.0))
                .map_err(db)?;
            ids.push(id);
        }
        tx.commit().map_err(db)?;
        Ok(ids)
    }
}

fn expiry(now: Ts, secs: i64) -> Result<Ts, RoomError> {
    now.checked_add(secs)
        .ok_or_else(|| RoomError::Refused("lease timestamp overflows".into()))
}

struct Attempt {
    id: String,
    worker: String,
    expires: Ts,
    state: String,
    submitted_commit: Option<String>,
}

fn attempt(conn: &Connection, item: &ItemId, lease_no: u32) -> Result<Attempt, RoomError> {
    conn.query_row("SELECT id,worker,expires,state,submitted_commit FROM attempts WHERE item=?1 AND lease_no=?2", (&item.0, lease_no), |r| {
        Ok(Attempt { id:r.get(0)?, worker:r.get(1)?, expires:r.get(2)?, state:r.get(3)?, submitted_commit:r.get(4)? })
    }).optional().map_err(db)?.ok_or_else(|| RoomError::NotTakeable("unknown attempt".into()))
}

fn validate_lease(conn: &Connection, lease: &Lease, now: Ts) -> Result<Attempt, RoomError> {
    let current = item_view(conn, &lease.item)?;
    if current.lease_no != lease.lease_no {
        return Err(RoomError::Stale {
            lease_no: lease.lease_no,
            current: current.lease_no,
        });
    }
    let active = attempt(conn, &lease.item, lease.lease_no)?;
    if active.expires <= now
        || !matches!(current.state, ItemState::Leased | ItemState::Checking)
        || !matches!(active.state.as_str(), "leased" | "checking")
    {
        return Err(RoomError::Stale {
            lease_no: lease.lease_no,
            current: current.lease_no,
        });
    }
    if active.id != lease.attempt.0 || active.worker != lease.worker {
        return Err(RoomError::Refused(
            "lease identity does not match the stored turn".into(),
        ));
    }
    Ok(active)
}

fn abandoned(conn: &Connection, id: &ItemId) -> Result<(), RoomError> {
    conn.execute("INSERT OR IGNORE INTO disagreements (kind,item,detail) VALUES ('abandoned',?1,'attempt limit reached')", [&id.0]).map_err(db)?;
    Ok(())
}

fn refresh_dependencies(conn: &Connection) -> Result<(), RoomError> {
    let mut q = conn
        .prepare("SELECT id,after_ids FROM items WHERE state IN ('open','blocked')")
        .map_err(db)?;
    let blocked = q
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
        .map_err(db)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(db)?;
    for (id, after) in blocked {
        let state = if dependencies_ready(conn, &parse::<Vec<ItemId>>(&after)?)? {
            "open"
        } else {
            "blocked"
        };
        conn.execute("UPDATE items SET state=?1 WHERE id=?2", (state, &id))
            .map_err(db)?;
    }
    Ok(())
}
