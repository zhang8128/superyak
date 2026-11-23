//! Integration tests that exercise the real compiled binary as a subprocess, the way
//! `hotpot_open_rs.py` will: `build` from TSV files on disk, then `query` reading stdin lines
//! (including hostile ones) and writing stdout lines.

use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_corpus-index"))
}

fn write_fixture(dir: &std::path::Path) -> (PathBuf, PathBuf) {
    let docs = dir.join("docs.tsv");
    let links = dir.join("links.tsv");
    std::fs::write(
        &docs,
        "1\tLotus (band)\tLotus is a band whose singer was Ann Vale.\n\
         2\tAnn Vale\tAnn Vale grew up in Leeds in 1970.\n\
         3\tLotus Temple\tThe Lotus Temple is a building in Delhi.\n",
    )
    .unwrap();
    std::fs::write(&links, "1\t2\n1\t999\n999\t2\n").unwrap(); // 999 isn't a doc: dropped
    (docs, links)
}

fn build_index(dir: &std::path::Path) -> PathBuf {
    let (docs, links) = write_fixture(dir);
    let index = dir.join("index.bin");
    let output = Command::new(bin())
        .args(["build", "--docs"])
        .arg(&docs)
        .arg("--links")
        .arg(&links)
        .arg("--out")
        .arg(&index)
        .output()
        .expect("spawning corpus-index build");
    assert!(output.status.success(), "build failed: {}", String::from_utf8_lossy(&output.stderr));
    let summary = String::from_utf8_lossy(&output.stdout);
    assert!(summary.contains("\"docs\":3"), "summary: {summary}");
    assert!(summary.contains("\"links_kept\":1"), "summary: {summary}");
    assert!(summary.contains("\"links_dropped\":2"), "summary: {summary}");
    index
}

fn run_query(index: &std::path::Path, k: &str, stdin_bytes: &[u8]) -> (String, bool) {
    let mut child = Command::new(bin())
        .args(["query", "--index"])
        .arg(index)
        .arg("--k")
        .arg(k)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawning corpus-index query");
    child.stdin.take().unwrap().write_all(stdin_bytes).unwrap();
    let output = child.wait_with_output().expect("waiting for corpus-index query");
    (String::from_utf8_lossy(&output.stdout).into_owned(), output.status.success())
}

#[test]
fn build_then_query_round_trip_via_the_real_binary() {
    let dir = tempdir();
    let index = build_index(dir.path());
    let (stdout, ok) = run_query(&index, "2", b"q1\tWhere did the singer of the band Lotus grow up\n");
    assert!(ok);
    let line = stdout.lines().next().expect("one output line");
    let fields: Vec<&str> = line.split('\t').collect();
    assert_eq!(fields.len(), 3);
    assert_eq!(fields[0], "q1");
    assert_eq!(fields[1], "1,3");
    assert_eq!(fields[2], "1,2");
}

#[test]
fn an_unknown_word_query_gives_empty_fields_and_exit_code_zero() {
    let dir = tempdir();
    let index = build_index(dir.path());
    let (stdout, ok) = run_query(&index, "2", b"q1\txyzzyplughquux nosuchword\n");
    assert!(ok);
    assert_eq!(stdout.lines().next().unwrap(), "q1\t\t");
}

#[test]
fn an_empty_query_text_gives_empty_fields() {
    let dir = tempdir();
    let index = build_index(dir.path());
    let (stdout, ok) = run_query(&index, "2", b"q1\t\n");
    assert!(ok);
    assert_eq!(stdout.lines().next().unwrap(), "q1\t\t");
}

#[test]
fn invalid_utf8_in_one_query_line_does_not_crash_and_later_lines_still_answer() {
    let dir = tempdir();
    let index = build_index(dir.path());
    let mut input = Vec::new();
    input.extend_from_slice(b"bad\t");
    input.extend_from_slice(&[0xFF, 0xFE, 0xC0, 0xAF]); // never valid UTF-8
    input.push(b'\n');
    input.extend_from_slice(b"good\tLotus band singer\n");
    let (stdout, ok) = run_query(&index, "1", &input);
    assert!(ok, "the process must exit cleanly even after an invalid-UTF-8 line");
    let lines: Vec<&str> = stdout.lines().collect();
    assert_eq!(lines.len(), 2, "both lines must still produce output: {lines:?}");
    assert!(lines[0].starts_with("bad\t"));
    // doc 1's only out-link (doc 2, "Ann Vale") scores 0 for these terms, so the hop falls back
    // to BM25's rank-2 pick (doc 3), not doc 1 again.
    assert_eq!(lines[1], "good\t1\t1,3");
}

#[test]
fn a_huge_query_line_does_not_crash() {
    let dir = tempdir();
    let index = build_index(dir.path());
    let mut input = Vec::new();
    input.extend_from_slice(b"huge\t");
    input.extend_from_slice(&b"nosuchword ".repeat(500_000));
    input.extend_from_slice(b"Lotus band singer\n");
    let (stdout, ok) = run_query(&index, "1", &input);
    assert!(ok);
    assert_eq!(stdout.lines().next().unwrap(), "huge\t1\t1,3");
}

#[test]
fn a_blank_stdin_line_is_skipped_without_crashing() {
    let dir = tempdir();
    let index = build_index(dir.path());
    let (stdout, ok) = run_query(&index, "1", b"\n\nq1\tLotus band singer\n");
    assert!(ok);
    assert_eq!(stdout.lines().collect::<Vec<_>>(), vec!["q1\t1\t1,3"]);
}

/// A minimal, dependency-free temp directory: a unique path under the OS temp dir, removed on
/// drop. `std::env::temp_dir()` plus the process id and an incrementing counter is enough to
/// avoid collisions between the tests in this file, which is all a `cargo test --offline` binary
/// without a `tempfile` crate needs.
struct TempDir(PathBuf);

impl TempDir {
    fn path(&self) -> &std::path::Path {
        &self.0
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn tempdir() -> TempDir {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let n = COUNTER.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!("corpus-index-test-{}-{}", std::process::id(), n));
    std::fs::create_dir_all(&dir).unwrap();
    TempDir(dir)
}
