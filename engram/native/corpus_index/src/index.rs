//! The index itself: building it from docs + links, writing/reading the binary format, and
//! answering a BM25 query plus its one-hop pick.
//!
//! Two build paths produce byte-for-byte the same [`Index`] (see
//! `streaming_build_from_paths_matches_the_in_memory_build_byte_for_byte` below): [`Index::build`]
//! takes already-parsed slices, for small in-memory fixtures; [`Index::build_from_paths`] streams
//! `docs.tsv` and `links.tsv` from disk -- each exactly twice -- and allocates the postings and
//! link-edge arrays once, at their exact final size, from counts gathered in a first pass. The
//! CLI's `build` uses the streaming path; its peak memory is dominated by the postings array
//! (sized exactly, no growth slack) rather than by the input files' size. The format itself (the
//! layout below) and its version are unchanged by this: it was always a flat, exactly-allocated
//! layout on disk, independent of how construction got there.
//!
//! Binary layout (all little-endian), written by [`Index::write_to`] (streamed) or
//! [`Index::to_bytes`] (collected into one `Vec<u8>`, for tests) and read back by
//! [`Index::from_bytes`]:
//!
//! ```text
//! magic            [u8; 4]      b"CIX1"
//! version          u32
//! doc_count        u64          N
//! avg_doc_len      f64
//! for each of N docs, in build order (doc index 0..N):
//!     page_id      u64
//!     doc_len      u32          token count, for BM25 length normalization
//! vocab_count      u64          V, number of distinct terms
//! for each term, sorted ascending by UTF-8 bytes:
//!     term_len     u32
//!     term_bytes   [u8; term_len]
//!     doc_freq     u32          df(t)
//!     postings_off u64          index into the postings array below where this term's run starts
//! postings_count   u64          P == sum of doc_freq over all terms
//! for each of P postings, grouped by term in vocab order, sorted by doc_idx within a term:
//!     doc_idx      u32
//!     tf           u16          saturating at u16::MAX
//! edge_count       u64          E
//! csr_offsets      [u64; N + 1] cumulative edge count per source doc index
//! csr_edges        [u32; E]     target doc index, sorted + deduped within a source
//! ```

use std::collections::HashMap;
use std::fs::File;
use std::io::{self, BufReader, Write};
use std::path::Path;

use crate::bm25::{idf, term_contribution};
use crate::format::{ByteReader, ByteWriter, MAGIC, VERSION};
use crate::tokenize::tokenize;

/// One input document, as read from `docs.tsv`.
pub struct DocRecord {
    pub page_id: u64,
    pub title: String,
    pub text: String,
}

struct VocabEntry {
    term: String,
    doc_freq: u32,
    postings_offset: u64,
}

pub struct Index {
    doc_count: u64,
    avg_doc_len: f64,
    page_ids: Vec<u64>,
    doc_lens: Vec<u32>,
    vocab: Vec<VocabEntry>,
    postings: Vec<(u32, u16)>,
    csr_offsets: Vec<u64>,
    csr_edges: Vec<u32>,
}

/// Counts printed in `build`'s JSON summary line.
pub struct BuildStats {
    pub docs: usize,
    pub terms: usize,
    pub postings: usize,
    pub links_kept: usize,
    pub links_dropped: usize,
}

/// One query's picks: BM25's top-k page ids, and the hop's two page ids (fewer, or none, when
/// there is nothing to pick).
pub struct QueryResult {
    pub bm25: Vec<u64>,
    pub hop: Vec<u64>,
}

/// A query's working memory, from `Index::scratch`: one score slot per doc (all 0.0 between
/// queries), the docs this query touched, and a copy of them to zero the slots afterwards.
pub struct Scratch {
    acc: Vec<f64>,
    touched: Vec<u32>,
    touched_all: Vec<u32>,
}

impl Index {
    /// Build an index from documents (in the order they define doc index 0..N) and links
    /// (`src_page_id`, `dst_page_id`). A link is kept only when both ends resolve to a document
    /// in `docs`; otherwise it is dropped and counted.
    pub fn build(docs: &[DocRecord], links: &[(u64, u64)]) -> (Index, BuildStats) {
        let n = docs.len();
        let mut page_ids = Vec::with_capacity(n);
        let mut doc_lens = Vec::with_capacity(n);
        let mut page_id_to_idx: HashMap<u64, u32> = HashMap::with_capacity(n);
        let mut term_postings: HashMap<String, Vec<(u32, u16)>> = HashMap::new();
        let mut total_len: u64 = 0;

        for (idx, doc) in docs.iter().enumerate() {
            let idx_u32 = idx as u32;
            page_ids.push(doc.page_id);
            page_id_to_idx.entry(doc.page_id).or_insert(idx_u32);

            let mut combined = String::with_capacity(doc.title.len() + 1 + doc.text.len());
            combined.push_str(&doc.title);
            combined.push(' ');
            combined.push_str(&doc.text);
            let tokens = tokenize(&combined);
            doc_lens.push(tokens.len() as u32);
            total_len += tokens.len() as u64;

            let mut counts: HashMap<String, u32> = HashMap::new();
            for tok in tokens {
                *counts.entry(tok).or_insert(0) += 1;
            }
            for (term, count) in counts {
                let tf = count.min(u16::MAX as u32) as u16; // saturating, never wrapping
                term_postings.entry(term).or_default().push((idx_u32, tf));
            }
        }

        let avg_doc_len = if n > 0 { total_len as f64 / n as f64 } else { 0.0 };

        let mut terms: Vec<String> = term_postings.keys().cloned().collect();
        terms.sort();

        let mut vocab = Vec::with_capacity(terms.len());
        let mut postings: Vec<(u32, u16)> = Vec::new();
        for term in terms {
            let mut plist = term_postings.remove(&term).unwrap();
            plist.sort_by_key(|(doc_idx, _)| *doc_idx);
            let offset = postings.len() as u64;
            let doc_freq = plist.len() as u32;
            postings.extend(plist);
            vocab.push(VocabEntry { term, doc_freq, postings_offset: offset });
        }

        let mut adjacency: Vec<Vec<u32>> = vec![Vec::new(); n];
        let mut links_kept = 0usize;
        let mut links_dropped = 0usize;
        for &(src, dst) in links {
            match (page_id_to_idx.get(&src), page_id_to_idx.get(&dst)) {
                (Some(&s), Some(&d)) => {
                    adjacency[s as usize].push(d);
                    links_kept += 1;
                }
                _ => links_dropped += 1,
            }
        }
        let mut csr_offsets = Vec::with_capacity(n + 1);
        let mut csr_edges = Vec::new();
        csr_offsets.push(0u64);
        for mut row in adjacency {
            row.sort_unstable();
            row.dedup();
            csr_edges.extend_from_slice(&row);
            csr_offsets.push(csr_edges.len() as u64);
        }

        let stats = BuildStats {
            docs: n,
            terms: vocab.len(),
            postings: postings.len(),
            links_kept,
            links_dropped,
        };
        let index = Index {
            doc_count: n as u64,
            avg_doc_len,
            page_ids,
            doc_lens,
            vocab,
            postings,
            csr_offsets,
            csr_edges,
        };
        (index, stats)
    }

