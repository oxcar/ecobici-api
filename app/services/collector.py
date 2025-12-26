"""
Colector de datos GBFS para Ecobici.

Captura snapshots del estado de las estaciones cada minuto
y los almacena en formato parquet por dia.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
import polars as pl

from app.config import get_settings

# Zona horaria de Ciudad de Mexico
CDMX_TZ = ZoneInfo("America/Mexico_City")

logger = logging.getLogger(__name__)


class GBFSCollector:
    """Colector de datos GBFS de Ecobici."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._http_client: Optional[httpx.AsyncClient] = None

        # URLs de los feeds GBFS
        self._station_info_url = (
            f"{self._settings.gbfs_base_url}/en/station_information.json"
        )
        self._station_status_url = (
            f"{self._settings.gbfs_base_url}/en/station_status.json"
        )

    @property
    def snapshots_path(self) -> Path:
        """Ruta base para los snapshots."""
        return self._settings.gbfs_snapshots_path

    async def start(self) -> None:
        """Inicializa el cliente HTTP del colector."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self._settings.gbfs_timeout)
            logger.info("Cliente HTTP del colector GBFS inicializado")

    async def stop(self) -> None:
        """Cierra el cliente HTTP del colector."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
            logger.info("Cliente HTTP del colector GBFS cerrado")

    async def collect_snapshot(self, max_retries: int = 3) -> None:
        """Captura y guarda un snapshot del estado de las estaciones con reintentos."""
        for attempt in range(max_retries):
            try:
                df = await self._collect_snapshot()
                if df is not None and not df.is_empty():
                    logger.debug(f"Snapshot capturado: {len(df)} estaciones")
                    self._save_snapshot(df)
                    return
                else:
                    logger.warning(f"Snapshot vacio en intento {attempt + 1}/{max_retries}")
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                else:
                    logger.error(f"Error al capturar snapshot tras {max_retries} intentos: {e}")

    async def _fetch_station_info(self) -> dict:
        """Obtiene informacion de las estaciones."""
        response = await self._http_client.get(self._station_info_url) # type: ignore
        response.raise_for_status()
        return response.json()

    async def _fetch_station_status(self) -> dict:
        """Obtiene estado actual de las estaciones."""
        response = await self._http_client.get(self._station_status_url) # type: ignore
        response.raise_for_status()
        return response.json()

    async def _collect_snapshot(self) -> Optional[pl.DataFrame]:
        """Captura un snapshot del estado de las estaciones."""
        snapshot_time = datetime.now(timezone.utc).replace(microsecond=0)

        # Obtener datos en paralelo
        info_data, status_data = await asyncio.gather(
            self._fetch_station_info(),
            self._fetch_station_status(),
        )

        # Crear diccionario de informacion de estaciones
        stations_info = {}
        for station in info_data.get("data", {}).get("stations", []):
            stations_info[station["station_id"]] = {
                "station_code": station.get("short_name"),
                "name": station.get("name", ""),
                "latitude": station.get("lat"),
                "longitude": station.get("lon"),
                "capacity": station.get("capacity", 0),
            }

        # Construir registros combinando info y status
        records = []
        for station in status_data.get("data", {}).get("stations", []):
            station_id = station.get("station_id")
            info = stations_info.get(station_id)

            if info is None or info.get("station_code") is None:
                continue

            # Convertir epoch a datetime UTC
            last_reported = station.get("last_reported")

            records.append({
                "snapshot_time": snapshot_time,
                "station_id": station_id,
                "station_code": info["station_code"],
                "name": info["name"],
                "capacity": info["capacity"],
                "latitude": info["latitude"],
                "longitude": info["longitude"],
                "bikes_available": station.get("num_bikes_available", 0),
                "bikes_disabled": station.get("num_bikes_disabled", 0),
                "docks_available": station.get("num_docks_available", 0),
                "docks_disabled": station.get("num_docks_disabled", 0),
                "is_installed": station.get("is_installed", 0),
                "is_renting": station.get("is_renting", 0),
                "is_returning": station.get("is_returning", 0),
                "last_reported": (
                    datetime.fromtimestamp(last_reported, tz=timezone.utc)
                    if last_reported else None
                ),
            })

        if not records:
            return None

        return pl.DataFrame(records)

    def _save_snapshot(self, df: pl.DataFrame) -> Path:
        """Guarda el snapshot en archivo parquet diario."""
        # Obtener fecha del snapshot en hora de Ciudad de Mexico para particionar
        snapshot_time = df["snapshot_time"][0]
        # Convertir a hora de CDMX para determinar la fecha del archivo
        snapshot_cdmx = snapshot_time.astimezone(CDMX_TZ)
        year = snapshot_cdmx.strftime("%Y")
        month = snapshot_cdmx.strftime("%m")
        date_str = snapshot_cdmx.strftime("%Y%m%d")

        # Crear directorio de salida
        output_dir = self.snapshots_path / f"year={year}" / f"month={month}"
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / f"gbfs_{date_str}.parquet"

        # Si existe el archivo, cargar y concatenar
        if output_file.exists():
            existing_df = pl.read_parquet(output_file)
            df = pl.concat([existing_df, df])
            # Eliminar duplicados por snapshot_time y station_code
            df = df.unique(subset=["snapshot_time", "station_code"], keep="last")
            df = df.sort(["station_code", "snapshot_time"])

        df.write_parquet(output_file)
        logger.info(f"Snapshot guardado en {output_file}: {len(df)} registros")

        return output_file


# Instancia singleton del colector
gbfs_collector = GBFSCollector()
