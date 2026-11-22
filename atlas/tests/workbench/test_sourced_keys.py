"""North-star test 5's source keys and source comparison, as the approved spec fixes them
(docs/superpowers/specs/2026-11-22-claim-crossing-design.md, revision 6, 84fafe71: "A source's keys")."""
import pytest

from workbench.sourced import compare_sources, how_matched, source_key


def src(url, title="A study of X", year=2024, citation="", source_id="S1"):
    return {"id": source_id, "title": title, "url": url, "year": year, "citation": citation}


# --- the url key: every source has one, since Atlas requires a url

@pytest.mark.parametrize("url, key", [
    ("https://journal.example/a/42", "url:https://journal.example/a/42"),
    ("http://journal.example/a/42", "url:https://journal.example/a/42"),          # http and https fold
    ("https://WWW.Journal.Example/a/42", "url:https://journal.example/a/42"),     # host lowercased, www. removed
    ("https://journal.example:443/a/42", "url:https://journal.example/a/42"),     # default port removed
    ("http://journal.example:80/a/42", "url:https://journal.example/a/42"),
    ("https://journal.example/a/42/", "url:https://journal.example/a/42"),        # one trailing slash removed
    ("https://journal.example/a/42#results", "url:https://journal.example/a/42"),  # fragment removed
    ("https://journal.example/a/42?id=7&ref=x", "url:https://journal.example/a/42?id=7&ref=x"),  # query kept as it is
    ("https://journal.example:8443/a", "url:https://journal.example:8443/a"),     # another port kept
    ("https://journal.example/A/Path", "url:https://journal.example/A/Path"),     # the path keeps its case
])
def test_the_url_key(url, key):
    assert source_key(src(url))["url"] == key


# --- the DOI key from a doi.org url: the whole decoded path, never the regex

@pytest.mark.parametrize("url, doi", [
    ("https://doi.org/10.5555/superyak-fixture-a1", "doi:10.5555/superyak-fixture-a1"),
    ("http://dx.doi.org/10.5555/SUPERYAK-FIXTURE-A1", "doi:10.5555/superyak-fixture-a1"),
    ("https://www.doi.org/10.5555/superyak-fixture-a1", "doi:10.5555/superyak-fixture-a1"),
    ("https://doi.org/10.5555/superyak-fixture-a1/", "doi:10.5555/superyak-fixture-a1"),       # one trailing / removed
    ("https://doi.org/doi:10.5555/superyak-fixture-a1", "doi:10.5555/superyak-fixture-a1"),    # a doi: prefix removed
    ("https://doi.org/10.5555/superyak-fixture-a1?via=x#top", "doi:10.5555/superyak-fixture-a1"),  # query, fragment out
    # %3C and %3E decode to < and >, and stay in the DOI (C5): two SICI articles of one issue key apart
    ("https://doi.org/10.1002/(SICI)1097-4571(199806)49:8%3C693::AID-ASI4%3E3.0.CO;2-0",
     "doi:10.1002/(sici)1097-4571(199806)49:8<693::aid-asi4>3.0.co;2-0"),
    ("https://doi.org/10.1002/(SICI)1097-4571(199806)49:8%3C701::AID-ASI5%3E3.0.CO;2-X",
     "doi:10.1002/(sici)1097-4571(199806)49:8<701::aid-asi5>3.0.co;2-x"),
])
def test_the_doi_key_from_a_doi_org_url(url, doi):
    assert source_key(src(url))["doi"] == doi


@pytest.mark.parametrize("url", ["https://doi.org/", "https://doi.org/help", "https://doi.org/10.5555",
                                 "https://doi.org/10.x/abc", "https://doi.org/11.5555/x"])
def test_a_doi_org_path_that_is_not_a_doi_gives_no_doi_key(url):
    key = source_key(src(url))
    assert key["doi"] is None
    assert key["url"].startswith("url:https://doi.org")  # it keeps its url key; a path makes it strong, the bare root
    # is weak (amendment 3, test_a_root_only_url_is_weak below)


# --- the DOI key from the citation, only when the url gave none