    /// The same algorithm as [`Index::build`], but streaming `docs_path` and `links_path` from
    /// disk -- each read exactly twice -- instead of requiring every document's text and a
    /// growable postings list per term to sit in memory at once.
    ///
    /// Pass 1 over `docs.tsv` builds the vocabulary (term -> document frequency), each doc's
    /// page id and length, and the page-id -> doc-index map, without keeping any text or per-term
    /// postings. The vocabulary is then sorted once (as `build` already does) and each term's
    /// exact postings range is fixed by a prefix sum over its document frequency, so the postings
    /// array can be allocated once, at its final size -- a flat `Vec<(u32, u16)>`, not a `Vec`
    /// per term. Pass 2 re-reads `docs.tsv`, retokenizes each doc, and writes each (doc, term)
    /// pair directly into its term's reserved slot (tracked by a per-term write cursor); because
    /// pass 2 visits docs in increasing doc-index order, each term's postings come out already
    /// sorted by doc index, with no separate sort needed. `links.tsv` gets the same treatment:
    /// one pass counts each source doc's raw out-degree (to size one flat edges array exactly),
    /// a second pass fills it, and a final linear pass sorts, dedupes and compacts each source
    /// doc's edges in place within that same array (no second buffer) to match `build`'s
    /// sort-then-dedup adjacency rows exactly.
    ///
    /// `buf_capacity` is each file's internal read buffer size, in bytes (the CLI passes a
    /// multi-KB buffer; a test can pass something tiny to force many refills deterministically,
    /// including mid-line, regardless of how long a single line is).
    pub fn build_from_paths(docs_path: &Path, links_path: &Path, buf_capacity: usize)
            -> Result<(Index, BuildStats), String> {
        // ---- docs pass 1: vocabulary (term -> df), page ids, doc lengths, page_id -> doc idx ----
        let mut page_ids: Vec<u64> = Vec::new();
        let mut doc_lens: Vec<u32> = Vec::new();
        let mut df: HashMap<String, u32> = HashMap::new();
        let mut page_id_to_idx: HashMap<u64, u32> = HashMap::new();
        let mut local_counts: HashMap<String, u32> = HashMap::new(); // cleared and reused per doc

        stream_file_lines(docs_path, buf_capacity, |line| {
            let (page_id, title, text) = parse_doc_line(line)?;
            let idx = page_ids.len() as u32;
            page_ids.push(page_id);
            page_id_to_idx.entry(page_id).or_insert(idx);

            let combined = combined_text(title, text);
            let len = count_terms(&combined, &mut local_counts);
            doc_lens.push(len);
            for term in local_counts.keys() {
                // `.get_mut` first avoids cloning `term` for every occurrence; a term is only
                // ever cloned the first time it's seen, when it enters the vocabulary.
                if let Some(count) = df.get_mut(term) {
                    *count += 1;
                } else {
                    df.insert(term.clone(), 1);
                }
            }
            Ok(())
        })?;

        let n = page_ids.len();
        let total_len: u64 = doc_lens.iter().map(|&l| l as u64).sum();
        let avg_doc_len = if n > 0 { total_len as f64 / n as f64 } else { 0.0 };

        // ---- sort the vocabulary by term bytes, fix each term's exact postings range ----
        let mut vocab: Vec<VocabEntry> = df
            .into_iter()
            .map(|(term, doc_freq)| VocabEntry { term, doc_freq, postings_offset: 0 })
            .collect();
        vocab.sort_by(|a, b| a.term.cmp(&b.term));
        let mut running = 0u64;
        for entry in &mut vocab {
            entry.postings_offset = running;
            running += entry.doc_freq as u64;
        }
        let postings_count = running as usize;

        // ---- docs pass 2: fill the exactly-sized, flat postings array ----
        let mut postings: Vec<(u32, u16)> = vec![(0u32, 0u16); postings_count];
        let mut cursor: Vec<u32> = vec![0u32; vocab.len()];
        let mut local_counts2: HashMap<String, u32> = HashMap::new();
        let mut doc_idx: u32 = 0;

        stream_file_lines(docs_path, buf_capacity, |line| {
            let (_page_id, title, text) = parse_doc_line(line)?;
            let combined = combined_text(title, text);
            count_terms(&combined, &mut local_counts2);
            for (term, &count) in local_counts2.iter() {
                let tf = count.min(u16::MAX as u32) as u16;
                if let Ok(vi) = vocab.binary_search_by(|v| v.term.as_str().cmp(term.as_str())) {
                    let off = vocab[vi].postings_offset as usize;
                    let c = cursor[vi] as usize;
                    postings[off + c] = (doc_idx, tf);
                    cursor[vi] += 1;
                }
            }
            doc_idx += 1;
            Ok(())
        })?;

        // ---- links pass A: count each source doc's raw out-degree (both ends must resolve) ----
        let mut raw_degree: Vec<u32> = vec![0u32; n];
        let mut links_kept = 0usize;
        let mut links_dropped = 0usize;
        stream_file_lines(links_path, buf_capacity, |line| {
            let (src, dst) = parse_link_line(line)?;
            match (page_id_to_idx.get(&src), page_id_to_idx.get(&dst)) {
                (Some(&s), Some(_)) => {
                    raw_degree[s as usize] += 1;
                    links_kept += 1;
                }
                _ => links_dropped += 1,
            }
            Ok(())
        })?;

        let mut raw_offsets: Vec<u64> = Vec::with_capacity(n + 1);
        raw_offsets.push(0);
        for &d in &raw_degree {
            raw_offsets.push(raw_offsets.last().unwrap() + d as u64);
        }
        let raw_total = *raw_offsets.last().unwrap() as usize;

        // ---- links pass B: fill the exactly-sized raw edges array ----
        let mut raw_edges: Vec<u32> = vec![0u32; raw_total];
        let mut fill_cursor: Vec<u32> = vec![0u32; n];
        stream_file_lines(links_path, buf_capacity, |line| {
            let (src, dst) = parse_link_line(line)?;
            if let (Some(&s), Some(&d)) = (page_id_to_idx.get(&src), page_id_to_idx.get(&dst)) {
                let pos = raw_offsets[s as usize] as usize + fill_cursor[s as usize] as usize;
                raw_edges[pos] = d;
                fill_cursor[s as usize] += 1;
            }
            Ok(())
        })?;

        // ---- compact in place: sort + dedup each source doc's raw edges, matching `build`'s
        //      per-row sort_unstable()+dedup(), shifting each row left onto the row before it so
        //      the same Vec ends up holding exactly the final (deduped) edges, with no second
        //      allocation ----
        let mut final_degree: Vec<u32> = vec![0u32; n];
        let mut compacted = 0usize;
        for i in 0..n {
            let start = raw_offsets[i] as usize;
            let end = raw_offsets[i + 1] as usize;
            raw_edges[start..end].sort_unstable();
            let deduped_len = dedup_in_place(&mut raw_edges[start..end]);
            final_degree[i] = deduped_len as u32;
            if compacted != start {
                raw_edges.copy_within(start..start + deduped_len, compacted);
            }
            compacted += deduped_len;
        }
        raw_edges.truncate(compacted);
        let csr_edges = raw_edges;
        let mut csr_offsets: Vec<u64> = Vec::with_capacity(n + 1);
        csr_offsets.push(0);
        for &d in &final_degree {
            csr_offsets.push(csr_offsets.last().unwrap() + d as u64);
        }

        let stats = BuildStats { docs: n, terms: vocab.len(), postings: postings.len(), links_kept, links_dropped };
        let index = Index {
            doc_count: n as u64,
            avg_doc_len,
            page_ids,
            doc_lens,
            vocab,
            postings,
            csr_offsets,
            csr_edges,
        };
        Ok((index, stats))
    }

