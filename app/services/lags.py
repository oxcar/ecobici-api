"""
Servicio para calcular lags historicos desde snapshots GBFS.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


class LagsService:
    """Servicio para calcular lags de disponibilidad de bicicletas desde snapshots."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.data_path = self.settings.data_path
        # Lags requeridos por el modelo (en intervalos de 10 minutos)
        # lag_1 = 10 min atras, lag_2 = 20 min atras, etc.
        self.lag_intervals = {
            "lag_1": 10,      # 10 min atras
            "lag_2": 20,      # 20 min atras
            "lag_3": 30,      # 30 min atras
            "lag_6": 60,      # 60 min atras (1 hora)
            "lag_12": 120,    # 120 min atras (2 horas)
            "lag_144": 1440,  # 1440 min atras (24 horas / 1 dia)
        }

    def _get_snapshot_path(self, dt: datetime) -> Path:
        """
        Construye la ruta al snapshot para un datetime.

        Formato: data/gbfs/raw/YYYY/MM/DD/YYYYMMDD_HHMM/station_status.json
        """
        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        day = dt.strftime("%d")
        folder_name = dt.strftime("%Y%m%d_%H%M")

        return (
            self.data_path
            / "gbfs"
            / "raw"
            / year
            / month
            / day
            / folder_name
            / "station_status.json"
        )

    def _load_snapshot(self, dt: datetime) -> dict[str, Any] | None:
        """
        Carga un snapshot de station_status.json.

        Returns:
            Diccionario con station_id como clave y datos como valor, o None si no existe.
        """
        path = self._get_snapshot_path(dt)
        if not path.exists():
            logger.debug(f"Snapshot no encontrado: {path}")
            return None

        try:
            with open(path) as f:
                data = json.load(f)

            # Indexar por station_id para busqueda rapida
            stations = data.get("data", {}).get("stations", [])
            return {station["station_id"]: station for station in stations}

        except Exception as e:
            logger.error(f"Error al leer snapshot {path}: {e}")
            return None

    def _get_bikes_from_snapshot(
        self,
        snapshot: dict[str, Any],
        station_id: str,
    ) -> int | None:
        """Obtiene num_bikes_available de un snapshot para una estacion."""
        if not snapshot or station_id not in snapshot:
            return None
        return snapshot[station_id].get("num_bikes_available")

    async def get_lags_for_station(
        self,
        station_id: str,
        current_time: datetime | None = None,
        current_bikes: int | None = None,
    ) -> dict[str, int | None]:
        """
        Calcula los lags historicos para una estacion.

        Args:
            station_id: ID interno de la estacion (de GBFS station_status)
            current_time: Timestamp actual (default: ahora)
            current_bikes: Bicicletas disponibles actualmente (fallback)

        Returns:
            Diccionario con los lags calculados.
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        # Convertir a hora local de Mexico (UTC-6)
        mexico_offset = timedelta(hours=-6)
        current_time_mx = current_time + mexico_offset

        # Truncar a minuto (sin segundos/microsegundos)
        current_time_mx = current_time_mx.replace(second=0, microsecond=0)

        lags: dict[str, int | None] = {
            "num_bikes_available_lag_1": None,
            "num_bikes_available_lag_2": None,
            "num_bikes_available_lag_3": None,
            "num_bikes_available_lag_6": None,
            "num_bikes_available_lag_12": None,
            "num_bikes_available_lag_144": None,
        }

        # Calcular cada lag
        for lag_name, minutes_back in self.lag_intervals.items():
            lag_time = current_time_mx - timedelta(minutes=minutes_back)
            snapshot = self._load_snapshot(lag_time)

            if snapshot:
                bikes = self._get_bikes_from_snapshot(snapshot, station_id)
                if bikes is not None:
                    lags[f"num_bikes_available_{lag_name}"] = bikes
                    logger.debug(
                        f"Lag {lag_name} ({lag_time.strftime('%Y%m%d_%H%M')}): "
                        f"{bikes} bicicletas"
                    )

        # Si no encontramos algunos lags, usar el valor actual como fallback
        if current_bikes is not None:
            for key, value in lags.items():
                if value is None:
                    lags[key] = current_bikes
                    logger.debug(f"{key} no encontrado, usando valor actual: {current_bikes}")

        return lags

    async def get_recent_data(
        self,
        station_id: str,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        """
        Obtiene datos historicos recientes para una estacion.

        Args:
            station_id: ID interno de la estacion
            hours: Horas de datos a obtener

        Returns:
            Lista de registros historicos.
        """
        now = datetime.now(timezone.utc)
        mexico_offset = timedelta(hours=-6)
        now_mx = now + mexico_offset
        now_mx = now_mx.replace(second=0, microsecond=0)

        results = []
        current_time = now_mx

        # Iterar minuto a minuto hacia atras
        for _ in range(hours * 60):
            snapshot = self._load_snapshot(current_time)
            if snapshot and station_id in snapshot:
                station_data = snapshot[station_id]
                station_data["snapshot_time"] = current_time.isoformat()
                results.append(station_data)

            current_time -= timedelta(minutes=1)

        # Ordenar cronologicamente (mas antiguo primero)
        results.reverse()
        return results


# Instancia singleton del servicio
lags_service = LagsService()