@pytest.mark.parametrize("citation, doi", [
    ("Vale A. (2024). A study of X. doi:10.5555/superyak-fixture-a1", "doi:10.5555/superyak-fixture-a1"),
    ("doi: 10.5555/superyak-fixture-a1.", "doi:10.5555/superyak-fixture-a1"),        # trailing full stop
    ("(see doi:10.5555/superyak-fixture-a1.)", "doi:10.5555/superyak-fixture-a1"),     # stripped repeatedly: .) both go
    ("Available at <https://doi.org/10.5555/superyak-fixture-a1>.", "doi:10.5555/superyak-fixture-a1"),  # E1
    ("DOI 10.5555/SUPERYAK-FIXTURE-A1;", "doi:10.5555/superyak-fixture-a1"),
    ("doi:10.5555/superyak%2Dfixture%2Da1", "doi:10.5555/superyak-fixture-a1"),        # percent-decoded first
    # < and > are in the class, so a SICI DOI in a citation is kept whole (D3), and a wrapped one sheds only the
    # unpartnered > of its wrapper (G3)
    ("doi:10.1002/(SICI)1097-4571(199806)49:8<693::AID-ASI4>3.0.CO;2-0",
     "doi:10.1002/(sici)1097-4571(199806)49:8<693::aid-asi4>3.0.co;2-0"),
    ("<doi:10.1002/(SICI)1097-4571(199806)49:8<693::AID-ASI4>3.0.CO;2-0>",
     "doi:10.1002/(sici)1097-4571(199806)49:8<693::aid-asi4>3.0.co;2-0"),
    ("10.5555/superyak-fixture-(a1)", "doi:10.5555/superyak-fixture-(a1)"),  # a partnered ) is part of the DOI
])
def test_the_doi_key_from_the_citation(citation, doi):
    assert source_key(src("https://journal.example/a/42", citation=citation))["doi"] == doi


def test_a_citation_with_two_distinct_dois_gives_none():
    record = src("https://journal.example/a/42", citation="doi:10.5555/superyak-fixture-a1, retracted by 10.5555/superyak-fixture-r1")
    assert source_key(record)["doi"] is None


def test_the_same_doi_twice_in_a_citation_is_one_doi():
    record = src("https://journal.example/a/42", citation="doi:10.5555/superyak-fixture-a1 (https://doi.org/10.5555/superyak-fixture-a1)")
    assert source_key(record)["doi"] == "doi:10.5555/superyak-fixture-a1"


def test_the_url_s_doi_wins_and_the_citation_is_not_read():
    record = src("https://doi.org/10.5555/superyak-fixture-a1", citation="doi:10.5555/superyak-fixture-zz")
    assert source_key(record)["doi"] == "doi:10.5555/superyak-fixture-a1"


def test_a_citation_doi_keeps_the_url_key_beside_it():
    key = source_key(src("https://journal.example/a/42", citation="doi:10.5555/superyak-fixture-a1"))
    assert key["url"] == "url:https://journal.example/a/42" and key["doi"] == "doi:10.5555/superyak-fixture-a1"


# --- the title key: weak, for every source; none when the title is all punctuation

def test_the_title_key():
    assert source_key(src("https://journal.example/a", title="A Study of X: Part 1!", year=2024))["title"] == \
        "title:a study of x part 1:2024"
    assert source_key(src("https://journal.example/a", title="self-supervised", year=2020))["title"] == \
        "title:self supervised:2020"  # punctuation becomes a space, as store._normalized_title does
    assert source_key(src("https://journal.example/a", title="—?!", year=2024))["title"] is None


def test_the_key_names_its_function():
    assert source_key(src("https://journal.example/a"))["fn"] == "source_key/1"


# --- comparing two sources: five rules in order, the first that holds wins

URL_A, URL_B = "https://journal.example/a/42", "https://other.example/b/7"
DOI_1, DOI_2 = "https://doi.org/10.5555/superyak-fixture-p1", "https://doi.org/10.5555/superyak-fixture-p2"


def compare(a, b):
    result = compare_sources(source_key(a), source_key(b))
    assert compare_sources(source_key(b), source_key(a)) == result  # it is symmetric
    return result


def test_rule_1_distinct_by_doi_even_when_they_share_a_url():
    shared = "https://proc.example/vol12.pdf"
    a = src(shared, title="Paper one", citation="doi:10.5555/superyak-fixture-p1")
    b = src(shared, title="Paper two", citation="doi:10.5555/superyak-fixture-p2")
    assert compare(a, b) == "distinct"


def test_rule_2_unclear_two_dois_one_title_even_in_different_years():
    assert compare(src(DOI_1, title="A study of X", year=2023), src(DOI_2, title="A study of X", year=2024)) == "unclear"
    assert compare(src(DOI_1, title="Editorial"), src(DOI_2, title="Editorial")) == "unclear"