    /// Writes the same bytes [`Index::to_bytes`] would return, but through any `Write`, one field
    /// at a time -- so the CLI's `build` can stream straight to a `BufWriter<File>` instead of
    /// materializing the whole (at full corpus scale, multi-gigabyte) index as a second in-memory
    /// copy before writing it out.
    pub fn write_to<W: Write>(&self, out: W) -> io::Result<()> {
        let mut w = ByteWriter::new(out);
        w.bytes(&MAGIC)?;
        w.u32(VERSION)?;
        w.u64(self.doc_count)?;
        w.f64(self.avg_doc_len)?;
        for i in 0..self.doc_count as usize {
            w.u64(self.page_ids[i])?;
            w.u32(self.doc_lens[i])?;
        }
        w.u64(self.vocab.len() as u64)?;
        for v in &self.vocab {
            let bytes = v.term.as_bytes();
            w.u32(bytes.len() as u32)?;
            w.bytes(bytes)?;
            w.u32(v.doc_freq)?;
            w.u64(v.postings_offset)?;
        }
        w.u64(self.postings.len() as u64)?;
        for &(doc_idx, tf) in &self.postings {
            w.u32(doc_idx)?;
            w.u16(tf)?;
        }
        w.u64(self.csr_edges.len() as u64)?;
        for &off in &self.csr_offsets {
            w.u64(off)?;
        }
        for &e in &self.csr_edges {
            w.u32(e)?;
        }
        Ok(())
    }

