"""Nettoyage, déduplication et routage vers la Quarantaine (Dead-Letter Queue).

Toute fonction ici est pure (aucun appel réseau ni base Cloud) :
elle est donc rapide et facile à tester avec pytest.
"""

from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from src.contracts import WeatherEvent


def split_valid_and_quarantine(
    records: list[dict],
    reference_time: datetime | None = None,
    max_age_hours: int = 24,
) -> tuple[list[dict], list[dict]]:
    """Sépare un lot brut en deux listes : lignes valides et lignes en quarantaine.

    Règles appliquées :
    1. Validation du contrat Pydantic (complétude, validité, exactitude, trim, UTC).
    2. Contrôle de fraîcheur (si `reference_time` est fourni : pas dans le futur,
       ni plus vieux que `max_age_hours`).
    3. Déduplication déterministe sur la clé logique `(station_id, observed_at)` :
       la première occurrence valide est conservée, les suivantes partent en quarantaine.
    """
    valides: list[dict] = []
    quarantaine: list[dict] = []
    cles_vues: set[tuple[str, str]] = set()

    # On normalise la date de référence en UTC si elle est fournie
    ref_utc = reference_time.astimezone(UTC) if reference_time is not None else None

    for brut in records:
        # 1. Validation du contrat (schéma, types, bornes, trim et conversion UTC)
        try:
            evt = WeatherEvent.model_validate(brut)
        except ValidationError as exc:
            # On enregistre la ligne brute et le premier motif d'erreur pour audit
            quarantaine.append({"raw": brut, "reason": exc.errors()[0]["msg"]})
            continue

        # 2. Contrôle de fraîcheur (dimension Timeliness)
        if ref_utc is not None:
            if evt.observed_at > ref_utc:
                quarantaine.append({"raw": brut, "reason": "FUTURE_EVENT"})
                continue
            if ref_utc - evt.observed_at > timedelta(hours=max_age_hours):
                quarantaine.append({"raw": brut, "reason": "STALE_EVENT"})
                continue

        # 3. Contrôle d'unicité (déduplication déterministe sur clé métier)
        cle_metier = (evt.station_id, evt.observed_at.isoformat())
        if cle_metier in cles_vues:
            quarantaine.append({"raw": brut, "reason": "DUPLICATE_EVENT"})
            continue

        cles_vues.add(cle_metier)
        # On sérialise en JSON propre (dates ISO-8601 en UTC)
        valides.append(evt.model_dump(mode="json"))

    return valides, quarantaine
