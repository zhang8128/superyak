use rusqlite::{OptionalExtension, params};
use serde::Serialize;

use crate::{
    AttemptId, ChangedFile, ItemId, Measured, Room, RoomError, Tokens,
    item::{from_key, key},
    store::db,
    walk::plain_path,
};

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TurnView {
    pub attempt: AttemptId,
    pub lease_no: u32,
    pub worker: String,
    pub state: String,
    pub commit: Option<String>,
    pub passed: Option<bool>,
    pub measured: Option<Measured>,
    pub changes: Vec<ChangedFile>,
    pub steps: u32,
    pub steps_with_a_name: u32,
}

impl Room {
    /// Keep a whole turn once. Missing costs remain NULL, rather than zero.
    pub fn record_measured(&mut self, attempt: &AttemptId, m: &Measured) -> Result<(), RoomError> {
        self.conn.execute(
            "INSERT INTO measured VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18)",
            params![attempt.0, key(&m.ended)?, m.exit_code, m.tokens.complete,
                m.tokens.fresh_in.map(integer).transpose()?, m.tokens.cache_write.map(integer).transpose()?, m.tokens.cache_read.map(integer).transpose()?, m.tokens.output.map(integer).transpose()?,
                m.tokens.reasoning.map(integer).transpose()?, integer(m.steps_seen)?, integer(m.unknown_steps)?, integer(m.sandbox_ms)?, integer(m.worker_ms)?,
                integer(m.seal_ms)?, integer(m.bring_ms)?, m.check_ms.map(integer).transpose()?, m.recheck_ms.map(integer).transpose()?, integer(m.active_ms)?],
        ).map_err(db)?;
        Ok(())
    }

    /// Keep the second look beside the measured turn, without changing its active time.
    pub fn record_recheck_ms(&mut self, attempt: &AttemptId, ms: u64) -> Result<(), RoomError> {
        let rows = self
            .conn
            .execute(
                "UPDATE measured SET recheck_ms=?1 WHERE attempt=?2",
                (integer(ms)?, &attempt.0),
            )
            .map_err(db)?;
        if rows == 0 {
            return Err(RoomError::Refused(
                "the attempt has no measured record".into(),
            ));
        }
        Ok(())
    }

    pub fn measured(&self, attempt: &AttemptId) -> Result<Option<Measured>, RoomError> {
        let row = self.conn.query_row(
            "SELECT ended,exit_code,tokens_complete,fresh_in,cache_write,cache_read,output,reasoning,steps_seen,unknown_steps,sandbox_ms,worker_ms,seal_ms,bring_ms,check_ms,recheck_ms,active_ms FROM measured WHERE attempt=?1",
            [&attempt.0], |r| Ok((r.get::<_,String>(0)?, Measured {
                ended: crate::Ended::NotRun, exit_code: r.get(1)?,
                tokens: Tokens { complete: r.get(2)?, fresh_in: read_optional(r, 3)?, cache_write: read_optional(r, 4)?,
                    cache_read: read_optional(r, 5)?, output: read_optional(r, 6)?, reasoning: read_optional(r, 7)? },
                steps_seen: read_number(r, 8)?, unknown_steps: read_number(r, 9)?, sandbox_ms: read_number(r, 10)?,
                worker_ms: read_number(r, 11)?, seal_ms: read_number(r, 12)?, bring_ms: read_number(r, 13)?,
                check_ms: read_optional(r, 14)?, recheck_ms: read_optional(r, 15)?, active_ms: read_number(r, 16)?,
            })),
        ).optional().map_err(db)?;
        row.map(|(ended, mut m)| {
            m.ended = from_key(&ended)?;
            Ok(m)
        })
        .transpose()
    }

    /// Keep only plain paths, preserving their order. Returns how many names were omitted.
    pub fn record_changes(
        &mut self,
        attempt: &AttemptId,
        files: &[ChangedFile],
    ) -> Result<usize, RoomError> {
        let tx = self.conn.transaction().map_err(db)?;
        let mut omitted = 0;
        for (ordinal, file) in files.iter().enumerate() {
            if !plain_path(&file.path) {
                omitted += 1;
                continue;
            }
            tx.execute(
                "INSERT INTO changes VALUES (?1,?2,?3,?4)",
                (&attempt.0, ordinal as i64, &file.path, key(&file.change)?),
            )
            .map_err(db)?;
        }
        tx.commit().map_err(db)?;
        Ok(omitted)
    }

    pub fn changes(&self, attempt: &AttemptId) -> Result<Vec<ChangedFile>, RoomError> {
        let mut q = self
            .conn
            .prepare("SELECT path,change FROM changes WHERE attempt=?1 ORDER BY ordinal")
            .map_err(db)?;
        let rows = q
            .query_map([&attempt.0], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
            })
            .map_err(db)?;
        rows.map(|row| {
            let (path, change) = row.map_err(db)?;
            Ok(ChangedFile {
                path,
                change: from_key(&change)?,
            })
        })
        .collect()
    }

    /// Every attempt of an item, including unmeasured attempts from stage 1.
    pub fn turns(&self, item: &ItemId) -> Result<Vec<TurnView>, RoomError> {
        // Hold a read snapshot while combining the attempt and its child rows.
        let tx = self.conn.unchecked_transaction().map_err(db)?;
        self.item(item)?;
        let mut q = self.conn.prepare(
            "SELECT a.id,a.lease_no,a.worker,a.state,a.submitted_commit,v.passed,
             (SELECT count(*) FROM steps s WHERE s.attempt=a.id),
             (SELECT count(*) FROM steps s WHERE s.attempt=a.id AND (s.target='tracked_file' OR EXISTS
                 (SELECT 1 FROM step_files f WHERE f.attempt=s.attempt AND f.seq=s.seq)))
             FROM attempts a LEFT JOIN verdicts v ON v.attempt=a.id WHERE a.item=?1 ORDER BY a.lease_no"
        ).map_err(db)?;
        let rows = q
            .query_map([&item.0], |r| {
                Ok(TurnView {
                    attempt: AttemptId(r.get(0)?),
                    lease_no: r.get(1)?,
                    worker: r.get(2)?,
                    state: r.get(3)?,
                    commit: r.get(4)?,
                    passed: r.get(5)?,
                    measured: None,
                    changes: Vec::new(),
                    steps: r.get(6)?,
                    steps_with_a_name: r.get(7)?,
                })
            })
            .map_err(db)?;
        let mut out = Vec::new();
        for row in rows {
            let mut view = row.map_err(db)?;
            view.measured = self.measured(&view.attempt)?;
            view.changes = self.changes(&view.attempt)?;
            out.push(view);
        }
        drop(q);
        tx.commit().map_err(db)?;
        Ok(out)
    }
}

fn integer(value: u64) -> Result<i64, RoomError> {
    i64::try_from(value).map_err(db)
}

fn unsigned(value: i64, column: usize) -> rusqlite::Result<u64> {
    u64::try_from(value).map_err(|e| {
        rusqlite::Error::FromSqlConversionFailure(
            column,
            rusqlite::types::Type::Integer,
            Box::new(e),
        )
    })
}

fn read_number(row: &rusqlite::Row<'_>, column: usize) -> rusqlite::Result<u64> {
    unsigned(row.get(column)?, column)
}

fn read_optional(row: &rusqlite::Row<'_>, column: usize) -> rusqlite::Result<Option<u64>> {
    row.get::<_, Option<i64>>(column)?
        .map(|n| unsigned(n, column))
        .transpose()
}
