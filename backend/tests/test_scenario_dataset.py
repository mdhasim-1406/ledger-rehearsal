"""Structural and conservatism checks for the independent reconciliation corpus.

These tests validate fixture semantics/shape only; they do not execute the
reconciliation domain or claim that any matcher produces these outcomes.
"""
import json
from pathlib import Path


DATASET = Path(__file__).with_name("fixtures") / "reconciliation_scenarios.json"
ALLOWED_OUTCOMES = {"match", "review", "no_match", "insufficient_data"}
REQUIRED_FIELDS = {"id", "category", "description", "statement", "ledger", "expected"}


def load_scenarios():
    return json.loads(DATASET.read_text(encoding="utf-8"))


def test_dataset_is_independent_well_formed_and_large_enough():
    dataset = load_scenarios()
    assert dataset["schema_version"] == 1
    assert "domain_execution_claim" in dataset
    assert dataset["domain_execution_claim"] is False
    scenarios = dataset["scenarios"]
    assert len(scenarios) >= 50
    ids = [scenario["id"] for scenario in scenarios]
    assert len(ids) == len(set(ids))
    for scenario in scenarios:
        assert REQUIRED_FIELDS <= scenario.keys()
        assert scenario["expected"]["outcome"] in ALLOWED_OUTCOMES
        assert scenario["expected"].get("rationale", "").strip()
        assert isinstance(scenario["statement"], list)
        assert isinstance(scenario["ledger"], list)
        assert scenario["statement"] or scenario["ledger"]


def test_fixture_scenarios_execute_without_hiding_errors(tmp_path):
    """Exercise representable inputs; validate conservative identity invariants.

    This is safety coverage, not proof of all corpus business outcomes.
    """
    from decimal import Decimal
    import sqlite3
    from backend.domain_foundation import initialize, ReconciliationDomain
    for scenario in load_scenarios()["scenarios"]:
        dbpath = tmp_path / (scenario["id"] + ".sqlite")
        initialize(dbpath)
        domain = ReconciliationDomain(dbpath)
        def convert(row, identity):
            value = row.get("amount")
            if value is None or not row.get("currency") or not row.get("date"):
                return None
            cents = Decimal(str(value)) * 100
            if cents != cents.to_integral_value():
                return None
            return {"source_id": identity, "transaction_id": str(row.get("reference") or ""),
                    "date": row["date"], "description": identity,
                    "amount_cents": int(cents), "currency": row["currency"]}
        for i, row in enumerate(scenario["ledger"]):
            record = convert(row, f"L{i}")
            if record is not None:
                domain.add_ledger_record("test", record["source_id"], record["date"], record["description"], record["amount_cents"], record["currency"], record["transaction_id"])
        records = [convert(row, f"S{i}") for i,row in enumerate(scenario["statement"])]
        records = [row for row in records if row is not None]
        if records:
            import re
            invalid_currency = any(not re.fullmatch(r'[A-Z]{3}', row['currency']) for row in records)
            if invalid_currency:
                import pytest
                with pytest.raises(ValueError, match='currency'):
                    domain.ingest('test', 'corpus', '1', records)
                continue
            domain.ingest("test", "corpus", "1", records)
        domain.reconcile("test")
        with sqlite3.connect(dbpath) as db:
            invalid = db.execute("""SELECT count(*) FROM lr_matches m
                JOIN lr_source_records s ON s.id=m.source_record_id
                JOIN lr_ledger_records l ON l.id=m.ledger_record_id
                WHERE m.status='active' AND (s.transaction_id='' OR
                    s.transaction_id!=l.transaction_id OR s.currency!=l.currency OR
                    s.amount_cents!=l.amount_cents OR s.transaction_date!=l.transaction_date)""").fetchone()[0]
            assert invalid == 0, scenario["id"]


def test_ambiguity_and_stale_evidence_are_never_forced_into_match():
    scenarios = load_scenarios()["scenarios"]
    guarded = [s for s in scenarios if s["category"] in {"ambiguity", "stale"}]
    assert guarded
    assert all(s["expected"]["outcome"] in {"review", "no_match", "insufficient_data"} for s in guarded)


def test_risky_or_incomplete_cases_have_explicit_conservative_outcomes():
    scenarios = load_scenarios()["scenarios"]
    categories = {s["category"] for s in scenarios}
    assert {"exact", "duplicates", "partial", "one_many", "dates", "fees", "reversals", "currency", "missing_ids", "ambiguity", "stale"} <= categories
    assert all(s["expected"]["outcome"] != "match" for s in scenarios if s["category"] in {"ambiguity", "stale", "currency", "missing_ids"})