    /// The same bytes `write_to` streams, collected into one `Vec<u8>` -- convenient for the unit
    /// tests' tiny fixtures; writing to a `Vec<u8>` cannot fail.
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut buf = Vec::new();
        self.write_to(&mut buf).expect("writing to an in-memory Vec<u8> cannot fail");
        buf
    }

    /// Reads an index written by `write_to`. Every count is checked against the bytes left before it
    /// sizes an allocation, and the parts are checked against each other, so a corrupt file is an
    /// error here and a query on a loaded index can't index out of bounds or break the scoring's
    /// invariants (a posting's tf >= 1 keeps every contribution > 0; the vocabulary is sorted).
    pub fn from_bytes(buf: &[u8]) -> Result<Index, String> {
        let mut r = ByteReader::new(buf);
        let magic = r.bytes(4)?;
        if magic != MAGIC {
            return Err("not a corpus-index file (bad magic)".to_string());
        }
        let version = r.u32()?;
        if version != VERSION {
            return Err(format!("unsupported index version {version}"));
        }
        let doc_count = r.u64()?;
        let avg_doc_len = r.f64()?;
        if !(avg_doc_len.is_finite() && avg_doc_len >= 0.0) {
            return Err(format!("bad average doc length {avg_doc_len}"));
        }
        if doc_count > u32::MAX as u64 {
            return Err(format!("{doc_count} docs is more than a u32 doc index can name"));
        }
        let n = r.fits(doc_count, 12, "docs")?;
        let mut page_ids = Vec::with_capacity(n);
        let mut doc_lens = Vec::with_capacity(n);
        for _ in 0..n {
            page_ids.push(r.u64()?);
            doc_lens.push(r.u32()?);
        }
        let vocab_count = r.u64()?;
        let mut vocab: Vec<VocabEntry> = Vec::with_capacity(r.fits(vocab_count, 16, "terms")?);
        for _ in 0..vocab_count {
            let len = r.u32()? as usize;
            let bytes = r.bytes(len)?;
            let term = String::from_utf8(bytes.to_vec()).map_err(|_| "bad utf-8 in index term".to_string())?;
            let doc_freq = r.u32()?;
            let postings_offset = r.u64()?;
            if doc_freq == 0 {
                return Err(format!("term {term:?} has no documents"));
            }
            if vocab.last().is_some_and(|prev| prev.term >= term) {
                return Err(format!("vocabulary not strictly sorted at {term:?}"));
            }
            vocab.push(VocabEntry { term, doc_freq, postings_offset });
        }
        let postings_count = r.u64()?;
        let mut postings = Vec::with_capacity(r.fits(postings_count, 6, "postings")?);
        for _ in 0..postings_count {
            let doc_idx = r.u32()?;
            let tf = r.u16()?;
            if doc_idx as u64 >= doc_count || tf == 0 {
                return Err(format!("posting ({doc_idx}, {tf}) names no doc or has tf 0"));
            }
            postings.push((doc_idx, tf));
        }
        for v in &vocab {
            if v.postings_offset.checked_add(v.doc_freq as u64).is_none_or(|end| end > postings_count) {
                return Err(format!("term {:?}'s postings run past the postings array", v.term));
            }
        }
        let edge_count = r.u64()?;
        let mut csr_offsets = Vec::with_capacity(r.fits(doc_count + 1, 8, "link offsets")?);
        for _ in 0..=n {
            let offset = r.u64()?;
            if offset > edge_count || csr_offsets.last().is_some_and(|&prev| offset < prev) {
                return Err(format!("link offset {offset} out of order or past {edge_count} edges"));
            }
            csr_offsets.push(offset);
        }
        if csr_offsets.first() != Some(&0) || csr_offsets.last() != Some(&edge_count) {
            return Err("link offsets don't run from 0 to the edge count".to_string());
        }
        let mut csr_edges = Vec::with_capacity(r.fits(edge_count, 4, "edges")?);
        for _ in 0..edge_count {
            let target = r.u32()?;
            if target as u64 >= doc_count {
                return Err(format!("link target {target} names no doc"));
            }
            csr_edges.push(target);
        }
        if r.remaining() != 0 {
            return Err(format!("{} bytes trail the index", r.remaining()));
        }
        Ok(Index { doc_count, avg_doc_len, page_ids, doc_lens, vocab, postings, csr_offsets, csr_edges })
    }

    fn vocab_lookup(&self, term: &str) -> Option<&VocabEntry> {
        self.vocab.binary_search_by(|v| v.term.as_str().cmp(term)).ok().map(|i| &self.vocab[i])
    }

    fn postings_for(&self, v: &VocabEntry) -> &[(u32, u16)] {
        let start = v.postings_offset as usize;
        let end = start + v.doc_freq as usize;
        &self.postings[start..end]
    }

    /// The query's distinct terms, tokenized, in first-seen order (scoring is order-independent;
    /// dedup just avoids double-counting a repeated word).
    fn query_terms(&self, query: &str) -> Vec<String> {
        let mut seen = std::collections::HashSet::new();
        let mut out = Vec::new();
        for tok in tokenize(query) {
            if seen.insert(tok.clone()) {
                out.push(tok);
            }
        }
        out
    }

    /// Reusable per-query buffers: a dense score per doc and the list of docs a query touched, so
    /// a query costs its postings, not a hash map of millions of entries. One per querying thread.
    pub fn scratch(&self) -> Scratch {
        Scratch { acc: vec![0.0; self.doc_lens.len()], touched: Vec::new(), touched_all: Vec::new() }
    }

    /// Adds every doc's BM25 score for `terms` into `scratch` (zeroed beforehand). Each doc's
    /// contributions are added in `terms` order, the order the map-based reference adds them in, so
    /// every sum is bit-for-bit the same. A posting's contribution is always > 0 (tf >= 1, idf > 0),
    /// so a slot still at 0.0 is one this query hasn't touched yet.
    fn accumulate(&self, terms: &[String], scratch: &mut Scratch) {
        for term in terms {
            if let Some(v) = self.vocab_lookup(term) {
                let idf_value = idf(self.doc_count, v.doc_freq);
                for &(doc_idx, tf) in self.postings_for(v) {
                    let doc_len = self.doc_lens[doc_idx as usize];
                    let contribution = term_contribution(idf_value, tf, doc_len, self.avg_doc_len);
                    let slot = &mut scratch.acc[doc_idx as usize];
                    if *slot == 0.0 {
                        scratch.touched.push(doc_idx);
                    }
                    *slot += contribution;
                }
            }
        }
    }

    /// Highest score first, ties broken by the smaller doc index: a partial selection over the
    /// touched docs, then a sort of the `k` kept, in the same total order a full sort uses.
    fn topk_touched(scratch: &mut Scratch, k: usize) -> Vec<(u32, f64)> {
        let acc = &scratch.acc;
        let order = |a: &u32, b: &u32| {
            acc[*b as usize].partial_cmp(&acc[*a as usize]).unwrap_or(std::cmp::Ordering::Equal).then(a.cmp(b))
        };
        let touched = &mut scratch.touched;
        if touched.len() > k && k > 0 {
            touched.select_nth_unstable_by(k - 1, order);
            touched.truncate(k);
        }
        touched.sort_by(order);
        touched.truncate(k);
        touched.iter().map(|&d| (d, acc[d as usize])).collect()
    }

    /// BM25's top-`k` page ids, plus the hop's pick: BM25's top 1, then the out-link scoring
    /// highest (> 0) against the same query; with none, BM25's second pick. A query with no known
    /// terms gives empty fields, never a panic. Allocates its own scratch; a loop should reuse one
    /// with `query_with`.
    pub fn query(&self, query: &str, k: usize) -> QueryResult {
        let mut scratch = self.scratch();
        self.query_with(&mut scratch, query, k)
    }

    pub fn query_with(&self, scratch: &mut Scratch, query: &str, k: usize) -> QueryResult {
        let result = self.query_scored(scratch, query, k);
        for &d in &scratch.touched_all {
            scratch.acc[d as usize] = 0.0;
        }
        scratch.touched_all.clear();
        scratch.touched.clear();
        result
    }

    fn query_scored(&self, scratch: &mut Scratch, query: &str, k: usize) -> QueryResult {
        let terms = self.query_terms(query);
        if terms.is_empty() {
            return QueryResult { bm25: Vec::new(), hop: Vec::new() };
        }
        self.accumulate(&terms, scratch);
        if scratch.touched.is_empty() {
            return QueryResult { bm25: Vec::new(), hop: Vec::new() };
        }
        // The selection reorders and shortens `touched`; keep the full list to zero the slots after.
        scratch.touched_all.clear();
        scratch.touched_all.extend_from_slice(&scratch.touched);
        let need = k.max(2);
        let top = Self::topk_touched(scratch, need);
        let bm25_page_ids: Vec<u64> = top.iter().take(k).map(|&(d, _)| self.page_ids[d as usize]).collect();

        let hop = match top.first() {
            None => Vec::new(),
            Some(&(first_idx, _)) => {
                let start = self.csr_offsets[first_idx as usize] as usize;
                let end = self.csr_offsets[first_idx as usize + 1] as usize;
                let out_links = &self.csr_edges[start..end];
                let mut best: Option<(u32, f64)> = None;
                for &target in out_links {
                    // The out-link's whole BM25 score for this query, already summed in term order.
                    let s = scratch.acc[target as usize];
                    if s > 0.0 {
                        best = match best {
                            None => Some((target, s)),
                            Some((bd, bs)) => {
                                if s > bs || (s == bs && target < bd) {
                                    Some((target, s))
                                } else {
                                    Some((bd, bs))
                                }
                            }
                        };
                    }
                }
                match best {
                    Some((target, _)) => vec![self.page_ids[first_idx as usize], self.page_ids[target as usize]],
                    None => {
                        if top.len() >= 2 {
                            vec![self.page_ids[first_idx as usize], self.page_ids[top[1].0 as usize]]
                        } else {
                            vec![self.page_ids[first_idx as usize]]
                        }
                    }
                }
            }
        };

        QueryResult { bm25: bm25_page_ids, hop }
    }

    // ---- The first, map-based query path, kept verbatim for tests to hold the fast path to. ----

    /// BM25 scores for every doc that contains at least one of `terms`. A term absent from the
    /// vocabulary is simply skipped (it offers no evidence either way).
    #[cfg(test)]
    fn scores_for_terms(&self, terms: &[String]) -> HashMap<u32, f64> {
        let mut scores: HashMap<u32, f64> = HashMap::new();
        for term in terms {
            if let Some(v) = self.vocab_lookup(term) {
                let idf_value = idf(self.doc_count, v.doc_freq);
                for &(doc_idx, tf) in self.postings_for(v) {
                    let doc_len = self.doc_lens[doc_idx as usize];
                    let contribution = term_contribution(idf_value, tf, doc_len, self.avg_doc_len);
                    *scores.entry(doc_idx).or_insert(0.0) += contribution;
                }
            }
        }
        scores
    }

    /// Highest score first, ties broken by the smaller doc index.
    #[cfg(test)]
    fn topk_from_scores(scores: &HashMap<u32, f64>, k: usize) -> Vec<(u32, f64)> {
        let mut v: Vec<(u32, f64)> = scores.iter().map(|(&d, &s)| (d, s)).collect();
        v.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal).then(a.0.cmp(&b.0)));
        v.truncate(k);
        v
    }

    /// One doc's BM25 score against `terms`, computed directly (used for the hop, where the
    /// candidate set is a single document's handful of out-links, not the whole corpus).
    #[cfg(test)]
    fn score_doc_for_terms(&self, doc_idx: u32, terms: &[String]) -> f64 {
        let mut score = 0.0;
        for term in terms {
            if let Some(v) = self.vocab_lookup(term) {
                let postings = self.postings_for(v);
                if let Ok(pos) = postings.binary_search_by_key(&doc_idx, |&(d, _)| d) {
                    let (_, tf) = postings[pos];
                    let idf_value = idf(self.doc_count, v.doc_freq);
                    let doc_len = self.doc_lens[doc_idx as usize];
                    score += term_contribution(idf_value, tf, doc_len, self.avg_doc_len);
                }
            }
        }
        score
    }

    /// BM25's top-`k` page ids, plus the hop's pick: BM25's top 1, then the out-link scoring
    /// highest (> 0) against the same query; with none, BM25's second pick. A query with no known
    /// terms gives empty fields, never a panic.
    #[cfg(test)]
    pub fn query_reference(&self, query: &str, k: usize) -> QueryResult {
        let terms = self.query_terms(query);
        if terms.is_empty() {
            return QueryResult { bm25: Vec::new(), hop: Vec::new() };
        }
        let scores = self.scores_for_terms(&terms);
        if scores.is_empty() {
            return QueryResult { bm25: Vec::new(), hop: Vec::new() };
        }
        let need = k.max(2);
        let top = Self::topk_from_scores(&scores, need);
        let bm25_page_ids: Vec<u64> = top.iter().take(k).map(|&(d, _)| self.page_ids[d as usize]).collect();

        let hop = match top.first() {
            None => Vec::new(),
            Some(&(first_idx, _)) => {
                let start = self.csr_offsets[first_idx as usize] as usize;
                let end = self.csr_offsets[first_idx as usize + 1] as usize;
                let out_links = &self.csr_edges[start..end];
                let mut best: Option<(u32, f64)> = None;
                for &target in out_links {
                    let s = self.score_doc_for_terms(target, &terms);
                    if s > 0.0 {
                        best = match best {
                            None => Some((target, s)),
                            Some((bd, bs)) => {
                                if s > bs || (s == bs && target < bd) {
                                    Some((target, s))
                                } else {
                                    Some((bd, bs))
                                }
                            }
                        };
                    }
                }
                match best {
                    Some((target, _)) => vec![self.page_ids[first_idx as usize], self.page_ids[target as usize]],
                    None => {
                        if top.len() >= 2 {
                            vec![self.page_ids[first_idx as usize], self.page_ids[top[1].0 as usize]]
                        } else {
                            vec![self.page_ids[first_idx as usize]]
                        }
                    }
                }
            }
        };

        QueryResult { bm25: bm25_page_ids, hop }
    }

    pub fn doc_count(&self) -> u64 {
        self.doc_count
    }

    pub fn term_count(&self) -> usize {
        self.vocab.len()
    }

    pub fn postings_count(&self) -> usize {
        self.postings.len()
    }

    pub fn edge_count(&self) -> usize {
        self.csr_edges.len()
    }
}

