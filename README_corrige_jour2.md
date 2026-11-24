# Corrigé TP DataOps — Jour 2 (Slide 56)

Implémentation simple, lisible et commentée en français de l'atelier guidé **Journée 2** : *Data Contracts, Quarantaine (DLQ) & suite pytest*.

## Contenu de la branche `jour2`

| Fichier | Rôle dans l'atelier (p. 56) |
| :--- | :--- |
| `data/weather_dirty.json` | Jeu de données météo sale (10 lignes : 3 saines + 7 anomalies couvrant les 6 dimensions qualité). |
| `src/contracts.py` | **Étape 1** — Data Contract strict **Pydantic v2** (`WeatherEvent`) : format `FR-XXXX`, bornes physiques `[-50, 60] °C` et `[0, 100] %`, rejet des colonnes inconnues (`extra="forbid"`), nettoyage (`trim` + majuscules) et timezone obligatoire convertie en **UTC**. |
| `src/transform.py` | **Étape 2** — Fonction pure `split_valid_and_quarantine()` : valide chaque ligne, contrôle la fraîcheur (avec `reference_time` injectable), déduplique de manière déterministe sur `(station_id, observed_at)` et renvoie `(valides, quarantaine)` avec le motif exact d'erreur. |
| `tests/test_transform.py` | **Étape 3** — 8 tests unitaires (normalisation + chaque anomalie) + 1 test d'intégration SQL en mémoire via **DuckDB** sur `data/weather_dirty.json`. |
| `pyproject.toml` | Configuration minimale (`pydantic`, `duckdb`, `pytest`, `pytest-cov`, `ruff`). |

## Vérifications effectuées (Étape 4)

- `ruff check .` et `ruff format --check .` : **0 erreur**
- `pytest -v --cov=src` : **9/9 tests passés**, couverture **98 %** (> 85 % demandés)

## Lancer le corrigé en local

Avec **uv** :
```bash
uv sync
uv run ruff check .
uv run pytest -v --cov=src
```

Ou avec **pip** :
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest -v --cov=src
```
