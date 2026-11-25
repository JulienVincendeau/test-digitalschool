"""
Tests for the BigQuery / command-line parts of the pipeline.

BigQuery is replaced by a fake client, so these tests run offline
and never touch the real project.
"""
import pandas as pd
import pytest

from src import contracts, transform

DIRTY = pd.DataFrame(
    [
        ("CA", "F", "1910", "Mary", "295"),
        ("CA", "F", "1910", "Mary", "295"),     # duplicate
        ("ZZ", "F", "1911", "Anna", "120"),     # invalid state
        ("TX", "F", "1912", "Rose", "80"),
    ],
    columns=["state", "gender", "year", "name", "number"],
    dtype="object",
)


@pytest.fixture
def fake_bigquery(monkeypatch):
    """Replace google.cloud.bigquery.Client with an in-memory fake."""
    bigquery = pytest.importorskip("google.cloud.bigquery")
    calls = {"queries": [], "loads": {}}

    class FakeJob:
        def __init__(self, df=None):
            self._df = df

        def to_dataframe(self):
            return self._df.copy()

        def result(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def query(self, sql):
            calls["queries"].append(sql)
            return FakeJob(DIRTY)

        def load_table_from_dataframe(self, df, table, job_config=None):
            calls["loads"][table] = df.copy()
            return FakeJob()

    monkeypatch.setattr(bigquery, "Client", FakeClient)
    return calls


def test_load_from_bigquery_builds_query(fake_bigquery):
    df = contracts.load_from_bigquery("p.d.t", limit=10)
    assert len(df) == len(DIRTY)
    assert fake_bigquery["queries"] == ["SELECT * FROM `p.d.t` LIMIT 10"]


def test_run_contract_fails_on_dirty_data(fake_bigquery, capsys):
    assert contracts.run_contract("p.d.t") is False
    out = capsys.readouterr().out
    assert "=== PROFILE ===" in out
    assert "CONTRACT FAILED" in out


def test_run_contract_passes_on_clean_data(monkeypatch, capsys):
    clean, _ = transform.transform(DIRTY)
    monkeypatch.setattr(contracts, "load_from_bigquery", lambda table: clean)
    assert contracts.run_contract("p.d.t_clean") is True
    assert "CONTRACT PASSED" in capsys.readouterr().out


def test_transform_main_writes_clean_and_dlq(fake_bigquery, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)                       # CSVs go to a temp folder
    transform.main("p.d.t")

    loads = fake_bigquery["loads"]
    assert set(loads) == {"p.d.t_clean", "p.d.t_dlq"}
    assert len(loads["p.d.t_clean"]) == 2             # Mary + Rose
    assert len(loads["p.d.t_dlq"]) == 2               # duplicate + ZZ
    assert (tmp_path / "output" / "clean.csv").exists()
    assert (tmp_path / "output" / "dlq.csv").exists()
    assert "Quarantine reasons" in capsys.readouterr().out


def test_profile_handles_missing_columns(capsys):
    contracts.profile(pd.DataFrame({"other": [1, 2]}))
    assert "rows: 2" in capsys.readouterr().out