/// `title + " " + text`, the same combination `build` tokenizes.
fn combined_text(title: &str, text: &str) -> String {
    let mut combined = String::with_capacity(title.len() + 1 + text.len());
    combined.push_str(title);
    combined.push(' ');
    combined.push_str(text);
    combined
}

/// Clears `into`, tokenizes `text`, and counts each token's occurrences into it; returns the
/// token count (the doc's length for BM25's normalization). Shared by both docs passes so they
/// can't drift apart on what counts as a term or a doc's length.
fn count_terms(text: &str, into: &mut HashMap<String, u32>) -> u32 {
    into.clear();
    let mut len = 0u32;
    for tok in tokenize(text) {
        len += 1;
        *into.entry(tok).or_insert(0) += 1;
    }
    len
}

/// `page_id\ttitle\ttext`.
fn parse_doc_line(line: &str) -> Result<(u64, &str, &str), String> {
    let mut parts = line.splitn(3, '\t');
    let page_id_s = parts.next().unwrap_or("");
    let title = parts.next().unwrap_or("");
    let text = parts.next().unwrap_or("");
    let page_id: u64 = page_id_s.parse().map_err(|_| format!("bad page id {page_id_s:?}"))?;
    Ok((page_id, title, text))
}

/// `src_page_id\tdst_page_id`.
fn parse_link_line(line: &str) -> Result<(u64, u64), String> {
    let mut parts = line.splitn(2, '\t');
    let src_s = parts.next().unwrap_or("");
    let dst_s = parts.next().unwrap_or("");
    let src: u64 = src_s.parse().map_err(|_| format!("bad src page id {src_s:?}"))?;
    let dst: u64 = dst_s.parse().map_err(|_| format!("bad dst page id {dst_s:?}"))?;
    Ok((src, dst))
}

