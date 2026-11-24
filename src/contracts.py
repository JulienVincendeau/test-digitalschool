"""Contrat de données (Data Contract) pour les observations météo.

Utilise Pydantic v2 pour valider chaque mesure dès l'entrée du pipeline
(principe Shift-Left : bloquer les anomalies au plus tôt).
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WeatherEvent(BaseModel):
    """Schéma strict d'une observation météo."""

    # Rejette toute colonne inattendue non déclarée dans le contrat
    model_config = ConfigDict(extra="forbid")

    # Validité : code station au format FR-0075 (FR- suivi de 4 chiffres)
    station_id: str = Field(pattern=r"^FR-[0-9]{4}$")
    # Cohérence temporelle : horodatage obligatoire avec fuseau horaire
    observed_at: datetime
    # Exactitude : bornes physiques plausibles pour la température (°C)
    temperature_c: float = Field(ge=-50.0, le=60.0)
    # Validité : humidité comprise entre 0 % et 100 %
    humidity_pct: float = Field(ge=0.0, le=100.0)

    @field_validator("station_id", mode="before")
    @classmethod
    def nettoyer_station_id(cls, valeur: object) -> object:
        """Supprime les espaces autour et met en majuscules avant validation."""
        if isinstance(valeur, str):
            return valeur.strip().upper()
        return valeur

    @field_validator("observed_at")
    @classmethod
    def verifier_et_convertir_utc(cls, valeur: datetime) -> datetime:
        """Impose la présence d'une timezone et convertit la date en UTC."""
        if valeur.tzinfo is None:
            raise ValueError("Timezone obligatoire sur observed_at")
        return valeur.astimezone(UTC)
