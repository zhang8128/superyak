//! Tokenization shared by `build` and `query`.
//!
//! The rule is deliberately simple and must be the same on both sides of the index file, since
//! the index's vocabulary is built from it and a query must land on the same terms: lowercase the
//! whole string, then split it into maximal runs of `char::is_alphanumeric`. No stemming, no
//! stopword removal.

/// Lowercase `text` and split it into maximal runs of alphanumeric characters.
pub fn tokenize(text: &str) -> Vec<String> {
    let lowered = text.to_lowercase();
    let mut tokens = Vec::new();
    let mut current = String::new();
    for ch in lowered.chars() {
        if ch.is_alphanumeric() {
            current.push(ch);
        } else if !current.is_empty() {
            tokens.push(std::mem::take(&mut current));
        }
    }
    if !current.is_empty() {
        tokens.push(current);
    }
    tokens
}

#[cfg(test)]
mod tests {
    use super::tokenize;

    #[test]
    fn splits_on_punctuation_and_whitespace() {
        assert_eq!(tokenize("Ann Vale, singer."), vec!["ann", "vale", "singer"]);
    }

    #[test]
    fn lowercases_everything() {
        assert_eq!(tokenize("BM25 Index"), vec!["bm25", "index"]);
    }

    #[test]
    fn keeps_digits_as_part_of_alphanumeric_runs() {
        assert_eq!(tokenize("enwiki-20261101"), vec!["enwiki", "20261101"]);
    }

    #[test]
    fn handles_accented_unicode_letters_as_one_token() {
        // "café" lowercases to itself (no case change) and the accented "é" is alphabetic,
        // so it must stay fused to "caf" as a single token, not split off.
        assert_eq!(tokenize("Caf\u{00e9} Society"), vec!["caf\u{00e9}", "society"]);
    }

    #[test]
    fn non_ascii_punctuation_and_symbols_split_tokens() {
        // Em dash, curly quotes and a bullet are not alphanumeric.
        assert_eq!(tokenize("multi\u{2014}hop \u{201c}graph\u{201d} \u{2022} bm25"),
                   vec!["multi", "hop", "graph", "bm25"]);
    }

    #[test]
    fn empty_and_whitespace_only_text_has_no_tokens() {
        assert_eq!(tokenize(""), Vec::<String>::new());
        assert_eq!(tokenize("   \t\n  "), Vec::<String>::new());
    }

    #[test]
    fn repeated_whitespace_and_leading_trailing_punctuation_are_ignored() {
        assert_eq!(tokenize("  !!Ann   Vale??  "), vec!["ann", "vale"]);
    }
}
