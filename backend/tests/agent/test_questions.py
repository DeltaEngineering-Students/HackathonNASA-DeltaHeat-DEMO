from pathlib import Path

from uhd.agent import evalrun

Q = Path(__file__).with_name("questions.yaml")


def test_questions_file_is_consistent():
    qs = evalrun.load(str(Q))
    assert 15 <= len(qs) <= 25
    assert len({q["id"] for q in qs}) == len(qs)
    for q in qs:
        assert q["question"].strip()
        assert q.get("expect_tools") or q.get("any_of") or q.get("forbid_tools"), q["id"]
