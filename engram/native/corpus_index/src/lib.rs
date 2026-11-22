//! A dependency-free BM25 keyword index with a link graph over a frozen Wikipedia corpus.
//!
//! Built for multi-hop retrieval (`engram/experiments/multihop`): `build` turns a corpus's docs
//! and links into one binary index file; `query` loads it once and answers many queries from
//! stdin in milliseconds, instead of the ~19 s a per-question SQLite FTS5 scan over the whole
//! corpus takes. Std library only, by Andy's direction that new components be written in Rust or
//! C where practical.

pub mod bm25;
pub mod format;
pub mod index;
pub mod tokenize;

pub use index::{BuildStats, DocRecord, Index, QueryResult};
