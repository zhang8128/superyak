//! CLI: `corpus-index build --docs <docs.tsv> --links <links.tsv> --out <index.bin>` and
//! `corpus-index query --index <index.bin> [--k N]` (queries read from stdin, see `cmd_query`).

use std::collections::HashMap;
use std::env;
use std::fs;
use std::io::{self, BufRead, BufWriter, Write};
use std::process::ExitCode;
use std::time::Instant;

use corpus_index::{DocRecord, Index};

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

/// `docs.tsv`: one line per document, `page_id\ttitle\ttext`. Read as bytes and lossy-decoded so
/// a stray non-UTF-8 byte in a huge export can't crash the build.
fn read_docs(path: &str) -> Result<Vec<DocRecord>, String> {
    let data = fs::read(path).map_err(|e| format!("reading {path}: {e}"))?;
    let text = String::from_utf8_lossy(&data);
    let mut docs = Vec::new();
    for (lineno, line) in text.lines().enumerate() {
        if line.is_empty() {
            continue;
        }
        let mut parts = line.splitn(3, '\t');
        let page_id_s = parts.next().unwrap_or("");
        let title = parts.next().unwrap_or("").to_string();
        let body = parts.next().unwrap_or("").to_string();
        let page_id: u64 = page_id_s
            .parse()
            .map_err(|_| format!("{path} line {}: bad page id {:?}", lineno + 1, page_id_s))?;
        docs.push(DocRecord { page_id, title, text: body });
    }
    Ok(docs)
}

/// `links.tsv`: one line per link, `src_page_id\tdst_page_id`.
fn read_links(path: &str) -> Result<Vec<(u64, u64)>, String> {
    let data = fs::read(path).map_err(|e| format!("reading {path}: {e}"))?;
    let text = String::from_utf8_lossy(&data);
    let mut links = Vec::new();
    for (lineno, line) in text.lines().enumerate() {
        if line.is_empty() {
            continue;
        }
        let mut parts = line.splitn(2, '\t');
        let src_s = parts.next().unwrap_or("");
        let dst_s = parts.next().unwrap_or("");
        let src: u64 = src_s
            .parse()
            .map_err(|_| format!("{path} line {}: bad src page id {:?}", lineno + 1, src_s))?;
        let dst: u64 = dst_s
            .parse()
            .map_err(|_| format!("{path} line {}: bad dst page id {:?}", lineno + 1, dst_s))?;
        links.push((src, dst));
    }
    Ok(links)
}

fn cmd_build(opts: &HashMap<String, String>) -> Result<(), String> {
    let docs_path = opts.get("docs").ok_or("missing --docs")?;
    let links_path = opts.get("links").ok_or("missing --links")?;
    let out_path = opts.get("out").ok_or("missing --out")?;

    let start = Instant::now();
    let docs = read_docs(docs_path)?;
    let links = read_links(links_path)?;
    let (index, stats) = Index::build(&docs, &links);
    let bytes = index.to_bytes();
    fs::write(out_path, &bytes).map_err(|e| format!("writing {out_path}: {e}"))?;
    let seconds = start.elapsed().as_secs_f64();

    println!(
        "{{\"docs\":{},\"terms\":{},\"postings\":{},\"links_kept\":{},\"links_dropped\":{},\"seconds\":{:.3}}}",
        stats.docs, stats.terms, stats.postings, stats.links_kept, stats.links_dropped, seconds
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
        let result = index.query(query, k);
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
