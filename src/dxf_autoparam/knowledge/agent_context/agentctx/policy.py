"""Trust policy: categories, vocabularies and the three separate eligibility answers.

Three purposes are answered separately for every record, and there is deliberately no single "usable" flag:
  retrieval  - may an agent read this as context (with its label)?
  binding    - may this establish a project dimension or measurement target? (needs a human-verified value)
  finetune   - may this enter the fine-tuning pipeline? (the pipeline's own rules: permission, gold/silver, review)

Every eligibility value is a string "eligible:<reason>" or "blocked:<reason>[+<reason>...]".
The reasons are codes, so a pack or an agent can show the exact cause.
"""

from __future__ import annotations

CATEGORY_NAMES: dict[str, str] = {
    "A": "observation_from_drawing_or_source",
    "B": "reference_engineering_knowledge",
    "C": "vocabulary_and_interpretation_aid",
    "D": "proposed_or_disputed",
    "E": "operational_instruction",
}

# Topic -> category for knowledge-base entries (topics come from knowledge/kb/topics.json).
TOPIC_CATEGORY: dict[str, str] = {
    "structure": "C", "component": "C", "space": "C", "feature": "C", "datum": "C",
    "quantity": "C", "context": "C", "material": "C", "relation_type": "C",
    "drawing_language": "C", "abbreviation": "C", "drawing_practice": "C",
    "reinforcement_term": "C", "note_semantics": "C", "place_code": "C",
    "level_chain": "B", "constant": "B", "concept": "B", "family": "B", "formula": "B",
    "rule": "B", "method": "B", "source_doc": "B", "standard_drawing": "B", "clause": "B",
    "load": "B", "hydraulics": "B", "soil_foundation": "B", "inspection_defect": "B",
    "quantities_estimating": "B", "approval_admin": "B",
    "reading_rule": "E", "ambiguity": "E", "sheet_scope": "E",
    "conflict": "D",
}

REVIEWED_STATES = frozenset({"reviewed", "verified"})
HUMAN_LABELS = frozenset({"human_verified", "human_corrected"})

# How a drawing observation is classified (common.schema.json vocabulary).
DRAWING_EPISTEMIC = "REFERENCE_OBSERVED"
DRAWING_LABEL = "vlm"  # the grounding agent read the picture; no person has checked it

ISSUE_SEVERITIES = ("info", "warning", "error")
PURPOSES = ("retrieval", "binding", "finetune")


def knowledge_category(topic: str, review_state: str | None, evidence_status: str | None) -> str | None:
    """Category of a knowledge-base entry. Proposed or disputed knowledge is D, whatever its topic.

    Returns None for a topic the topic registry does not know; the caller reports that as an issue.
    """
    if topic == "conflict" or review_state == "proposed" or evidence_status == "DISPUTED":
        return "D"
    return TOPIC_CATEGORY.get(topic)


def elig(ok: bool, reason: str) -> str:
    return ("eligible:" if ok else "blocked:") + reason


def join_blockers(blockers: list[str]) -> str:
    return "+".join(blockers)


def eligibility(
    *,
    retrieval_ok: bool,
    retrieval_reason: str,
    binding_blockers: list[str],
    finetune_blockers: list[str],
) -> dict[str, str]:
    """Build the three answers. An empty blocker list means eligible for that purpose."""
    binding = (
        "blocked:" + join_blockers(binding_blockers) if binding_blockers else "eligible:human_verified_value_with_unit"
    )
    finetune = (
        "blocked:" + join_blockers(finetune_blockers) if finetune_blockers else "eligible:permitted_and_human_labelled"
    )
    return {
        "retrieval": elig(retrieval_ok, retrieval_reason),
        "binding": binding,
        "finetune": finetune,
    }


def permission_blockers(permission: str | None) -> list[str]:
    """Training permission as recorded in the repository. Only an explicit 'yes' passes."""
    if permission == "yes":
        return []
    return ["permission_" + (permission or "missing")]


def knowledge_retrieval_reason(category: str, review_state: str | None, evidence_status: str | None = None) -> str:
    """Why a knowledge record may be read as context. A NORMATIVE label alone is not verification."""
    reviewed = review_state in REVIEWED_STATES
    if category == "D":
        return "proposed_or_disputed_do_not_present_as_accepted"
    if category == "E":
        return "operational_instruction"
    if category == "C":
        return "reviewed_vocabulary" if reviewed else "unreviewed_vocabulary_interpretation_aid"
    if category == "B":
        if reviewed:
            return "reviewed_reference"
        if evidence_status == "NORMATIVE":
            return "unreviewed_reference_labelled_normative_not_verified"
        return "unreviewed_reference"
    return "observation_unverified"


def knowledge_finetune_blockers(
    *, category: str, review_state: str | None, evidence_status: str | None, qa_training: bool, permitted: bool
) -> list[str]:
    blockers: list[str] = []
    if category == "D":
        blockers.append("proposed_or_disputed")
    if review_state not in REVIEWED_STATES:
        blockers.append("review_state_" + (review_state or "missing"))
    if evidence_status == "DISPUTED":
        blockers.append("evidence_disputed")
    if not qa_training:
        blockers.append("not_marked_for_qa_training")
    if not permitted:
        blockers.append("no_training_permission_record")
    return blockers


BINDING_KNOWLEDGE_BLOCKER = "knowledge_does_not_establish_project_dimensions"
BINDING_NOT_A_VALUE = "not_a_value_observation"
BINDING_NO_HUMAN = "no_human_verification"