def test_rule_3_match_by_any_shared_strong_key():
    assert compare(src(URL_A, title="One"), src(URL_A, title="Two")) == "match"
    assert compare(src("http://www.journal.example/a/42/"), src(URL_A)) == "match"
    # a shared url, only one side with a DOI (C6): rules 1 and 2 don't apply, and the url matches
    assert compare(src(URL_A, title="A study of X: the sequel", citation="doi:10.5555/superyak-fixture-a1"),
                   src(URL_A, title="A study of X")) == "match"
    # one DOI in url form on one side and citation form on the other
    assert compare(src(DOI_1), src(URL_A, citation="doi:10.5555/superyak-fixture-p1")) == "match"


def test_rule_3_match_by_title_and_year_across_key_forms():
    # a publisher url against a DOI, one title and year: the same paper, never independent
    assert compare(src(URL_A, title="A study of X", year=2024), src(DOI_1, title="A study of X", year=2024)) == "match"


def test_rule_4_unclear_by_year():
    # a preprint kept by its arXiv url and its journal version under a DOI, a year apart (G1)
    assert compare(src("https://arxiv.org/abs/2301.00001", title="A study of X", year=2023),
                   src(DOI_1, title="A study of X", year=2024)) == "unclear"


def test_rule_5_distinct():
    assert compare(src(URL_A, title="One"), src(URL_B, title="Two")) == "distinct"
    assert compare(src(DOI_1, title="One"), src(URL_B, title="Two")) == "distinct"


def test_two_revisions_of_one_page_have_two_url_keys_and_match():
    # North-star test 1 keeps each Wikipedia revision as its own Atlas source (Serenity, all hands a4f32bf7). Their url
    # keys stay apart, since the query is kept, and they are one identity, by title: a retraction reaches every
    # revision, and a correction names one by Snapshot and record id.
    one = src("https://en.wikipedia.org/?curid=123&oldid=1001", title="Ann Vale", year=2026, source_id="w-1001")
    two = src("https://en.wikipedia.org/?curid=123&oldid=1002", title="Ann Vale", year=2026, source_id="w-1002")
    assert source_key(one)["url"] != source_key(two)["url"]
    assert compare(one, two) == "match"


def test_a_missing_title_key_never_matches():
    assert compare(src(URL_A, title="—?!"), src(URL_B, title="—?!")) == "distinct"
    assert compare(src(DOI_1, title="—?!"), src(DOI_2, title="—?!")) == "distinct"  # rule 1, not rule 2


# --- amendment 3: a url key with neither a path nor a query names a site, not a work, so it is weak

ROOTS = ["https://journal.example", "https://journal.example/", "https://journal.example/#top",
         "https://journal.example:8443/", "http://www.journal.example:80/", "https://doi.org/"]


@pytest.mark.parametrize("root", ROOTS)
def test_a_root_only_url_is_weak(root):
    # two different works cited only by one site's root don't match by it ...
    assert compare(src(root, title="One"), src(root, title="Two")) == "distinct"
    # ... while their title and year still can, and rule 4 still sees a year apart
    assert compare(src(root, title="One"), src(root, title="One")) == "match"
    assert compare(src(root, title="One", year=2023), src(root, title="One", year=2024)) == "unclear"
    assert source_key(src(root))["url"] is not None  # it keeps its url key, for display and for a notice's report


def test_a_root_url_with_a_query_names_one_page_and_stays_strong():
    page = "https://en.wikipedia.org/?curid=123"
    assert compare(src(page, title="One"), src(page, title="Two")) == "match"


def test_known_limit_a_root_with_only_a_tracking_query_stays_strong():
    # recorded in amendment 3 as a limit, not a rule: change it only when a real crossing shows it
    tracked = "https://journal.example/?utm_source=feed"
    assert compare(src(tracked, title="One"), src(tracked, title="Two")) == "match"


def test_a_match_by_a_shared_root_url_is_named_by_title():
    a, b = source_key(src("https://journal.example/", title="One")), source_key(src("https://journal.example", title="One"))
    assert compare_sources(a, b) == "match" and how_matched(a, b) == "title"
    a, b = source_key(src(URL_A, title="One")), source_key(src(URL_A, title="Two"))
    assert how_matched(a, b) == "url"
    a, b = source_key(src(DOI_1, title="One")), source_key(src(URL_A, title="Two", citation="doi:10.5555/superyak-fixture-p1"))
    assert how_matched(a, b) == "doi"
