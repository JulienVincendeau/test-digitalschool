"""Suite de tests pytest pour le TP DataOps Jour 2.

Couvre :
- 7 tests unitaires (normalisation + les 6 familles d'anomalies qualité)
- 1 test d'intégration SQL en mémoire avec DuckDB sur le fichier data/weather_dirty.json
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from src.transform import split_valid_and_quarantine

# ---------------------------------------------------------------------------
# 1. TESTS UNITAIRES (rapides, isolés, zéro accès réseau)
# ---------------------------------------------------------------------------


def test_cas_nominal_et_normalisation():
    """Une ligne valide est nettoyée (trim, majuscules) et convertie en UTC."""
    lot = [
        {
            "station_id": "  fr-0075  ",
            "observed_at": "2027-03-10T12:00:00+02:00",  # = 10:00:00 UTC
            "temperature_c": 18.4,
            "humidity_pct": 62.0,
        }
    ]

    valides, quarantaine = split_valid_and_quarantine(lot)

    assert len(valides) == 1
    assert len(quarantaine) == 0
    assert valides[0]["station_id"] == "FR-0075"
    assert valides[0]["observed_at"] == "2027-03-10T10:00:00Z"


def test_anomalie_completude_champ_manquant():
    """Un champ obligatoire à None (ou absent) est envoyé en quarantaine."""
    lot = [
        {
            "station_id": "FR-0031",
            "observed_at": "2027-03-10T10:00:00Z",
            "temperature_c": 20.0,
            "humidity_pct": None,
        }
    ]

    valides, quarantaine = split_valid_and_quarantine(lot)

    assert len(valides) == 0
    assert len(quarantaine) == 1


def test_anomalie_validite_type_casse():
    """Une température non numérique ('chaud') est rejetée en quarantaine."""
    lot = [
        {
            "station_id": "FR-0013",
            "observed_at": "2027-03-10T10:00:00Z",
            "temperature_c": "chaud",
            "humidity_pct": 50.0,
        }
    ]

    valides, quarantaine = split_valid_and_quarantine(lot)

    assert len(valides) == 0
    assert len(quarantaine) == 1


def test_anomalie_validite_format_station_et_colonne_inconnue():
    """Un station_id hors format FR-XXXX ou une colonne surprise sont rejetés."""
    lot = [
        {
            "station_id": "PARIS",
            "observed_at": "2027-03-10T10:00:00Z",
            "temperature_c": 19.0,
            "humidity_pct": 60.0,
        },
        {
            "station_id": "FR-0075",
            "observed_at": "2027-03-10T10:00:00Z",
            "temperature_c": 19.0,
            "humidity_pct": 60.0,
            "colonne_surprise": "interdit",
        },
    ]

    valides, quarantaine = split_valid_and_quarantine(lot)

    assert len(valides) == 0
    assert len(quarantaine) == 2


def test_anomalie_date_sans_timezone():
    """Une date sans fuseau horaire (ex: sans 'Z' ni '+02:00') est rejetée."""
    lot = [
        {
            "station_id": "FR-0044",
            "observed_at": "2027-03-10T10:00:00",
            "temperature_c": 14.5,
            "humidity_pct": 80.0,
        }
    ]

    valides, quarantaine = split_valid_and_quarantine(lot)

    assert len(valides) == 0
    assert len(quarantaine) == 1
    assert "Timezone obligatoire" in quarantaine[0]["reason"]


def test_anomalie_exactitude_valeur_aberrante():
    """Une valeur hors bornes physiques (+999 °C) part en quarantaine."""
    lot = [
        {
            "station_id": "FR-0059",
            "observed_at": "2027-03-10T10:00:00Z",
            "temperature_c": 999.0,
            "humidity_pct": 50.0,
        }
    ]

    valides, quarantaine = split_valid_and_quarantine(lot)

    assert len(valides) == 0
    assert len(quarantaine) == 1


def test_anomalie_unicite_doublon():
    """La première mesure est gardée ; un doublon (même après conversion UTC) est rejeté."""
    lot = [
        {
            "station_id": "FR-0075",
            "observed_at": "2027-03-10T10:00:00Z",
            "temperature_c": 18.4,
            "humidity_pct": 62.0,
        },
        {
            # Même station et même instant exprimé en +02:00 -> doublon logique !
            "station_id": "fr-0075",
            "observed_at": "2027-03-10T12:00:00+02:00",
            "temperature_c": 18.4,
            "humidity_pct": 62.0,
        },
    ]

    valides, quarantaine = split_valid_and_quarantine(lot)

    assert len(valides) == 1
    assert len(quarantaine) == 1
    assert quarantaine[0]["reason"] == "DUPLICATE_EVENT"


def test_anomalie_fraicheur_trop_ancienne_ou_future():
    """Les mesures trop anciennes (> 24h) ou dans le futur sont rejetées."""
    ref = datetime(2027, 3, 10, 12, 0, tzinfo=UTC)
    lot = [
        {
            # Trop ancienne (année 2020)
            "station_id": "FR-0006",
            "observed_at": "2020-01-01T10:00:00Z",
            "temperature_c": 12.0,
            "humidity_pct": 65.0,
        },
        {
            # Dans le futur par rapport à reference_time
            "station_id": "FR-0006",
            "observed_at": "2027-03-10T15:00:00Z",
            "temperature_c": 16.0,
            "humidity_pct": 55.0,
        },
    ]

    valides, quarantaine = split_valid_and_quarantine(lot, reference_time=ref, max_age_hours=24)

    assert len(valides) == 0
    assert len(quarantaine) == 2
    assert quarantaine[0]["reason"] == "STALE_EVENT"
    assert quarantaine[1]["reason"] == "FUTURE_EVENT"


# ---------------------------------------------------------------------------
# 2. TEST D'INTÉGRATION SQL RAPIDE (DuckDB en mémoire sur le dataset sale)
# ---------------------------------------------------------------------------


def test_integration_sql_duckdb_sur_dataset_sale():
    """Vérifie le flux complet : fichier JSON sale -> nettoyage -> requête SQL DuckDB."""
    # 1. Lecture du fichier OpenData sale fourni dans data/
    chemin_fichier = Path(__file__).parent.parent / "data" / "weather_dirty.json"
    donnees_brutes = json.loads(chemin_fichier.read_text(encoding="utf-8"))

    # 2. Exécution du contrat + quarantaine avec date de référence fixe (reproductible)
    ref = datetime(2027, 3, 10, 12, 0, tzinfo=UTC)
    valides, quarantaine = split_valid_and_quarantine(donnees_brutes, reference_time=ref)

    # 3 lignes saines sur 10, 7 anomalies isolées en quarantaine
    assert len(valides) == 3
    assert len(quarantaine) == 7

    # 3. Chargement en mémoire dans DuckDB et contrôle analytique SQL
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE trusted_weather (
            station_id VARCHAR,
            observed_at TIMESTAMP,
            temperature_c DOUBLE,
            humidity_pct DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO trusted_weather VALUES (?, ?, ?, ?)",
        [
            (r["station_id"], r["observed_at"], r["temperature_c"], r["humidity_pct"])
            for r in valides
        ],
    )

    nb_lignes, nb_stations, temp_moyenne = con.execute(
        """
        SELECT
            COUNT(*) AS nb_lignes,
            COUNT(DISTINCT station_id) AS nb_stations,
            ROUND(AVG(temperature_c), 2) AS temp_moyenne
        FROM trusted_weather
        """
    ).fetchone()

    assert nb_lignes == 3
    assert nb_stations == 3
    assert temp_moyenne == 18.2
