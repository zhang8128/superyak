//! The BM25 formula, fixed here once so `build` and `query` can't drift apart.
//!
//! `k1 = 1.2`, `b = 0.75`. `idf(t) = ln(1 + (N - df + 0.5) / (df + 0.5))`, which is always
//! nonnegative for `0 < df <= N` (unlike the classic Robertson/Sparck-Jones form, which can go
//! negative for very common terms). A term's contribution to a document's score is
//! `idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))`.

pub const K1: f64 = 1.2;
pub const B: f64 = 0.75;

/// `ln(1 + (n - df + 0.5) / (df + 0.5))`.
pub fn idf(n: u64, df: u32) -> f64 {
    let n = n as f64;
    let df = df as f64;
    (1.0 + (n - df + 0.5) / (df + 0.5)).ln()
}

/// One query term's contribution to a document's BM25 score, given that term's idf, its term
/// frequency in the document, the document's length (token count) and the corpus's average
/// document length.
pub fn term_contribution(idf_value: f64, tf: u16, doc_len: u32, avg_doc_len: f64) -> f64 {
    let tf = tf as f64;
    if tf <= 0.0 {
        return 0.0;
    }
    let length_norm = if avg_doc_len > 0.0 {
        1.0 - B + B * (doc_len as f64) / avg_doc_len
    } else {
        1.0 - B
    };
    let denom = tf + K1 * length_norm;
    if denom <= 0.0 {
        return 0.0;
    }
    idf_value * (tf * (K1 + 1.0)) / denom
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn idf_is_nonnegative_for_every_valid_df() {
        for df in 1..=10u32 {
            assert!(idf(10, df) >= 0.0, "idf(10, {df}) went negative");
        }
    }

    #[test]
    fn idf_is_zero_only_in_the_limit_and_shrinks_as_df_grows() {
        let rare = idf(1000, 1);
        let common = idf(1000, 500);
        assert!(rare > common);
        assert!(common > 0.0);
    }

    #[test]
    fn a_term_in_every_document_still_has_positive_idf() {
        assert!(idf(5, 5) > 0.0);
    }

    #[test]
    fn higher_term_frequency_gives_a_higher_contribution() {
        let idf_value = idf(100, 10);
        let low = term_contribution(idf_value, 1, 100, 100.0);
        let high = term_contribution(idf_value, 5, 100, 100.0);
        assert!(high > low);
    }

    #[test]
    fn a_longer_document_gets_a_smaller_contribution_for_the_same_tf() {
        let idf_value = idf(100, 10);
        let short = term_contribution(idf_value, 2, 50, 100.0);
        let long = term_contribution(idf_value, 2, 400, 100.0);
        assert!(short > long);
    }

    #[test]
    fn zero_term_frequency_contributes_nothing() {
        let idf_value = idf(100, 10);
        assert_eq!(term_contribution(idf_value, 0, 100, 100.0), 0.0);
    }

    /// Orderings alone (rarer beats common, shorter beats longer) survive many wrong constants,
    /// including k1 or b changed to some other positive value. Pin the exact arithmetic for one
    /// hand-computed case so a changed K1, B, or idf's +0.5 smoothing fails a test, not just a
    /// changed sign or direction.
    #[test]
    fn exact_values_pin_k1_b_and_the_idf_smoothing_constants() {
        // idf(10, 2) = ln(1 + (10 - 2 + 0.5) / (2 + 0.5)) = ln(1 + 8.5/2.5) = ln(4.4)
        let got_idf = idf(10, 2);
        assert!((got_idf - 4.4_f64.ln()).abs() < 1e-12, "idf(10,2) = {got_idf}, expected ln(4.4)");

        // With k1=1.2, b=0.75, tf=3, doc_len=50, avg_doc_len=100:
        //   length_norm = 1 - 0.75 + 0.75*50/100 = 0.625
        //   denom       = 3 + 1.2*0.625          = 3.75
        //   contribution = idf * (3*2.2) / 3.75  = idf * 1.76
        let idf_value = 2.0;
        let got = term_contribution(idf_value, 3, 50, 100.0);
        let expected = idf_value * 1.76;
        assert!((got - expected).abs() < 1e-9, "term_contribution = {got}, expected {expected}");
    }
}
