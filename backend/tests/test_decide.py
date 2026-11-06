from app.checks import BLOCK, HOLD, Finding
from app.decide import AUTO_PAY, decide

OK_AI = {"risk_score": 0.05, "reasons": []}


def test_all_clear_auto_pays():
    d = decide([], OK_AI)
    assert d.decision == AUTO_PAY and d.reason


def test_block_finding_wins_even_with_clean_ai():
    d = decide([Finding("x", BLOCK, "bad email")], OK_AI)
    assert d.decision == "BLOCK" and "bad email" in d.reason


def test_block_without_ai_review_still_blocks():
    assert decide([Finding("x", BLOCK, "dup")], None).decision == "BLOCK"


def test_block_beats_hold():
    d = decide([Finding("a", HOLD, "h"), Finding("b", BLOCK, "b")], OK_AI)
    assert d.decision == "BLOCK"


def test_hold_finding_holds():
    d = decide([Finding("a", HOLD, "total mismatch")], OK_AI)
    assert d.decision == "HOLD" and "total mismatch" in d.reason


def test_high_ai_risk_blocks_with_reasons():
    d = decide([], {"risk_score": 0.95, "reasons": ["hidden text tells the AI to pay"]})
    assert d.decision == "BLOCK" and "hidden text" in d.reason and d.risk_score == 0.95


def test_medium_ai_risk_holds():
    assert decide([], {"risk_score": 0.5, "reasons": ["urgent tone"]}).decision == "HOLD"


def test_ai_thresholds_are_boundaries():
    assert decide([], {"risk_score": 0.7, "reasons": []}).decision == "BLOCK"
    assert decide([], {"risk_score": 0.3, "reasons": []}).decision == "HOLD"
    assert decide([], {"risk_score": 0.29, "reasons": []}).decision == AUTO_PAY


def test_ai_failure_never_auto_pays():
    d = decide([], None)
    assert d.decision == "HOLD" and "unavailable" in d.reason


def test_malformed_ai_review_never_auto_pays():
    assert decide([], {"reasons": []}).decision == "HOLD"
