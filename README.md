# TP DataOps — Jour 2 : Data Contracts, Quarantaine & pytest

Correction simple et pédagogique de l'atelier guidé **Journée 2 (slide 56)**.

## Structure du projet

- `data/weather_dirty.json` : jeu de données météo sale (10 lignes : 3 valides + 7 anomalies couvrant les 6 dimensions qualité).
- `src/contracts.py` : contrat de données strict **Pydantic v2** (`WeatherEvent`) avec nettoyage (`trim`, majuscules) et normalisation **UTC**.
- `src/transform.py` : fonction pure `split_valid_and_quarantine()` qui sépare les lignes valides, vérifie la fraîcheur, déduplique et isole les erreurs en quarantaine motivée (DLQ).
- `tests/test_transform.py` : 8 tests unitaires + 1 test d'intégration SQL en mémoire avec **DuckDB**.

## Lancer les vérifications en local

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
