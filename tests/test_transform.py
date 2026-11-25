"""
Unit tests - one test (at least) per anomaly found in the diagnostic (Step 1)
plus the guarantees of the cleaning step (Step 2).

Run from the project root:   python -m pytest -v
"""
import pandas as pd
import pytest
from pydantic import ValidationError

from src.contracts import KEY, NameRecord, NamesSchema
from src.transform import normalize, transform

GOOD = {"state": "CA", "gender": "F", "year": "1910", "name": "Mary", "number": "295"}


def make_raw(*rows: dict) -> pd.DataFrame:
    """Build a raw DataFrame like BigQuery returns it (every column is STRING)."""
    return pd.DataFrame([{**GOOD, **r} for r in rows], dtype="object")


# ---------------------------------------------------------------------
# Validity - year / number stored as STRING in BigQuery
# ---------------------------------------------------------------------
def test_text_numbers_are_cast_to_integers():
    norm = normalize(make_raw({"year": "1910", "number": "295"}))
    assert norm.loc[0, "year"] == 1910
    assert norm.loc[0, "number"] == 295
    assert str(norm["year"].dtype) == "Int64"


def test_non_numeric_year_goes_to_quarantine():
    clean, dlq = transform(make_raw({"year": "abc"}))
    assert clean.empty
    assert len(dlq) == 1
    assert "year" in dlq.loc[0, "reason"]
    assert dlq.loc[0, "year"] == "abc"          # DLQ keeps the raw value


# ---------------------------------------------------------------------
# Uniqueness - duplicated rows
# ---------------------------------------------------------------------
def test_duplicates_are_removed_and_quarantined():
    clean, dlq = transform(make_raw({}, {}, {}))          # 3 identical rows
    assert len(clean) == 1
    assert len(dlq) == 2
    assert dlq["reason"].str.startswith("duplicate").all()


def test_deduplication_is_deterministic():
    raw = make_raw({"number": "100"}, {"number": "300"}, {"number": "200"},
                   {"name": "Anna"}, {"state": "TX"})
    first, _ = transform(raw)
    for seed in range(5):                                  # shuffled input
        again, _ = transform(raw.sample(frac=1, random_state=seed))
        pd.testing.assert_frame_equal(first, again)
    kept = first[(first["name"] == "Mary") & (first["state"] == "CA")]
    assert kept["number"].tolist() == [300]                # highest number kept


# ---------------------------------------------------------------------
# Consistency - spaces and case
# ---------------------------------------------------------------------
def test_trim_and_case_are_normalized():
    clean, dlq = transform(make_raw({"state": " ca ", "gender": "f", "name": "  MARY "}))
    assert dlq.empty
    assert clean.loc[0, ["state", "gender", "name"]].tolist() == ["CA", "F", "Mary"]


def test_same_row_with_different_formatting_is_a_duplicate():
    clean, dlq = transform(make_raw({}, {"state": "ca", "name": "MARY "}))
    assert len(clean) == 1 and len(dlq) == 1


# ---------------------------------------------------------------------
# Completeness - missing values
# ---------------------------------------------------------------------
@pytest.mark.parametrize("column", ["state", "gender", "year", "name", "number"])
def test_empty_or_missing_values_go_to_quarantine(column):
    for missing in ("", "   ", None):
        clean, dlq = transform(make_raw({column: missing}))
        assert clean.empty, f"{column}={missing!r} should be rejected"
        assert column in dlq.loc[0, "reason"]


# ---------------------------------------------------------------------
# Validity / Accuracy / Timeliness - business rules of the contract
# ---------------------------------------------------------------------
@pytest.mark.parametrize("field, bad_value", [
    ("state", "ZZ"),        # Validity: not a US state
    ("gender", "X"),        # Validity: only F / M
    ("name", "M4ry"),       # Validity: letters only
    ("number", "2"),        # Accuracy: the source only publishes names given 5+ times
    ("number", "-10"),      # Accuracy: negative count
    ("year", "1850"),       # Timeliness: before 1910
    ("year", "2099"),       # Timeliness: after 2013 / in the future
])
def test_business_rules_are_enforced(field, bad_value):
    clean, dlq = transform(make_raw({field: bad_value}))
    assert clean.empty
    assert field in dlq.loc[0, "reason"]


def test_contract_forbids_extra_columns():
    with pytest.raises(ValidationError):
        NameRecord.model_validate({"state": "CA", "gender": "F", "year": 1910,
                                   "name": "Mary", "number": 295, "extra": "x"})


# ---------------------------------------------------------------------
# Pipeline guarantees
# ---------------------------------------------------------------------
def test_no_row_is_lost_and_dlq_is_traceable():
    raw = make_raw({}, {}, {"state": "ZZ"}, {"year": "abc"}, {"name": "Anna"})
    clean, dlq = transform(raw)
    assert len(clean) + len(dlq) == len(raw)
    assert dlq["reason"].notna().all()
    assert dlq["processed_at_utc"].str.endswith("Z").all()   # UTC timestamp


def test_clean_output_passes_the_pandera_contract():
    raw = make_raw({}, {}, {"state": " ny", "name": "ROSE"}, {"year": "1915", "number": "40"})
    clean, _ = transform(raw)
    NamesSchema.validate(clean, lazy=True)                   # raises if invalid
    assert not clean.duplicated(subset=KEY).any()