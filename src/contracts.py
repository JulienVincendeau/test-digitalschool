"""
Data contract for the USA names dataset (usa_1910_2013).
Columns: state, gender, year, name, number

Covers the 6 data-quality dimensions:
  1. Completeness   - every column is filled (no nulls / empty strings)
  2. Uniqueness     - one row per (state, gender, year, name)
  3. Validity       - state is a real US code, gender in {F, M}, name only letters
  4. Accuracy       - number >= 5 (the source only publishes names given 5+ times)
  5. Consistency    - formatting is uniform: STATE uppercase, Name capitalised, no spaces
  6. Timeliness     - year within the dataset's coverage 1910-2013, never in the future

Pydantic v2  -> row-level validation (strict, no extra columns)
Pandera      -> table-level validation (uniqueness, column-level checks)

Usage:
    python -m src.contracts sbx-mydigitalschool-2026.usa_names__mar.usa_1910_2013
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Literal

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# ---------- Shared business rules ----------
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
    "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
    "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}
MIN_YEAR, MAX_YEAR = 1910, 2013
MIN_NUMBER, MAX_NUMBER = 5, 100_000
NAME_PATTERN = r"^[A-Z][a-z]+$"          # e.g. "Mary" (no digits, spaces, all-caps)
KEY = ["state", "gender", "year", "name"]
COLUMNS = ["state", "gender", "year", "name", "number"]


class Gender(str, Enum):
    F = "F"
    M = "M"


# =====================================================================
# 1) Pydantic v2 - row-level contract
# =====================================================================
class NameRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    # Completeness: all fields required (no Optional)
    state: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")   # Validity + Consistency
    gender: Literal["F", "M"]                                                # Validity
    year: int = Field(ge=MIN_YEAR, le=MAX_YEAR)                              # Timeliness
    name: str = Field(min_length=2, max_length=15, pattern=NAME_PATTERN)     # Validity + Consistency
    number: int = Field(ge=MIN_NUMBER, le=MAX_NUMBER)                        # Accuracy

    @field_validator("state")
    @classmethod
    def state_exists(cls, v: str) -> str:
        if v not in US_STATES:
            raise ValueError(f"unknown US state code {v!r}")
        return v

    @field_validator("year")
    @classmethod
    def year_not_future(cls, v: int) -> int:
        if v > datetime.now(UTC).year:
            raise ValueError("year is in the future")
        return v


# =====================================================================
# 2) Pandera - table-level contract
# =====================================================================
class NamesSchema(pa.DataFrameModel):
    state: Series[str] = pa.Field(nullable=False, isin=sorted(US_STATES))
    gender: Series[str] = pa.Field(nullable=False, isin=[g.value for g in Gender])
    year: Series[pd.Int64Dtype] = pa.Field(nullable=False, ge=MIN_YEAR, le=MAX_YEAR)
    name: Series[str] = pa.Field(nullable=False, str_matches=NAME_PATTERN,
                                 str_length={"min_value": 2, "max_value": 15})
    number: Series[pd.Int64Dtype] = pa.Field(nullable=False, ge=MIN_NUMBER, le=MAX_NUMBER)

    class Config:
        strict = True      # no unexpected columns
        coerce = True      # cast BigQuery types to the declared dtypes
        unique = KEY       # Uniqueness: one row per state/gender/year/name

    @pa.check("state", "gender", "name", name="consistency_no_surrounding_spaces")
    def no_spaces(cls, s: Series[str]) -> Series[bool]:
        return s == s.str.strip()


# =====================================================================
# 3) Run the contract against a BigQuery table
# =====================================================================
def load_from_bigquery(table: str, limit: int | None = None) -> pd.DataFrame:
    from google.cloud import bigquery

    client = bigquery.Client()
    sql = f"SELECT * FROM `{table}`" + (f" LIMIT {limit}" if limit else "")
    return client.query(sql).to_dataframe()


def _to_python(value):
    """Turn pandas/numpy values into plain Python values (needed for strict mode)."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if hasattr(value, "item"):          # numpy scalar -> python scalar
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)               # 36.0 -> 36 (BigQuery FLOAT/nullable ints)
    return value


def validate_rows_pydantic(df: pd.DataFrame) -> pd.DataFrame:
    """Return one line per row-level violation (row, field, message)."""
    errors = []
    for idx, row in df.iterrows():
        record = {k: _to_python(v) for k, v in row.to_dict().items()}
        try:
            NameRecord.model_validate(record)
        except ValidationError as e:
            for err in e.errors():
                errors.append({"row": idx,
                               "field": ".".join(map(str, err["loc"])) or "__row__",
                               "error": err["msg"]})
    return pd.DataFrame(errors, columns=["row", "field", "error"])


def validate_df_pandera(df: pd.DataFrame) -> pd.DataFrame:
    """Return Pandera failure cases (empty DataFrame if valid)."""
    try:
        NamesSchema.validate(df, lazy=True)   # lazy=True collects ALL errors
        return pd.DataFrame()
    except pa.errors.SchemaErrors as e:
        return e.failure_cases


def profile(df: pd.DataFrame) -> None:
    """Quick profile of the dirty data, one line per dimension."""
    print("\n=== PROFILE ===")
    print(f"rows: {len(df)}   columns: {list(df.columns)}")
    print("\n[Completeness] nulls per column:")
    print(df.isna().sum().to_string())
    present = [c for c in KEY if c in df.columns]
    if present:
        print(f"\n[Uniqueness] duplicated {present}: {df.duplicated(subset=present).sum()}")
    if "state" in df:
        print(f"[Validity] unknown states: {(~df['state'].isin(US_STATES)).sum()}")
    if "gender" in df:
        print(f"[Validity] gender values: {df['gender'].value_counts(dropna=False).to_dict()}")
    if "number" in df:
        n = pd.to_numeric(df["number"], errors="coerce")
        print(f"[Accuracy] number < {MIN_NUMBER}: {(n < MIN_NUMBER).sum()}   "
              f"min={n.min()} max={n.max()}")
    if "name" in df:
        bad = ~df["name"].astype(str).str.match(NAME_PATTERN)
        print(f"[Consistency] badly formatted names: {bad.sum()}")
    if "year" in df:
        y = pd.to_numeric(df["year"], errors="coerce")
        print(f"[Timeliness] year outside {MIN_YEAR}-{MAX_YEAR}: "
              f"{((y < MIN_YEAR) | (y > MAX_YEAR)).sum()}   min={y.min()} max={y.max()}")


def run_contract(table: str = "sbx-mydigitalschool-2026.usa_names__mar.usa_1910_2013") -> bool:
    df = load_from_bigquery(table)
    print(f"Loaded {len(df)} rows from {table}")
    profile(df)

    row_errors = validate_rows_pydantic(df)
    df_errors = validate_df_pandera(df)

    print(f"\n[Pydantic] {len(row_errors)} row-level violations")
    if not row_errors.empty:
        print(row_errors.groupby(["field", "error"]).size()
              .sort_values(ascending=False).to_string())

    print(f"\n[Pandera] {len(df_errors)} failure cases")
    if not df_errors.empty:
        print(df_errors.groupby(["column", "check"], dropna=False).size()
              .sort_values(ascending=False).to_string())

    ok = row_errors.empty and df_errors.empty
    print("\nCONTRACT", "PASSED ✅" if ok else "FAILED ❌")
    return ok


if __name__ == "__main__":
    import sys

    raise SystemExit(0 if run_contract(*sys.argv[1:]) else 1)