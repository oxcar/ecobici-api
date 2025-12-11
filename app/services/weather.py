"""
Servicio para obtener datos meteorologicos de Open-Meteo.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class WeatherService:
    """Servicio para interactuar con la API de Open-Meteo."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.openmeteo_base_url
        self.timeout = self.settings.openmeteo_timeout
        self._cache: dict[str, Any] | None = None
        self._cache_timestamp: datetime | None = None
        self._cache_ttl_seconds = 300  # Cache por 5 minutos

    async def get_current_weather(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> dict[str, float]:
        """
        Obtiene los datos meteorologicos actuales.

        Args:
            latitude: Latitud (default: centro de CDMX)
            longitude: Longitud (default: centro de CDMX)

        Returns:
            Diccionario con las variables meteorologicas.
        """
        lat = latitude or self.settings.cdmx_latitude
        lon = longitude or self.settings.cdmx_longitude

        # Verificar cache
        now = datetime.now(timezone.utc)
        if (
            self._cache
            and self._cache_timestamp
            and (now - self._cache_timestamp).total_seconds() < self._cache_ttl_seconds
        ):
            return self._cache

        # Variables meteorologicas requeridas por el modelo
        weather_vars = [
            "temperature_2m",
            "apparent_temperature",
            "rain",
            "surface_pressure",
            "cloud_cover",
            "wind_speed_10m",
            "relative_humidity_2m",
        ]

        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ",".join(weather_vars),
            "timezone": "America/Mexico_City",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/forecast", params=params)
                response.raise_for_status()
                data = response.json()

            current = data.get("current", {})

            weather_data = {
                "temperature_2m": current.get("temperature_2m", 20.0),
                "apparent_temperature": current.get("apparent_temperature", 20.0),
                "rain": current.get("rain", 0.0),
                "surface_pressure": current.get("surface_pressure", 1013.0),
                "cloud_cover": current.get("cloud_cover", 0.0),
                "wind_speed_10m": current.get("wind_speed_10m", 0.0),
                "relative_humidity_2m": current.get("relative_humidity_2m", 50.0),
            }

            # Actualizar cache
            self._cache = weather_data
            self._cache_timestamp = now

            logger.info(f"Datos meteorologicos obtenidos: temp={weather_data['temperature_2m']}C")
            return weather_data

        except httpx.HTTPError as e:
            logger.error(f"Error al obtener datos meteorologicos: {e}")
            # Devolver valores por defecto en caso de error
            return self._get_default_weather()

    def _get_default_weather(self) -> dict[str, float]:
        """Devuelve valores meteorologicos por defecto."""
        return {
            "temperature_2m": 20.0,
            "apparent_temperature": 20.0,
            "rain": 0.0,
            "surface_pressure": 1013.0,
            "cloud_cover": 50.0,
            "wind_speed_10m": 5.0,
            "relative_humidity_2m": 50.0,
        }

    async def get_forecast(
        self,
        latitude: float | None = None,
        longitude: float | None = None,
        hours: int = 2,
    ) -> list[dict[str, Any]]:
        """
        Obtiene el pronostico meteorologico para las proximas horas.

        Args:
            latitude: Latitud (default: centro de CDMX)
            longitude: Longitud (default: centro de CDMX)
            hours: Numero de horas a pronosticar

        Returns:
            Lista de diccionarios con el pronostico por hora.
        """
        lat = latitude or self.settings.cdmx_latitude
        lon = longitude or self.settings.cdmx_longitude

        weather_vars = [
            "temperature_2m",
            "apparent_temperature",
            "rain",
            "surface_pressure",
            "cloud_cover",
            "wind_speed_10m",
            "relative_humidity_2m",
        ]

        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(weather_vars),
            "forecast_hours": hours,
            "timezone": "America/Mexico_City",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/forecast", params=params)
                response.raise_for_status()
                data = response.json()

            hourly = data.get("hourly", {})
            times = hourly.get("time", [])

            forecast = []
            for i, time in enumerate(times[:hours]):
                forecast.append({
                    "time": time,
                    "temperature_2m": hourly.get("temperature_2m", [20.0])[i],
                    "apparent_temperature": hourly.get("apparent_temperature", [20.0])[i],
                    "rain": hourly.get("rain", [0.0])[i],
                    "surface_pressure": hourly.get("surface_pressure", [1013.0])[i],
                    "cloud_cover": hourly.get("cloud_cover", [50.0])[i],
                    "wind_speed_10m": hourly.get("wind_speed_10m", [5.0])[i],
                    "relative_humidity_2m": hourly.get("relative_humidity_2m", [50.0])[i],
                })

            return forecast

        except httpx.HTTPError as e:
            logger.error(f"Error al obtener pronostico: {e}")
            return []


# Instancia singleton del servicio
weather_service = WeatherService()
