"""
Configuracion de la aplicacion.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Directorio base de la API (donde esta este archivo)
API_BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configuracion de la aplicacion."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignorar variables de entorno extra
    )

    # Rutas (relativas al directorio de la API)
    models_path: Path = API_BASE_DIR / "data" / "models"
    data_path: Path = API_BASE_DIR / "data"
    statistics_path: Path = API_BASE_DIR / "data" / "statistics"

    # GBFS API
    gbfs_base_url: str = "https://gbfs.mex.lyftbikes.com/gbfs"
    gbfs_timeout: int = 10

    # GBFS Collector
    gbfs_collector_enabled: bool = True
    gbfs_snapshots_path: Path = API_BASE_DIR / "data" / "gbfs"

    # Open-Meteo API
    openmeteo_base_url: str = "https://api.open-meteo.com/v1"
    openmeteo_timeout: int = 10

    # Coordenadas de CDMX (centro aproximado de Ecobici)
    cdmx_latitude: float = 19.4326
    cdmx_longitude: float = -99.1332

    # Logging
    log_level: str = "INFO"

    # API
    api_title: str = "Ecobici Prediction API"
    api_version: str = "0.1.0"
    api_description: str = "API de prediccion de disponibilidad de bicicletas Ecobici CDMX"


@lru_cache
def get_settings() -> Settings:
    """Obtiene la configuracion cacheada."""
    return Settings()
