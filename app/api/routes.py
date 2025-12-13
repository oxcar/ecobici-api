"""
Rutas de la API.
"""

import logging
import time
from collections import defaultdict
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import polars as pl
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.models.schemas import (
    ErrorResponse,
    FeedbackInput,
    FeedbackResponse,
    HealthResponse,
    Predictions,
    PredictionResponse,
    WeatherData,
    WeatherInput,
)
from app.services.feedback import feedback_service
from app.services.gbfs import gbfs_service
from app.services.history import history_service
from app.services.lags import lags_service
from app.services.predictor import predictor_service

logger = logging.getLogger(__name__)

# Timezone de Ciudad de Mexico
CDMX_TZ = ZoneInfo("America/Mexico_City")

# Rate limiting para feedback: maximo 5 peticiones por minuto por IP
feedback_rate_limit = defaultdict(list)
FEEDBACK_MAX_REQUESTS = 5
FEEDBACK_WINDOW_SECONDS = 60

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Health check del servicio.

    Verifica que los modelos esten cargados y que GBFS este disponible.
    """
    gbfs_available = await gbfs_service.is_available()

    return HealthResponse(
        status="healthy" if predictor_service.is_loaded and gbfs_available else "degraded",
        timestamp=datetime.now(CDMX_TZ),
        models_loaded=predictor_service.is_loaded,
        gbfs_available=gbfs_available,
    )


@router.post(
    "/predict/{station_code}",
    response_model=PredictionResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Estacion no encontrada"},
        500: {"model": ErrorResponse, "description": "Error interno"},
    },
)
async def predict_availability(
    station_code: str,
    weather_input: WeatherInput,
) -> PredictionResponse:
    """
    Predice la disponibilidad de bicicletas para una estacion.

    Args:
        station_code: Codigo de la estacion (ej: "001", "123")
        weather_input: Datos meteorologicos (temperature_2m, rain, surface_pressure,
                      cloud_cover, wind_speed_10m, relative_humidity_2m)

    Returns:
        Predicciones de disponibilidad para 20, 40 y 60 minutos.
    """
    now = datetime.now(CDMX_TZ)

    # Obtener datos de la estacion desde GBFS
    station_data = await gbfs_service.get_station_data(station_code)
    if not station_data:
        raise HTTPException(
            status_code=404,
            detail=f"Estacion {station_code} no encontrada",
        )

    # Usar datos meteorologicos proporcionados por el cliente
    weather_data = {
        "temperature_2m": weather_input.temperature_2m,
        "rain": weather_input.rain,
        "surface_pressure": weather_input.surface_pressure,
        "cloud_cover": weather_input.cloud_cover,
        "wind_speed_10m": weather_input.wind_speed_10m,
        "relative_humidity_2m": weather_input.relative_humidity_2m,
    }

    # Obtener lags historicos (usando station_id para buscar en parquet)
    lags = await lags_service.get_lags_for_station(
        station_id=station_data.get("station_id"),
        current_time=now,
        current_bikes=station_data.get("num_bikes_available"),
    )

    # Verificar si es dia festivo (simplificado - se puede mejorar)
    is_holiday = False  # TODO: Implementar verificacion de dias festivos

    # Realizar prediccion
    try:
        predictions = predictor_service.predict(
            station_data=station_data,
            weather_data=weather_data,
            lags=lags,
            timestamp=now,
            is_holiday=is_holiday,
            model_type=weather_input.model,
        )
    except RuntimeError as e:
        logger.error(f"Error en prediccion: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error al realizar la prediccion. Los modelos pueden no estar cargados.",
        )

    return PredictionResponse(
        station_code=station_code,
        timestamp=now,
        current_bikes=station_data.get("num_bikes_available", 0),
        capacity=station_data.get("capacity", 0),
        predictions=Predictions(
            bikes_20min=predictions["bikes_20min"],
            bikes_40min=predictions["bikes_40min"],
            bikes_60min=predictions["bikes_60min"],
        ),
        weather=WeatherData(
            temperature_2m=weather_data["temperature_2m"],
            rain=weather_data["rain"],
            surface_pressure=weather_data["surface_pressure"],
            cloud_cover=weather_data["cloud_cover"],
            wind_speed_10m=weather_data["wind_speed_10m"],
            relative_humidity_2m=weather_data["relative_humidity_2m"],
        ),
    )


def _df_to_parquet_response(df: pl.DataFrame, filename: str) -> Response:
    """Convierte un DataFrame a respuesta parquet."""
    buffer = BytesIO()
    df.write_parquet(buffer, compression="snappy")
    buffer.seek(0)

    return Response(
        content=buffer.getvalue(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get(
    "/history/{station_code}/yesterday",
    responses={
        404: {"model": ErrorResponse, "description": "Estacion o datos no encontrados"},
    },
)
async def get_history_yesterday(station_code: str) -> Response:
    """
    Obtiene el historial de disponibilidad del dia anterior para una estacion.

    Args:
        station_code: Codigo de la estacion (ej: "001", "123")

    Returns:
        Archivo parquet con el historial de disponibilidad cada 10 minutos.
    """
    try:
        result = await history_service.get_yesterday(station_code)

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontraron datos para la estacion {station_code}",
            )

        df, date_str = result
        return _df_to_parquet_response(df, f"{station_code}_yesterday_{date_str}.parquet")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al obtener historial yesterday para {station_code}: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno: {e}")


@router.get(
    "/history/{station_code}/today",
    responses={
        404: {"model": ErrorResponse, "description": "Estacion o datos no encontrados"},
    },
)
async def get_history_today(station_code: str) -> Response:
    """
    Obtiene el historial de disponibilidad del dia actual para una estacion.

    Los datos se actualizan cada 10 minutos.

    Args:
        station_code: Codigo de la estacion (ej: "001", "123")

    Returns:
        Archivo parquet con el historial de disponibilidad cada 10 minutos.
    """
    try:
        result = await history_service.get_today(station_code)

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontraron datos para la estacion {station_code}",
            )

        df, date_str = result
        return _df_to_parquet_response(df, f"{station_code}_today_{date_str}.parquet")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al obtener historial today para {station_code}: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno: {e}")


@router.get(
    "/history/{station_code}/average",
    responses={
        404: {"model": ErrorResponse, "description": "Estacion o datos no encontrados"},
    },
)
async def get_history_average(station_code: str) -> Response:
    """
    Obtiene el promedio de disponibilidad de los ultimos 30 dias.
    
    Calcula promedios separados para dias entre semana (lunes-viernes)
    y fines de semana (sabado-domingo).

    Args:
        station_code: Codigo de la estacion (ej: "001", "123")

    Returns:
        Archivo parquet con promedios por hora del dia:
        - time_of_day: Hora del dia (cada 10 min)
        - avg_bikes_weekday: Promedio de bicicletas disponibles en dias entre semana
        - std_bikes_weekday: Desviacion estandar en dias entre semana
        - min_bikes_weekday: Minimo observado en dias entre semana
        - max_bikes_weekday: Maximo observado en dias entre semana
        - sample_count_weekday: Numero de observaciones en dias entre semana
        - avg_bikes_weekend: Promedio de bicicletas disponibles en fin de semana
        - std_bikes_weekend: Desviacion estandar en fin de semana
        - min_bikes_weekend: Minimo observado en fin de semana
        - max_bikes_weekend: Maximo observado en fin de semana
        - sample_count_weekend: Numero de observaciones en fin de semana
    """
    try:
        df = await history_service.get_average(station_code)

        if df is None:
            raise HTTPException(
                status_code=404,
                detail=f"No se encontraron datos para la estacion {station_code}",
            )

        return _df_to_parquet_response(df, f"{station_code}_average_weekly.parquet")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al obtener average para {station_code}: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno: {e}")


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    responses={
        429: {"model": ErrorResponse, "description": "Demasiadas peticiones"},
        500: {"model": ErrorResponse, "description": "Error interno"},
    },
)
async def submit_feedback(request: Request, feedback: FeedbackInput) -> FeedbackResponse:
    """
    Recibe feedback de usuarios.

    Limites:
    - Maximo 5 peticiones por minuto por IP
    - Texto limitado a 250 caracteres

    Args:
        request: Request object para obtener IP del cliente
        feedback: Datos de feedback con thumb (valoracion) y text (comentario)

    Returns:
        Confirmacion de que el feedback fue guardado.
    """
    # Rate limiting por IP
    client_ip = request.client.host if request.client else "unknown"
    current_time = time.time()
    
    # Limpiar requests antiguos
    feedback_rate_limit[client_ip] = [
        req_time for req_time in feedback_rate_limit[client_ip]
        if current_time - req_time < FEEDBACK_WINDOW_SECONDS
    ]
    
    # Verificar limite
    if len(feedback_rate_limit[client_ip]) >= FEEDBACK_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Demasiadas peticiones. Maximo {FEEDBACK_MAX_REQUESTS} por minuto.",
        )
    
    # Registrar esta peticion
    feedback_rate_limit[client_ip].append(current_time)
    
    try:
        now = datetime.now(CDMX_TZ)
        feedback_service.save_feedback(thumb=feedback.thumb, text=feedback.text)

        return FeedbackResponse(
            message="Feedback recibido correctamente",
            timestamp=now,
        )

    except Exception as e:
        logger.error(f"Error al guardar feedback: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno: {e}")
