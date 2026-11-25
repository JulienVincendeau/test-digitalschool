"""
Step 2 - Cleaning & DLQ (Dead Letter Queue) for the USA names dataset.

  1. normalize()      -> trim spaces, uniform case, cast text to integers,
                         empty strings -> null
  2. validate()       -> each row is checked against the contract (src/contracts.py);
                         rows that break it go to quarantine WITH the reason
  3. deduplicate()    -> deterministic: rows are sorted on the key (+ number),
                         the first one is kept, the copies go to quarantine
  4. UTC              -> every run gets one UTC timestamp (processed_at_utc),
                         stored on quarantined rows for traceability
                         (the dataset itself has no date/time columns)

Outputs:
  - BigQuery  <table>_clean   valid rows only (same 5 columns as the contract)
  - BigQuery  <table>_dlq     rejected rows: raw values + reason + processed_at_utc
  - CSV copies in ./output/

Usage:
    python -m src.transform sbx-mydigitalschool-2026.usa_names__mar.usa_1910_2013
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd
from pydantic import ValidationError

from src.contracts import COLUMNS, KEY, NameRecord, _to_python

DLQ_COLUMNS = COLUMNS + ["reason", "processed_at_utc"]


# ---------------------------------------------------------------------
# 1) Normalisation
# ---------------------------------------------------------------------
def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    for col in df.columns:
        if df[col].dtype == object or pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].astype("string").str.strip()          # trim
            df[col] = df[col].replace("", pd.NA)                     # "" -> null
    if "state" in df:
        df["state"] = df["state"].str.upper()                        # "ca" -> "CA"
    if "gender" in df:
        df["gender"] = df["gender"].str.upper()                      # "f"  -> "F"
    if "name" in df:
        df["name"] = df["name"].str.capitalize()                     # "MARY" -> "Mary"
    for col in ("year", "number"):                                   # "1910" -> 1910
        if col in df:
            num = pd.to_numeric(df[col], errors="coerce")
            whole = num.notna() & (num % 1 == 0)
            df[col] = num.where(whole).astype("Int64")               # bad text -> null
    return df


# ---------------------------------------------------------------------
# 2) Validation against the contract -> valid / quarantine
# ---------------------------------------------------------------------
def validate(norm: pd.DataFrame, raw: pd.DataFrame, run_ts: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid_idx, dlq_rows = [], []
    for idx, row in norm.iterrows():
        record = {k: _to_python(v) for k, v in row.to_dict().items()}
        try:
            NameRecord.model_validate(record)
            valid_idx.append(idx)
        except ValidationError as e:
            reasons = "; ".join(
                f"{'.'.join(map(str, err['loc'])) or 'row'}: {err['msg']}" for err in e.errors()
            )
            dlq_rows.append({**raw.loc[idx].to_dict(), "reason": reasons, "processed_at_utc": run_ts})
    return norm.loc[valid_idx], pd.DataFrame(dlq_rows, columns=DLQ_COLUMNS)


# ---------------------------------------------------------------------
# 3) Deterministic deduplication
# ---------------------------------------------------------------------
def deduplicate(valid: pd.DataFrame, raw: pd.DataFrame, run_ts: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Same input -> same output: stable sort on the key, highest number first.
    ordered = valid.sort_values(KEY + ["number"], ascending=[True] * len(KEY) + [False], kind="mergesort")
    dup_mask = ordered.duplicated(subset=KEY, keep="first")
    kept = ordered[~dup_mask].reset_index(drop=True)
    dups = raw.loc[ordered[dup_mask].index].copy()
    dups["reason"] = "duplicate: same " + "+".join(KEY) + " as a kept row"
    dups["processed_at_utc"] = run_ts
    return kept[COLUMNS], dups[DLQ_COLUMNS]


# ---------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------
def transform(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")   # UTC
    raw = raw.reset_index(drop=True)
    norm = normalize(raw)
    valid, dlq_invalid = validate(norm, raw, run_ts)
    clean, dlq_dups = deduplicate(valid, raw, run_ts)
    dlq = pd.concat([dlq_invalid, dlq_dups], ignore_index=True)
    assert len(clean) + len(dlq) == len(raw), "no row may be lost"
    return clean, dlq


def write_bigquery(df: pd.DataFrame, table: str) -> None:
    from google.cloud import bigquery

    client = bigquery.Client()
    job = client.load_table_from_dataframe(
        df.astype("string") if table.endswith("_dlq") else df,       # DLQ keeps raw text
        table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    )
    job.result()


def main(source: str) -> None:
    from src.contracts import load_from_bigquery

    raw = load_from_bigquery(source)
    clean, dlq = transform(raw)

    os.makedirs("output", exist_ok=True)
    clean.to_csv("output/clean.csv", index=False)
    dlq.to_csv("output/dlq.csv", index=False)
    write_bigquery(clean, f"{source}_clean")
    write_bigquery(dlq, f"{source}_dlq")

    print(f"Input rows      : {len(raw)}")
    print(f"Valid (clean)   : {len(clean)}  -> {source}_clean")
    print(f"Quarantine (DLQ): {len(dlq)}  -> {source}_dlq")
    if not dlq.empty:
        print("\nQuarantine reasons:")
        print(dlq["reason"].value_counts().to_string())


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else "sbx-mydigitalschool-2026.usa_names__mar.usa_1910_2013")
