use crate::{
    AttemptId, Room, RoomError, Step, Target,
    item::{from_key, hex_hash, key},
    store::db,
};

impl Room {
    /// Admit a batch atomically. Unnamed outside targets never carry a path or text.
    pub fn record_walk(&mut self, attempt: &AttemptId, steps: &[Step]) -> Result<usize, RoomError> {
        let tx = self.conn.transaction().map_err(db)?;
        let exists: bool = tx
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM attempts WHERE id=?1)",
                [&attempt.0],
                |r| r.get(0),
            )
            .map_err(db)?;
        if !exists {
            return Err(RoomError::Refused("unknown attempt".into()));
        }
        for step in steps {
            if let Target::TrackedFile { path, blob } = &step.target
                && (!plain_path(path) || !hex_hash(blob, &[40, 64]))
            {
                return Err(RoomError::Refused(
                    "walk target must be a plain relative path and a Git blob hash".into(),
                ));
            }
            let (target, path, blob) = match &step.target {
                Target::TrackedFile { path, blob } => {
                    ("tracked_file", Some(path.as_str()), Some(blob.as_str()))
                }
                Target::Outside => ("outside", None, None),
            };
            tx.execute("INSERT INTO steps (attempt,seq,tool,target,path,blob,ok,tokens_in,tokens_out) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)",
                (&attempt.0, step.seq, key(&step.tool)?, target, path, blob, step.ok, step.tokens_in, step.tokens_out)).map_err(db)?;
        }
        tx.commit().map_err(db)?;
        Ok(steps.len())
    }

    pub fn walk(&self, attempt: &AttemptId) -> Result<Vec<Step>, RoomError> {
        let mut q = self.conn.prepare("SELECT seq,tool,target,path,blob,ok,tokens_in,tokens_out FROM steps WHERE attempt=?1 ORDER BY seq").map_err(db)?;
        let rows = q
            .query_map([&attempt.0], |r| {
                Ok(StoredStep {
                    seq: r.get(0)?,
                    tool: r.get(1)?,
                    target: r.get(2)?,
                    path: r.get(3)?,
                    blob: r.get(4)?,
                    ok: r.get(5)?,
                    tokens_in: r.get(6)?,
                    tokens_out: r.get(7)?,
                })
            })
            .map_err(db)?;
        rows.map(|row| {
            let s = row.map_err(db)?;
            let target = match s.target.as_str() {
                "outside" => Target::Outside,
                "tracked_file" => Target::TrackedFile {
                    path: s
                        .path
                        .ok_or_else(|| RoomError::Damaged("tracked step has no path".into()))?,
                    blob: s
                        .blob
                        .ok_or_else(|| RoomError::Damaged("tracked step has no blob".into()))?,
                },
                _ => return Err(RoomError::Damaged("unknown walk target".into())),
            };
            Ok(Step {
                seq: s.seq,
                tool: from_key(&s.tool)?,
                target,
                ok: s.ok,
                tokens_in: s.tokens_in,
                tokens_out: s.tokens_out,
            })
        })
        .collect()
    }
}

fn plain_path(path: &str) -> bool {
    !path.is_empty()
        && path.len() <= 512
        && !path.starts_with('/')
        && path
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_./-".contains(&b))
        && path.split('/').all(|part| !matches!(part, "" | "." | ".."))
}

struct StoredStep {
    seq: u32,
    tool: String,
    target: String,
    path: Option<String>,
    blob: Option<String>,
    ok: bool,
    tokens_in: Option<u32>,
    tokens_out: Option<u32>,
}
