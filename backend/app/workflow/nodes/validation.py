import re
from collections import Counter

from .contracts import (
    N03SearchPlan,
    N09EvidenceEvaluation,
    N11Adaptability,
    N12Candidates,
)


def validate_n03_plan(plan: N03SearchPlan, budget: int | None = None) -> N03SearchPlan:
    if budget is not None and len(plan.queries) > budget: raise ValueError("query plan exceeds budget")
    kinds = {q.search_type for q in plan.queries}
    if not {"keyword", "auto"}.issubset(kinds): raise ValueError("plan requires keyword and auto queries")
    bad = [q.query for q in plan.queries if re.search(r"(?:site:|\"|\s-\w+)", q.query)]
    if bad: raise ValueError("Google operators are not allowed")
    return plan

def validate_n01_seed(seed: str) -> str:
    if not seed or not seed.strip(): raise ValueError("seed cannot be empty")
    if len(seed) > 2000: raise ValueError("seed exceeds 2000 characters")
    if not re.search(r"[\u4e00-\u9fff]", seed): raise ValueError("seed must contain a Chinese clue")
    return seed.strip()

def validate_n05_selection(selection: dict, source_text: dict[str, str]) -> dict:
    if len(selection.get("selected_ids", [])) != 1: raise ValueError("N05 must select exactly one original meme")
    for quote in selection.get("evidence_quotes", []):
        source_id, text = quote.get("source_id"), quote.get("quote", "")
        if source_id not in source_text or text not in source_text[source_id]: raise ValueError("quote is not present in source")
    return selection

def validate_n09_evidence(evaluation: N09EvidenceEvaluation) -> N09EvidenceEvaluation:
    valid = [x for x in evaluation.items if x.classification == "VALID_VARIANT"]
    # De-duplicate the same wording across sites, as required by N09.
    unique = {x.variant_text.strip() for x in valid}
    urls = {x.url for x in valid}
    anchors = Counter(x.anchor for x in valid if x.anchor)
    evaluation.is_sufficient = bool(len(unique) >= 3 and len(urls) >= 2 and anchors and anchors.most_common(1)[0][1] >= 2)
    return evaluation

def validate_n11_5(value: N11Adaptability) -> N11Adaptability:
    expected = "DIRECT_SLOT_FILL" if value.direct_score >= 4 else "STRUCTURE_PRESERVING_REWRITE" if value.structure_score >= 3 else "ABANDON_ORIGINAL"
    if value.route != expected: raise ValueError("route does not match adaptability thresholds")
    return value

def validate_n12_candidates(value: N12Candidates) -> N12Candidates:
    ids = [c.candidate_id for c in value.candidates]
    if ids != [f"C{i}" for i in range(1, 6)]: raise ValueError("candidate ids must be C1..C5")
    if any("agu" not in c.text or "凿" not in c.text for c in value.candidates): raise ValueError("every candidate must contain agu and 凿")
    return value
