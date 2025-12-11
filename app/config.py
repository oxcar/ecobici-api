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

    # Directorio base de datos (se configura via DATA_PATH)
    data_path: Path = API_BASE_DIR / "data"

    # Propiedades derivadas del data_path
    @property
    def models_path(self) -> Path:
        """Ruta a los modelos."""
        return self.data_path / "models"

    @property
    def statistics_path(self) -> Path:
        """Ruta a las estadisticas."""
        return self.data_path / "statistics"

    @property
    def gbfs_snapshots_path(self) -> Path:
        """Ruta a los snapshots GBFS."""
        return self.data_path / "gbfs"

    @property
    def cache_path(self) -> Path:
        """Ruta al cache."""
        return self.data_path / "cache"

    # GBFS API
    gbfs_base_url: str = "https://gbfs.mex.lyftbikes.com/gbfs"
    gbfs_timeout: int = 10

    # GBFS Collector
    gbfs_collector_enabled: bool = True

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
