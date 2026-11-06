"""The firewall decision. A pure function: only this code can approve a payment, never the LLM.

AI review is a dict {"risk_score": 0.0-1.0, "reasons": [str, ...]} or None if the review failed.
(Callers may skip the AI review when a deterministic BLOCK already exists; BLOCK wins first.)
"""
from dataclasses import dataclass

from .checks import BLOCK, HOLD, Finding

AUTO_PAY = "AUTO_PAY"
AI_BLOCK_RISK = 0.7
AI_HOLD_RISK = 0.3


@dataclass
class Decision:
    decision: str  # AUTO_PAY / HOLD / BLOCK
    reason: str
    risk_score: float | None = None


def decide(findings: list[Finding], ai_review: dict | None) -> Decision:
    blocks = [f.message for f in findings if f.severity == BLOCK]
    holds = [f.message for f in findings if f.severity == HOLD]
    risk = ai_review.get("risk_score") if ai_review else None
    ai_reasons = list(ai_review.get("reasons", [])) if ai_review else []

    if blocks:
        return Decision(BLOCK, "; ".join(blocks), risk)
    if risk is not None and risk >= AI_BLOCK_RISK:
        return Decision(BLOCK, "AI review: high risk (" + f"{risk:.2f}" + "): " + "; ".join(ai_reasons), risk)
    if holds:
        return Decision(HOLD, "; ".join(holds), risk)
    if ai_review is None:
        return Decision(HOLD, "AI review unavailable, so a person must approve this payment", None)
    if risk is None or risk >= AI_HOLD_RISK:
        return Decision(HOLD, "AI review: medium risk (" + (f"{risk:.2f}" if risk is not None else "n/a") + "): "
                        + "; ".join(ai_reasons), risk)
    return Decision(AUTO_PAY, "All checks passed and AI review found no risk signals", risk)
