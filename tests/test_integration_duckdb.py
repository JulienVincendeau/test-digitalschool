"""
SQL integration test with DuckDB (in-memory, no BigQuery needed).

A dirty table is loaded into DuckDB with every column as VARCHAR (like BigQuery).
The Python pipeline cleans it, then SQL queries check the result end to end.
"""
import pandas as pd
import pytest

from src.transform import transform

duckdb = pytest.importorskip("duckdb")

DIRTY = pd.DataFrame(
    [
        ("CA", "F", "1910", "Mary", "295"),
        ("CA", "F", "1910", "Mary", "295"),     # exact duplicate
        (" ca", "f", "1910", "MARY ", "295"),   # duplicate after normalisation
        ("TX", "F", "1911", "Anna", "120"),
        ("NY", "F", "1912", "Rose", "80"),
        ("ZZ", "F", "1912", "Rose", "80"),      # invalid state
        ("NY", "F", "abc", "Helen", "60"),      # year is not a number
        ("NY", "F", "1913", "Ruth", "3"),       # number < 5
        ("NY", "F", "1913", "", "40"),          # empty name
    ],
    columns=["state", "gender", "year", "name", "number"],
)


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    con.register("dirty_df", DIRTY)
    con.execute("CREATE TABLE raw AS SELECT * FROM dirty_df")
    raw = con.execute("SELECT * FROM raw").df()
    clean, dlq = transform(raw)
    con.register("clean", clean)
    con.register("dlq", dlq)
    yield con
    con.close()


def test_sql_end_to_end(con):
    sql = lambda q: con.execute(q).fetchone()[0]

    # No row lost: raw = clean + quarantine
    assert sql("SELECT COUNT(*) FROM raw") == sql("SELECT COUNT(*) FROM clean") + sql("SELECT COUNT(*) FROM dlq")

    # Expected split: 3 valid rows (Mary, Anna, Rose NY), 6 quarantined
    assert sql("SELECT COUNT(*) FROM clean") == 3
    assert sql("SELECT COUNT(*) FROM dlq WHERE reason LIKE 'duplicate%'") == 2

    # Uniqueness
    assert sql("""SELECT COUNT(*) FROM (
                    SELECT state, gender, year, name FROM clean
                    GROUP BY ALL HAVING COUNT(*) > 1)""") == 0

    # Validity: year / number are real integers in SQL
    assert sql("SELECT typeof(year) FROM clean LIMIT 1") in ("BIGINT", "INTEGER")
    assert sql("SELECT typeof(number) FROM clean LIMIT 1") in ("BIGINT", "INTEGER")

    # Accuracy, timeliness, consistency
    assert sql("SELECT COUNT(*) FROM clean WHERE number < 5") == 0
    assert sql("SELECT COUNT(*) FROM clean WHERE year NOT BETWEEN 1910 AND 2013") == 0
    assert sql("SELECT COUNT(*) FROM clean WHERE state <> UPPER(TRIM(state)) "
               "OR name <> TRIM(name)") == 0

    # Every quarantined row has a reason and a UTC timestamp
    assert sql("SELECT COUNT(*) FROM dlq WHERE reason IS NULL OR processed_at_utc IS NULL") == 0

    # Cross-check: Python dedup gives the same result as a pure SQL dedup
    sql_dedup = sql("""SELECT COUNT(*) FROM (
                         SELECT DISTINCT UPPER(TRIM(state)), UPPER(TRIM(gender)),
                                TRY_CAST(year AS INT), LOWER(TRIM(name))
                         FROM raw
                         WHERE TRY_CAST(year AS INT) IS NOT NULL
                           AND UPPER(TRIM(state)) <> 'ZZ'
                           AND TRY_CAST(number AS INT) >= 5
                           AND TRIM(name) <> '')""")
    assert sql_dedup == sql("SELECT COUNT(*) FROM clean")