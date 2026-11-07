import json

from backend.investigation_agent import InvestigationResult, Hypothesis, ResolutionSuggestion


def test_resolution_suggestion_is_structured_and_stays_proposed():
    result = InvestigationResult(
        case_id="case", status="proposed",
        hypotheses=[Hypothesis(statement="date differs", evidence_ids=["src", "led"], confidence=.9)],
        suggestion=ResolutionSuggestion(kind="allocate", source_record_id="src", ledger_id="led", rationale="Exact identity; date variance."),
    )
    assert result.suggestion.kind == "allocate"
    assert result.resolution_proposal_id is None
    assert result.status == "proposed"