/// Calls `f` once per line of the file at `path` (split on `\n`, a trailing `\r` trimmed, blank
/// lines skipped), decoding each line with `String::from_utf8_lossy` so one invalid-UTF-8 line
/// can't stop the read. Reads via `read_until`, so a single line longer than `buf_capacity` is
/// still read whole, across as many internal buffer refills as it takes -- the read buffer is
/// reused across lines, not one allocation per line, and the file is never read into memory at
/// once. An error from `f` or from the read itself is reported with the file and line number.
fn stream_file_lines(path: &Path, buf_capacity: usize, mut f: impl FnMut(&str) -> Result<(), String>)
        -> Result<(), String> {
    let file = File::open(path).map_err(|e| format!("reading {}: {e}", path.display()))?;
    let mut reader = BufReader::with_capacity(buf_capacity.max(64), file);
    let mut buf: Vec<u8> = Vec::new();
    let mut lineno = 0usize;
    loop {
        buf.clear();
        let n = std::io::BufRead::read_until(&mut reader, b'\n', &mut buf)
            .map_err(|e| format!("reading {} line {}: {e}", path.display(), lineno + 1))?;
        if n == 0 {
            break;
        }
        lineno += 1;
        while matches!(buf.last(), Some(b'\n') | Some(b'\r')) {
            buf.pop();
        }
        if buf.is_empty() {
            continue;
        }
        let line = String::from_utf8_lossy(&buf);
        f(&line).map_err(|e| format!("{} line {}: {}", path.display(), lineno, e))?;
    }
    Ok(())
}

/// In-place dedup of consecutive equal elements in an already-sorted slice (the same rule as
/// `Vec::dedup`, usable on a mutable sub-slice of a larger buffer). Returns the deduped length;
/// the caller is responsible for treating only `slice[..len]` as live afterward.
fn dedup_in_place(slice: &mut [u32]) -> usize {
    if slice.is_empty() {
        return 0;
    }
    let mut write = 1;
    for read in 1..slice.len() {
        if slice[read] != slice[write - 1] {
            slice[write] = slice[read];
            write += 1;
        }
    }
    write
}

#[cfg(test)]
mod tests {
    use super::*;

    fn doc(page_id: u64, title: &str, text: &str) -> DocRecord {
        DocRecord { page_id, title: title.to_string(), text: text.to_string() }
    }

    /// The fixture used across these tests: a tiny "band -> singer" link, plus an unrelated
    /// article and one with no text match at all.
    /// A deterministic random corpus with a skewed vocabulary (a few words in most docs, many
    /// rare), duplicate docs for exact score ties, and random links; 500 queries through one
    /// reused scratch must give exactly what the map-based reference gives.
    #[test]
    fn the_dense_path_matches_the_map_based_reference_exactly_on_random_queries() {
        let mut seed: u64 = 0x5eed_1121;
        let mut next = move |m: u64| {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            (seed >> 33) % m
        };
        let words: Vec<String> = (0..60).map(|i| format!("w{i}")).collect();
        let pick = |next: &mut dyn FnMut(u64) -> u64| {
            // Skewed: index = floor(60 * u^3), so low indices (common words) dominate.
            let u = next(1_000_000) as f64 / 1_000_000.0;
            words[((u * u * u) * 60.0) as usize].clone()
        };
        let mut docs = Vec::new();
        for id in 1..=400u64 {
            let len = 1 + next(30);
            let text: Vec<String> = (0..len).map(|_| pick(&mut next)).collect();
            docs.push(doc(id, &format!("T{}", id % 97), &text.join(" ")));
        }
        for id in 401..=420u64 {
            // exact duplicates of earlier docs: same text, same length, so equal scores
            let src = &docs[(id - 401) as usize];
            docs.push(doc(id, &src.title.clone(), &src.text.clone()));
        }
        let mut links = Vec::new();
        for _ in 0..3000 {
            links.push((1 + next(420), 1 + next(440))); // some targets unknown, dropped
        }
        let (index, _) = Index::build(&docs, &links);
        let mut scratch = index.scratch();
        let mut compared = 0;
        for q in 0..500 {
            let n = 1 + next(12);
            let mut terms: Vec<String> = (0..n).map(|_| pick(&mut next)).collect();
            if q % 25 == 0 {
                terms.push("absentword".to_string());
            }
            let query = terms.join(" ");
            for k in [1usize, 2, 5] {
                let fast = index.query_with(&mut scratch, &query, k);
                let slow = index.query_reference(&query, k);
                assert_eq!(fast.bm25, slow.bm25, "bm25 differs for {query:?} k={k}");
                assert_eq!(fast.hop, slow.hop, "hop differs for {query:?} k={k}");
                compared += 1;
            }
        }
        assert_eq!(compared, 1500);
        assert!(scratch.acc.iter().all(|&x| x == 0.0), "the scratch is left clean");
    }

