"""
Servicio para obtener datos en tiempo real de GBFS (General Bikeshare Feed Specification).
"""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class GBFSService:
    """Servicio para interactuar con la API GBFS de Ecobici."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.gbfs_base_url
        self.timeout = self.settings.gbfs_timeout
        # Cache indexado por station_id (interno de GBFS)
        self._station_info_cache: dict[str, dict[str, Any]] = {}
        self._station_status_cache: dict[str, dict[str, Any]] = {}
        # Mapeo de short_name (station_code) a station_id
        self._short_name_to_id: dict[str, str] = {}
        # Timestamps de cache separados
        self._station_info_timestamp: datetime | None = None
        self._station_status_timestamp: datetime | None = None
        # TTL diferenciados: station_info cambia poco, station_status cambia constantemente
        self._station_info_ttl_seconds = 86400  # 24 horas para station_information
        self._station_status_ttl_seconds = 60   # 1 minuto para station_status

    async def _fetch_json(self, url: str) -> dict[str, Any]:
        """Realiza una peticion HTTP y devuelve el JSON."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def _refresh_station_info(self) -> None:
        """Actualiza el cache de informacion de estaciones si es necesario."""
        now = datetime.now(timezone.utc)

        if (
            self._station_info_timestamp
            and (now - self._station_info_timestamp).total_seconds() < self._station_info_ttl_seconds
        ):
            return  # Cache todavia valido

        logger.info("Actualizando cache de station_information...")

        try:
            station_info_url = f"{self.base_url}/es/station_information.json"
            station_info_data = await self._fetch_json(station_info_url)

            self._station_info_cache = {}
            self._short_name_to_id = {}

            for station in station_info_data["data"]["stations"]:
                station_id = station["station_id"]
                short_name = station.get("short_name", "")
                self._station_info_cache[station_id] = station
                if short_name:
                    self._short_name_to_id[short_name] = station_id

            self._station_info_timestamp = now
            logger.info(f"Cache de station_information actualizado con {len(self._station_info_cache)} estaciones")

        except httpx.HTTPError as e:
            logger.error(f"Error al actualizar cache de station_information: {e}")
            raise

    async def _refresh_station_status(self) -> None:
        """Actualiza el cache de estado de estaciones si es necesario."""
        now = datetime.now(timezone.utc)

        if (
            self._station_status_timestamp
            and (now - self._station_status_timestamp).total_seconds() < self._station_status_ttl_seconds
        ):
            return  # Cache todavia valido

        logger.info("Actualizando cache de station_status...")

        try:
            station_status_url = f"{self.base_url}/es/station_status.json"
            station_status_data = await self._fetch_json(station_status_url)

            self._station_status_cache = {
                station["station_id"]: station
                for station in station_status_data["data"]["stations"]
            }

            self._station_status_timestamp = now
            logger.debug(f"Cache de station_status actualizado")

        except httpx.HTTPError as e:
            logger.error(f"Error al actualizar cache de station_status: {e}")
            raise

    async def _refresh_cache(self) -> None:
        """Actualiza ambos caches si es necesario."""
        await self._refresh_station_info()
        await self._refresh_station_status()

    def _resolve_station_id(self, station_code: str) -> str | None:
        """
        Resuelve un station_code (short_name) a station_id interno.

        Args:
            station_code: Codigo de la estacion (short_name, ej: "001", "123")

        Returns:
            station_id interno o None si no se encuentra.
        """
        # Buscar directamente por short_name
        if station_code in self._short_name_to_id:
            return self._short_name_to_id[station_code]

        # Intentar con ceros a la izquierda (ej: "1" -> "001")
        padded = station_code.zfill(3)
        if padded in self._short_name_to_id:
            return self._short_name_to_id[padded]

        # Intentar sin ceros a la izquierda (ej: "001" -> "1")
        stripped = station_code.lstrip("0") or "0"
        if stripped in self._short_name_to_id:
            return self._short_name_to_id[stripped]

        return None

    async def get_station_status(self, station_code: str) -> dict[str, Any] | None:
        """
        Obtiene el estado actual de una estacion.

        Args:
            station_code: Codigo de la estacion (short_name, ej: "001", "002")

        Returns:
            Diccionario con el estado de la estacion o None si no existe.
        """
        await self._refresh_cache()

        station_id = self._resolve_station_id(station_code)
        if station_id and station_id in self._station_status_cache:
            return self._station_status_cache[station_id]

        logger.warning(f"Estacion {station_code} no encontrada en GBFS")
        return None

    async def get_station_info(self, station_code: str) -> dict[str, Any] | None:
        """
        Obtiene la informacion de una estacion.

        Args:
            station_code: Codigo de la estacion (short_name, ej: "001", "002")

        Returns:
            Diccionario con la informacion de la estacion o None si no existe.
        """
        await self._refresh_cache()

        station_id = self._resolve_station_id(station_code)
        if station_id and station_id in self._station_info_cache:
            return self._station_info_cache[station_id]

        logger.warning(f"Estacion {station_code} no encontrada en GBFS")
        return None

    async def get_station_data(self, station_code: str) -> dict[str, Any] | None:
        """
        Obtiene datos completos de una estacion (info + status).

        Args:
            station_code: Codigo de la estacion (short_name)

        Returns:
            Diccionario con datos combinados o None si no existe.
        """
        info = await self.get_station_info(station_code)
        status = await self.get_station_status(station_code)

        if not info or not status:
            return None

        return {
            "station_code": info.get("short_name", station_code),
            "station_id": info.get("station_id"),
            "name": info.get("name"),
            "latitude": info.get("lat"),
            "longitude": info.get("lon"),
            "capacity": info.get("capacity", 0),
            "num_bikes_available": status.get("num_bikes_available", 0),
            "num_docks_available": status.get("num_docks_available", 0),
            "is_installed": status.get("is_installed", False),
            "is_renting": status.get("is_renting", False),
            "is_returning": status.get("is_returning", False),
            "last_reported": status.get("last_reported"),
        }

    async def is_available(self) -> bool:
        """Verifica si el servicio GBFS esta disponible."""
        try:
            await self._refresh_cache()
            return len(self._station_status_cache) > 0
        except Exception:
            return False

    async def get_all_stations(self) -> list[dict[str, Any]]:
        """Obtiene todas las estaciones con su estado actual."""
        await self._refresh_cache()

        stations = []
        for station_id, info in self._station_info_cache.items():
            status = self._station_status_cache.get(station_id, {})
            stations.append({
                "station_code": info.get("short_name", ""),
                "station_id": station_id,
                "name": info.get("name"),
                "latitude": info.get("lat"),
                "longitude": info.get("lon"),
                "capacity": info.get("capacity", 0),
                "num_bikes_available": status.get("num_bikes_available", 0),
                "num_docks_available": status.get("num_docks_available", 0),
            })

        return stations


# Instancia singleton del servicio
gbfs_service = GBFSService()
