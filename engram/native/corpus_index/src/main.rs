//! CLI: `corpus-index build --docs <docs.tsv> --links <links.tsv> --out <index.bin>` and
//! `corpus-index query --index <index.bin> [--k N]` (queries read from stdin, see `cmd_query`).

use std::collections::HashMap;
use std::env;
use std::fs;
use std::fs::File;
use std::io::{self, BufRead, BufWriter, Write};
use std::path::Path;
use std::process::ExitCode;
use std::time::Instant;

use corpus_index::Index;

fn parse_opts(args: &[String]) -> HashMap<String, String> {
    let mut map = HashMap::new();
    let mut i = 0;
    while i < args.len() {
        if let Some(name) = args[i].strip_prefix("--") {
            let value = args.get(i + 1).cloned().unwrap_or_default();
            map.insert(name.to_string(), value);
            i += 2;
        } else {
            i += 1;
        }
    }
    map
}

/// `docs.tsv` and `links.tsv` are each streamed from disk twice (`Index::build_from_paths`),
/// never fully read into memory, and the index is streamed straight to `--out` through a
/// `BufWriter` (`Index::write_to`), never fully materialized as a second in-memory copy before
/// writing -- so peak memory stays well under the input corpus's size rather than some multiple
/// of it. 256 KiB is a plain sequential-read buffer size, not tuned to anything.
const BUILD_READ_BUFFER: usize = 256 * 1024;

fn cmd_build(opts: &HashMap<String, String>) -> Result<(), String> {
    let docs_path = opts.get("docs").ok_or("missing --docs")?;
    let links_path = opts.get("links").ok_or("missing --links")?;
    let out_path = opts.get("out").ok_or("missing --out")?;

    let start = Instant::now();
    let (index, stats) =
        Index::build_from_paths(Path::new(docs_path), Path::new(links_path), BUILD_READ_BUFFER)?;
    let file = File::create(out_path).map_err(|e| format!("writing {out_path}: {e}"))?;
    let mut writer = BufWriter::new(file);
    index.write_to(&mut writer).map_err(|e| format!("writing {out_path}: {e}"))?;
    writer.flush().map_err(|e| format!("writing {out_path}: {e}"))?;
    let seconds = start.elapsed().as_secs_f64();

    println!(
        "{{\"docs\":{},\"terms\":{},\"postings\":{},\"links_kept\":{},\"links_dropped\":{},\"edges\":{},\"seconds\":{:.3}}}",
        stats.docs, stats.terms, stats.postings, stats.links_kept, stats.links_dropped,
        index.edge_count(), seconds
    );
    Ok(())
}

/// Reads `qid\tquery text` lines from stdin, one at a time (so memory stays bounded by one line,
/// not the whole batch), and writes `qid\t<bm25 csv>\t<hop csv>` to stdout. A line is read as raw
/// bytes and lossy-decoded, so invalid UTF-8 on one line can't stop the rest of the batch. A line
/// with no tab is treated as an id with an empty query (so it still produces an output line, with
/// empty fields, rather than being silently skipped or erroring).
fn cmd_query(opts: &HashMap<String, String>) -> Result<(), String> {
    let index_path = opts.get("index").ok_or("missing --index")?;
    let k: usize = match opts.get("k") {
        Some(v) => v.parse().map_err(|_| format!("bad --k value {v:?}"))?,
        None => 10,
    };

    let bytes = fs::read(index_path).map_err(|e| format!("reading {index_path}: {e}"))?;
    let index = Index::from_bytes(&bytes)?;

    let stdin = io::stdin();
    let mut reader = stdin.lock();
    let stdout = io::stdout();
    let mut out = BufWriter::new(stdout.lock());
    let mut buf: Vec<u8> = Vec::new();

    let mut scratch = index.scratch();
    loop {
        buf.clear();
        let n = reader.read_until(b'\n', &mut buf).map_err(|e| format!("reading stdin: {e}"))?;
        if n == 0 {
            break; // EOF
        }
        while matches!(buf.last(), Some(b'\n') | Some(b'\r')) {
            buf.pop();
        }
        if buf.is_empty() {
            continue;
        }
        let line = String::from_utf8_lossy(&buf);
        let (qid, query) = match line.split_once('\t') {
            Some((q, rest)) => (q, rest),
            None => (line.as_ref(), ""),
        };
        let result = index.query_with(&mut scratch, query, k);
        let bm25_field = result.bm25.iter().map(u64::to_string).collect::<Vec<_>>().join(",");
        let hop_field = result.hop.iter().map(u64::to_string).collect::<Vec<_>>().join(",");
        writeln!(out, "{qid}\t{bm25_field}\t{hop_field}").map_err(|e| format!("writing output: {e}"))?;
    }
    out.flush().map_err(|e| format!("flushing output: {e}"))?;
    Ok(())
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: corpus-index <build|query> [options]");
        return ExitCode::from(2);
    }
    let opts = parse_opts(&args[2..]);
    let result = match args[1].as_str() {
        "build" => cmd_build(&opts),
        "query" => cmd_query(&opts),
        other => Err(format!("unknown subcommand {other:?} (expected build or query)")),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("corpus-index: error: {e}");
            ExitCode::FAILURE
        }
    }
}