    fn fixture() -> (Vec<DocRecord>, Vec<(u64, u64)>) {
        let docs = vec![
            doc(1, "Lotus (band)", "Lotus is a band whose singer was Ann Vale."),
            doc(2, "Ann Vale", "Ann Vale grew up in Leeds in 1970."),
            doc(3, "Lotus Temple", "The Lotus Temple is a building in Delhi."),
            doc(4, "Unrelated", "Nothing about flowers or music here at all."),
        ];
        let links = vec![(1, 2)]; // Lotus (band) -> Ann Vale
        (docs, links)
    }

    #[test]
    fn bm25_ranks_the_more_specific_match_first() {
        let (docs, links) = fixture();
        let (index, _) = Index::build(&docs, &links);
        let result = index.query("Lotus band singer", 4);
        assert_eq!(result.bm25.first(), Some(&1)); // "Lotus (band)" has all three terms
    }

    #[test]
    fn the_hop_follows_a_link_bm25_alone_would_miss() {
        let (docs, links) = fixture();
        let (index, _) = Index::build(&docs, &links);
        let result = index.query("Where did the singer of the band Lotus grow up", 2);
        assert_eq!(result.bm25.first(), Some(&1));
        assert!(!result.bm25.contains(&2), "Ann Vale shouldn't be a direct BM25 hit for this query");
        assert_eq!(result.hop, vec![1, 2]);
    }

    #[test]
    fn with_no_matching_link_the_hop_falls_back_to_bm25s_second_pick() {
        let (docs, links) = fixture();
        let (index, _) = Index::build(&docs, &links);
        // "Lotus Temple" has no out-links at all, so the hop must fall back.
        let result = index.query("Lotus Temple Delhi building", 2);
        assert_eq!(result.bm25.first(), Some(&3));
        assert_eq!(result.hop, result.bm25);
    }

    #[test]
    fn with_a_link_whose_target_scores_zero_the_hop_still_falls_back() {
        // Lotus (band) links to Ann Vale, but a query with none of Ann Vale's words should not
        // make the hop pick her anyway: a score of 0 doesn't count as "> 0".
        let (docs, links) = fixture();
        let (index, _) = Index::build(&docs, &links);
        let result = index.query("Lotus band", 2);
        assert_eq!(result.bm25.first(), Some(&1));
        assert_ne!(result.hop.get(1), Some(&2));
    }

    #[test]
    fn ties_break_by_the_smaller_doc_index() {
        // Two docs with the exact same single term and the same length tie on score; doc index 0
        // (page id 10) must win over doc index 1 (page id 20).
        let docs = vec![doc(10, "Alpha", "zzyzx"), doc(20, "Beta", "zzyzx")];
        let (index, _) = Index::build(&docs, &[]);
        let result = index.query("zzyzx", 2);
        assert_eq!(result.bm25, vec![10, 20]);
    }

    #[test]
    fn links_to_a_page_id_outside_the_corpus_are_dropped_and_counted() {
        let (docs, mut links) = fixture();
        links.push((1, 999)); // 999 isn't a doc
        links.push((999, 2)); // neither is this source
        let (_, stats) = Index::build(&docs, &links);
        assert_eq!(stats.links_kept, 1);
        assert_eq!(stats.links_dropped, 2);
    }

    #[test]
    fn a_query_with_no_known_terms_gives_empty_fields_not_a_crash() {
        let (docs, links) = fixture();
        let (index, _) = Index::build(&docs, &links);
        let result = index.query("xyzzyplughquux nosuchword", 2);
        assert!(result.bm25.is_empty());
        assert!(result.hop.is_empty());
    }

    #[test]
    fn an_empty_query_gives_empty_fields_not_a_crash() {
        let (docs, links) = fixture();
        let (index, _) = Index::build(&docs, &links);
        let result = index.query("", 2);
        assert!(result.bm25.is_empty());
        assert!(result.hop.is_empty());
    }

    #[test]
    fn a_huge_query_does_not_crash_and_still_scores_known_words() {
        let (docs, links) = fixture();
        let (index, _) = Index::build(&docs, &links);
        let padding = "nosuchword ".repeat(200_000);
        let query = format!("{padding}Lotus band singer");
        let result = index.query(&query, 2);
        assert_eq!(result.bm25.first(), Some(&1));
    }

    #[test]
    fn round_trip_build_serialize_deserialize_query_matches_the_original() {
        let (docs, links) = fixture();
        let (index, _) = Index::build(&docs, &links);
        let bytes = index.to_bytes();
        let reloaded = Index::from_bytes(&bytes).expect("a freshly written index must parse back");
        assert_eq!(reloaded.doc_count(), index.doc_count());
        assert_eq!(reloaded.term_count(), index.term_count());
        assert_eq!(reloaded.postings_count(), index.postings_count());
        assert_eq!(reloaded.edge_count(), index.edge_count());

        let before = index.query("Where did the singer of the band Lotus grow up", 2);
        let after = reloaded.query("Where did the singer of the band Lotus grow up", 2);
        assert_eq!(before.bm25, after.bm25);
        assert_eq!(before.hop, after.hop);
    }

    #[test]
    fn a_truncated_index_file_is_an_error_not_a_panic() {
        let (docs, links) = fixture();
        let (index, _) = Index::build(&docs, &links);
        let bytes = index.to_bytes();
        let truncated = &bytes[..bytes.len() / 2];
        assert!(Index::from_bytes(truncated).is_err());
    }

