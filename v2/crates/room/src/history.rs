//! A read snapshot of completed turns. No command, prompt, worker name or output crosses this seam.

use serde::{Deserialize, Serialize};

use crate::{
    AttemptId, ChangedFile, ItemId, ItemState, Room, RoomError, Step, Target, Ts, Verdict,
    item::classify, store::db,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Standing {
    PassedVerified,
    PassedUnverified,
    Failed,
    Unjudged,
}

/// The room's part of a walk file. Repository identity is resolved by the caller's bounded git reader.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ArrivedTurn {
    pub attempt: AttemptId,
    pub family: String,
    pub verdict: Option<bool>,
    pub standing: Standing,
    pub steps: Vec<Step>,
    pub changed: Vec<ChangedFile>,
    /// Arrival time, used for the ranker's later-turn tie break; never exported as turn text.
    pub recorded: Ts,
}

impl Room {
    /// Every completed verdict of this item, oldest lease first. Released and running attempts have not
    /// arrived. Failure and unverified pass are retained; admission to teaching is a separate policy.
    pub fn arrived_turns(&self, item: &ItemId) -> Result<Vec<ArrivedTurn>, RoomError> {
        let tx = self.conn.unchecked_transaction().map_err(db)?;
        let view = self.item(item)?;
        let spec = self.item_spec(item)?;
        let mut query = self
            .conn
            .prepare(
                "SELECT a.id,a.lease_no,a.worker,v.passed,v.exit_code,v.timed_out,v.artifact,
                    v.check_hash,v.output_sha256,v.recorded
             FROM attempts a JOIN verdicts v ON v.attempt=a.id
             WHERE a.item=?1 AND a.state='finished' ORDER BY a.lease_no",
            )
            .map_err(db)?;
        let rows = query
            .query_map([&item.0], |r| {
                Ok((
                    AttemptId(r.get(0)?),
                    r.get::<_, u32>(1)?,
                    r.get::<_, String>(2)?,
                    Verdict {
                        passed: r.get(3)?,
                        exit_code: r.get(4)?,
                        timed_out: r.get(5)?,
                        commit: r.get(6)?,
                        check_hash: r.get(7)?,
                        output_sha256: r.get(8)?,
                    },
                    r.get::<_, Ts>(9)?,
                ))
            })
            .map_err(db)?;
        let mut turns = Vec::new();
        for row in rows {
            let (attempt, lease_no, worker, verdict, recorded) = row.map_err(db)?;
            let family = crate::family(&worker);
            if !matches!(family, "claude" | "codex" | "script") {
                return Err(RoomError::Refused("walk.family".into()));
            }
            let frozen = spec
                .frozen
                .as_ref()
                .ok_or_else(|| RoomError::Damaged("arrived turn has no frozen check".into()))?;
            let standing = if verdict.commit == spec.base_commit {
                Standing::Failed
            } else {
                match classify(&spec.check, frozen, &verdict, &worker) {
                    ItemState::PassedVerified
                        if lease_no == view.lease_no
                            && view.state == ItemState::PassedUnverified =>
                    {
                        Standing::PassedUnverified
                    }
                    ItemState::PassedVerified => Standing::PassedVerified,
                    ItemState::PassedUnverified => Standing::PassedUnverified,
                    _ => Standing::Failed,
                }
            };
            let mut steps = self.walk(&attempt)?;
            for step in &mut steps {
                if step.named.is_empty()
                    && let Target::TrackedFile { path, blob } = &step.target
                {
                    step.named.push(crate::Named {
                        path: path.clone(),
                        blob: blob.clone(),
                    });
                }
            }
            turns.push(ArrivedTurn {
                changed: self.changes(&attempt)?,
                attempt,
                family: family.into(),
                verdict: Some(verdict.passed),
                standing,
                steps,
                recorded,
            });
        }
        drop(query);
        tx.commit().map_err(db)?;
        Ok(turns)
    }
}
