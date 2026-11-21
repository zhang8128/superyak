//! The index itself: building it from docs + links, writing/reading the binary format, and
//! answering a BM25 query plus its one-hop pick.
//!
//! Binary layout (all little-endian), written by [`Index::to_bytes`] and read back by
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

    pub fn to_bytes(&self) -> Vec<u8> {
        let mut w = ByteWriter::new();
        w.bytes(&MAGIC);
        w.u32(VERSION);
        w.u64(self.doc_count);
        w.f64(self.avg_doc_len);
        for i in 0..self.doc_count as usize {
            w.u64(self.page_ids[i]);
            w.u32(self.doc_lens[i]);
        }
        w.u64(self.vocab.len() as u64);
        for v in &self.vocab {
            let bytes = v.term.as_bytes();
            w.u32(bytes.len() as u32);
            w.bytes(bytes);
            w.u32(v.doc_freq);
            w.u64(v.postings_offset);
        }
        w.u64(self.postings.len() as u64);
        for &(doc_idx, tf) in &self.postings {
            w.u32(doc_idx);
            w.u16(tf);
        }
        w.u64(self.csr_edges.len() as u64);
        for &off in &self.csr_offsets {
            w.u64(off);
        }
        for &e in &self.csr_edges {
            w.u32(e);
        }
        w.buf
    }

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
        let n = doc_count as usize;
        let mut page_ids = Vec::with_capacity(n);
        let mut doc_lens = Vec::with_capacity(n);
        for _ in 0..n {
            page_ids.push(r.u64()?);
            doc_lens.push(r.u32()?);
        }
        let vocab_count = r.u64()?;
        let mut vocab = Vec::with_capacity(vocab_count as usize);
        for _ in 0..vocab_count {
            let len = r.u32()? as usize;
            let bytes = r.bytes(len)?;
            let term = String::from_utf8(bytes.to_vec()).map_err(|_| "bad utf-8 in index term".to_string())?;
            let doc_freq = r.u32()?;
            let postings_offset = r.u64()?;
            vocab.push(VocabEntry { term, doc_freq, postings_offset });
        }
        let postings_count = r.u64()?;
        let mut postings = Vec::with_capacity(postings_count as usize);
        for _ in 0..postings_count {
            let doc_idx = r.u32()?;
            let tf = r.u16()?;
            postings.push((doc_idx, tf));
        }
        let edge_count = r.u64()?;
        let mut csr_offsets = Vec::with_capacity(n + 1);
        for _ in 0..=n {
            csr_offsets.push(r.u64()?);
        }
        let mut csr_edges = Vec::with_capacity(edge_count as usize);
        for _ in 0..edge_count {
            csr_edges.push(r.u32()?);
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

    /// BM25 scores for every doc that contains at least one of `terms`. A term absent from the
    /// vocabulary is simply skipped (it offers no evidence either way).
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
    fn topk_from_scores(scores: &HashMap<u32, f64>, k: usize) -> Vec<(u32, f64)> {
        let mut v: Vec<(u32, f64)> = scores.iter().map(|(&d, &s)| (d, s)).collect();
        v.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal).then(a.0.cmp(&b.0)));
        v.truncate(k);
        v
    }

    /// One doc's BM25 score against `terms`, computed directly (used for the hop, where the
    /// candidate set is a single document's handful of out-links, not the whole corpus).
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
    pub fn query(&self, query: &str, k: usize) -> QueryResult {
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

#[cfg(test)]
mod tests {
    use super::*;

    fn doc(page_id: u64, title: &str, text: &str) -> DocRecord {
        DocRecord { page_id, title: title.to_string(), text: text.to_string() }
    }

    /// The fixture used across these tests: a tiny "band -> singer" link, plus an unrelated
    /// article and one with no text match at all.
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

    #[test]
    fn an_empty_corpus_builds_but_every_query_is_empty() {
        let (index, stats) = Index::build(&[], &[]);
        assert_eq!(stats.docs, 0);
        let result = index.query("anything", 2);
        assert!(result.bm25.is_empty());
        assert!(result.hop.is_empty());
    }
}
