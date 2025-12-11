"""
Esquemas Pydantic para la API.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ModelType = Literal["m1", "m2"]


class WeatherData(BaseModel):
    """Datos meteorologicos."""

    temperature_2m: float = Field(..., description="Temperatura a 2m (C)")
    rain: float = Field(..., description="Lluvia (mm)")
    surface_pressure: float = Field(..., description="Presion superficial (hPa)")
    cloud_cover: float = Field(..., description="Cobertura de nubes (%)")
    wind_speed_10m: float = Field(..., description="Velocidad del viento a 10m (km/h)")
    relative_humidity_2m: float = Field(..., description="Humedad relativa (%)")


class WeatherInput(BaseModel):
    """Datos meteorologicos de entrada para prediccion."""

    temperature_2m: float = Field(..., description="Temperatura a 2m (C)")
    rain: float = Field(..., description="Lluvia (mm)")
    surface_pressure: float = Field(..., description="Presion superficial (hPa)")
    cloud_cover: float = Field(..., description="Cobertura de nubes (%)")
    wind_speed_10m: float = Field(..., description="Velocidad del viento a 10m (km/h)")
    relative_humidity_2m: float = Field(..., description="Humedad relativa (%)")
    model: ModelType = Field(default="m1", description="Modelo a usar: m1=XGBoost, m2=LSTM")


class Predictions(BaseModel):
    """Predicciones de disponibilidad."""

    bikes_20min: int = Field(..., description="Bicicletas disponibles en 20 min")
    bikes_40min: int = Field(..., description="Bicicletas disponibles en 40 min")
    bikes_60min: int = Field(..., description="Bicicletas disponibles en 60 min")


class PredictionResponse(BaseModel):
    """Respuesta de prediccion."""

    station_code: str = Field(..., description="Codigo de la estacion")
    timestamp: datetime = Field(..., description="Timestamp de la prediccion")
    current_bikes: int = Field(..., description="Bicicletas disponibles actualmente")
    capacity: int = Field(..., description="Capacidad total de la estacion")
    predictions: Predictions = Field(..., description="Predicciones")
    weather: WeatherData = Field(..., description="Datos meteorologicos actuales")


class StationStatus(BaseModel):
    """Estado de una estacion GBFS."""

    station_id: str
    num_bikes_available: int
    num_docks_available: int
    is_installed: bool
    is_renting: bool
    is_returning: bool
    last_reported: int


class StationInfo(BaseModel):
    """Informacion de una estacion GBFS."""

    station_id: str
    name: str
    lat: float
    lon: float
    capacity: int


class HealthResponse(BaseModel):
    """Respuesta del health check."""

    status: str = Field(..., description="Estado del servicio")
    timestamp: datetime = Field(..., description="Timestamp")
    models_loaded: bool = Field(..., description="Modelos cargados")
    gbfs_available: bool = Field(..., description="GBFS disponible")


class ErrorResponse(BaseModel):
    """Respuesta de error."""

    detail: str = Field(..., description="Detalle del error")
    timestamp: datetime = Field(default_factory=datetime.now)


class HistoryRecord(BaseModel):
    """Registro historico de disponibilidad."""

    snapshot_time: datetime = Field(..., description="Timestamp del snapshot")
    num_bikes_available: int = Field(..., description="Bicicletas disponibles")
    num_bikes_disabled: int = Field(..., description="Bicicletas deshabilitadas")
    num_docks_available: int = Field(..., description="Docks disponibles")
    num_docks_disabled: int = Field(..., description="Docks deshabilitados")


class HistoryResponse(BaseModel):
    """Respuesta del historial de disponibilidad."""

    station_code: str = Field(..., description="Codigo de la estacion")
    date: str = Field(..., description="Fecha del historial (YYYY-MM-DD)")
    records: list[HistoryRecord] = Field(..., description="Registros historicos")
