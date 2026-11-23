"""Issue #7's smoke test: HotpotQA's answer scoring and the prompt, without a model."""
from experiments.multihop.hotpot_retrieval import Question
from experiments.multihop.hotpot_smoke import exact, f1, normalize, prompt


def test_normalize_follows_hotpotqa():
    assert normalize("The  Beatles!") == "beatles"
    assert normalize("An apple, a day") == "apple day"


def test_exact_and_f1():
    assert exact("the Beatles", "Beatles")
    assert not exact("Beatles band", "Beatles")
    assert f1("Beatles band", "Beatles") == 2 * 0.5 * 1.0 / 1.5
    assert f1("Paris", "London") == 0.0


def test_yes_and_no_score_only_when_equal():
    assert f1("yes", "yes") == 1.0
    assert f1("yes it is", "yes") == 0.0
    assert f1("no", "no answer") == 0.0


def test_the_prompt_carries_only_the_picked_paragraphs():
    q = Question(qid="q", question="Who?", kind="bridge", gold=frozenset(),
                 paragraphs=(("A", "alpha text"), ("B", "beta text"), ("C", "gamma text")))
    assert prompt(q, None) == "Question: Who?"
    text = prompt(q, [2, 0])
    assert "[C] gamma text" in text and "[A] alpha text" in text and "beta" not in text
    assert text.index("[C]") < text.index("[A]")