    /// Each consistency check, by corrupting one field of a real index and writing it out again: all
    /// are refused, including the two that would otherwise give wrong answers without a panic.
    #[test]
    fn a_corrupt_but_well_formed_index_is_refused_for_each_check() {
        let (docs, links) = fixture();
        let fresh = || Index::build(&docs, &links).0;
        assert!(Index::from_bytes(&fresh().to_bytes()).is_ok(), "control: the real index loads");
        type Corrupt = Box<dyn Fn(&mut Index)>;
        let cases: Vec<(&str, Corrupt)> = vec![
            ("tf 0", Box::new(|ix| ix.postings[0].1 = 0)),
            ("posting past the docs", Box::new(|ix| ix.postings[0].0 = ix.doc_count as u32)),
            ("vocabulary unsorted", Box::new(|ix| ix.vocab.swap(0, 1))),
            ("term with no docs", Box::new(|ix| ix.vocab[0].doc_freq = 0)),
            ("postings run past the array", Box::new(|ix| ix.vocab[0].postings_offset = ix.postings.len() as u64)),
            ("link target past the docs", Box::new(|ix| ix.csr_edges[0] = ix.doc_count as u32)),
            ("link offsets decrease", Box::new(|ix| { ix.csr_offsets[1] = 1; ix.csr_offsets[2] = 0; })),
            ("link offsets don't start at 0", Box::new(|ix| ix.csr_offsets[0] = 1)),
            ("average length NaN", Box::new(|ix| ix.avg_doc_len = f64::NAN)),
            ("average length negative", Box::new(|ix| ix.avg_doc_len = -1.0)),
        ];
        for (name, corrupt) in &cases {
            let mut ix = fresh();
            corrupt(&mut ix);
            assert!(Index::from_bytes(&ix.to_bytes()).is_err(), "{name} was accepted");
        }
        let mut trailing = fresh().to_bytes();
        trailing.push(0);
        assert!(Index::from_bytes(&trailing).is_err(), "trailing bytes were accepted");
        // A doc count far past what the file holds is refused before anything is allocated for it.
        let mut huge = fresh().to_bytes();
        huge[8..16].copy_from_slice(&(u32::MAX as u64).to_le_bytes());
        assert!(Index::from_bytes(&huge).is_err());
        huge[8..16].copy_from_slice(&u64::MAX.to_le_bytes());
        assert!(Index::from_bytes(&huge).is_err());
    }

    /// Every byte of a small index set to 0x00, 0xFF and its value + 1: each load is an error or an
    /// index that answers queries, never a panic.
    #[test]
    fn every_single_byte_corruption_is_refused_or_loads_and_queries_without_panic() {
        let (docs, links) = fixture();
        let good = Index::build(&docs, &links).0.to_bytes();
        let (mut loaded, mut refused) = (0, 0);
        for pos in 0..good.len() {
            for v in [0x00u8, 0xFF, good[pos].wrapping_add(1)] {
                if v == good[pos] {
                    continue;
                }
                let mut bad = good.clone();
                bad[pos] = v;
                match Index::from_bytes(&bad) {
                    Ok(ix) => {
                        loaded += 1;
                        let mut scratch = ix.scratch();
                        for q in ["Lotus band singer", "Ann Vale Leeds", "Delhi", "zzz", ""] {
                            let _ = ix.query_with(&mut scratch, q, 2);
                        }
                    }
                    Err(_) => refused += 1,
                }
            }
        }
        assert!(loaded > 0 && refused > 0, "loaded {loaded}, refused {refused}");
    }

    #[test]
    fn an_empty_corpus_builds_but_every_query_is_empty() {
        let (index, stats) = Index::build(&[], &[]);
        assert_eq!(stats.docs, 0);
        let result = index.query("anything", 2);
        assert!(result.bm25.is_empty());
        assert!(result.hop.is_empty());
    }

    /// A unique scratch directory under the OS temp dir, for the tests below that need real
    /// files on disk (`build_from_paths` streams from paths, not slices). Not an RAII guard:
    /// each test removes its own directory when done.
    fn temp_dir(tag: &str) -> std::path::PathBuf {
        use std::sync::atomic::{AtomicU64, Ordering};
        static COUNTER: AtomicU64 = AtomicU64::new(0);
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!("corpus-index-unit-{tag}-{}-{}", std::process::id(), n));
        std::fs::create_dir_all(&dir).expect("creating a scratch temp dir");
        dir
    }

    #[test]
    fn streaming_build_from_paths_matches_the_in_memory_build_byte_for_byte() {
        let (docs, links) = fixture();
        let (in_memory, in_memory_stats) = Index::build(&docs, &links);

        let dir = temp_dir("equivalence");
        let docs_path = dir.join("docs.tsv");
        let links_path = dir.join("links.tsv");
        let mut docs_text = String::new();
        for d in &docs {
            docs_text.push_str(&format!("{}\t{}\t{}\n", d.page_id, d.title, d.text));
        }
        std::fs::write(&docs_path, docs_text).unwrap();
        let mut links_text = String::new();
        for &(src, dst) in &links {
            links_text.push_str(&format!("{src}\t{dst}\n"));
        }
        std::fs::write(&links_path, links_text).unwrap();

        let (streamed, streamed_stats) = Index::build_from_paths(&docs_path, &links_path, 4096)
            .expect("streaming build over a tiny fixture must succeed");

        assert_eq!(streamed_stats.docs, in_memory_stats.docs);
        assert_eq!(streamed_stats.terms, in_memory_stats.terms);
        assert_eq!(streamed_stats.postings, in_memory_stats.postings);
        assert_eq!(streamed_stats.links_kept, in_memory_stats.links_kept);
        assert_eq!(streamed_stats.links_dropped, in_memory_stats.links_dropped);
        assert_eq!(
            in_memory.to_bytes(), streamed.to_bytes(),
            "build_from_paths must produce byte-for-byte the same index.bin as build"
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn streaming_build_handles_a_line_far_larger_than_the_read_buffer() {
        let dir = temp_dir("bigline");
        let docs_path = dir.join("docs.tsv");
        let links_path = dir.join("links.tsv");

        // One doc whose text is tens of thousands of bytes -- far longer than the internal read
        // buffer below -- so `build_from_paths` must cross hundreds of buffer refills mid-line,
        // in both of its passes over this file, without truncating or corrupting it.
        let long_text = "needle ".repeat(5000) + "haystack";
        std::fs::write(&docs_path, format!("1\tBig Doc\t{long_text}\n")).unwrap();
        std::fs::write(&links_path, "").unwrap();

        let (index, stats) = Index::build_from_paths(&docs_path, &links_path, 8)
            .expect("a tiny read buffer must still read the whole long line");
        assert_eq!(stats.docs, 1);
        // "needle" occurs 5000 times and "haystack" once, both inside the single long line; both
        // must be in the vocabulary, which they can only be if the whole line was read.
        let result = index.query("needle haystack", 1);
        assert_eq!(result.bm25, vec![1]);

        let _ = std::fs::remove_dir_all(&dir);
    }
}
