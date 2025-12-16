"""
Servicio de estadisticas de la API.

Registra cada peticion a la API en archivos parquet organizados por fecha.
Estructura: data/statistics/year=YYYY/month=MM/YYYY_MM_DD.parquet
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

logger = logging.getLogger(__name__)

# Timezone de Ciudad de Mexico
CDMX_TZ = ZoneInfo("America/Mexico_City")


class StatisticsService:
    """Servicio para registrar estadisticas de la API en archivos parquet."""

    def __init__(self) -> None:
        """Inicializa el servicio de estadisticas."""
        self._buffer: list[dict[str, Any]] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_interval = 60  # Segundos entre flush automatico
        self._max_buffer_size = 100  # Maximo de registros antes de flush
        self._statistics_path: Path | None = None
        self._flush_task: asyncio.Task | None = None

    def initialize(self, statistics_path: Path) -> None:
        """
        Inicializa el servicio con la ruta de estadisticas.

        Args:
            statistics_path: Ruta base donde guardar los archivos parquet
        """
        self._statistics_path = statistics_path
        logger.info(f"Servicio de estadisticas inicializado. Ruta: {statistics_path}")

    async def start_background_flush(self) -> None:
        """Inicia la tarea de flush periodico en segundo plano."""
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._periodic_flush())
            logger.info("Tarea de flush periodico iniciada")

    async def stop_background_flush(self) -> None:
        """Detiene la tarea de flush periodico."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
            # Flush final antes de cerrar
            await self.flush()
            logger.info("Tarea de flush periodico detenida")

    async def _periodic_flush(self) -> None:
        """Tarea que hace flush periodico del buffer."""
        while True:
            try:
                await asyncio.sleep(self._flush_interval)
                await self.flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error en flush periodico: {e}")

    async def record(
        self,
        *,
        timestamp: datetime,
        method: str,
        path: str,
        status_code: int,
        response_time_ms: float,
        client_ip: str | None = None,
        user_agent: str | None = None,
        station_code: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        """
        Registra una peticion en el buffer.

        Args:
            timestamp: Momento de la peticion
            method: Metodo HTTP (GET, POST, etc.)
            path: Ruta de la peticion
            status_code: Codigo de respuesta HTTP
            response_time_ms: Tiempo de respuesta en milisegundos
            client_ip: IP del cliente
            user_agent: User-Agent del cliente
            station_code: Codigo de estacion (si aplica)
            error_detail: Detalle del error (si aplica)
        """
        record = {
            "timestamp": timestamp,
            "method": method,
            "path": path,
            "status_code": status_code,
            "response_time_ms": response_time_ms,
            "client_ip": client_ip,
            "user_agent": user_agent,
            "station_code": station_code,
            "error_detail": error_detail,
        }

        async with self._buffer_lock:
            self._buffer.append(record)

            # Flush si el buffer esta lleno
            if len(self._buffer) >= self._max_buffer_size:
                await self._flush_internal()

    async def flush(self) -> None:
        """Guarda el buffer actual en archivos parquet."""
        async with self._buffer_lock:
            await self._flush_internal()

    async def _flush_internal(self) -> None:
        """
        Implementacion interna de flush (debe llamarse con lock adquirido).

        Agrupa los registros por fecha y los guarda en archivos parquet separados.
        Si el archivo ya existe, se agregan los nuevos registros.
        """
        if not self._buffer:
            return

        if not self._statistics_path:
            logger.warning("Ruta de estadisticas no configurada, descartando buffer")
            self._buffer.clear()
            return

        try:
            # Crear DataFrame con los registros del buffer
            df = pl.DataFrame(self._buffer)

            # Agrupar por fecha
            df = df.with_columns(
                pl.col("timestamp").dt.date().alias("date")
            )

            # Procesar cada fecha por separado
            for date_value in df.get_column("date").unique().to_list():
                df_date = df.filter(pl.col("date") == date_value).drop("date")

                # Construir ruta del archivo
                year = date_value.strftime("%Y")
                month = date_value.strftime("%m")
                date_str = date_value.strftime("%Y_%m_%d")

                dir_path = self._statistics_path / f"year={year}" / f"month={month}"
                file_path = dir_path / f"{date_str}.parquet"

                # Crear directorio si no existe
                dir_path.mkdir(parents=True, exist_ok=True)

                # Si el archivo existe, leer y concatenar
                if file_path.exists():
                    try:
                        df_existing = pl.read_parquet(file_path)
                        df_date = pl.concat([df_existing, df_date])
                    except Exception as e:
                        logger.warning(f"Error al leer archivo existente {file_path}: {e}")

                # Guardar archivo
                df_date.write_parquet(file_path, compression="snappy")
                logger.debug(f"Estadisticas guardadas en {file_path} ({len(df_date)} registros)")

            # Limpiar buffer
            records_flushed = len(self._buffer)
            self._buffer.clear()
            logger.info(f"Flush completado: {records_flushed} registros guardados")

        except Exception as e:
            logger.error(f"Error al guardar estadisticas: {e}")
            # No limpiar buffer en caso de error para reintentar


# Instancia global del servicio
statistics_service = StatisticsService()


class StatisticsMiddleware(BaseHTTPMiddleware):
    """Middleware para registrar estadisticas de cada peticion."""

    # Rutas a excluir del registro
    EXCLUDED_PATHS = {"/", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Procesa la peticion y registra estadisticas.

        Args:
            request: Peticion HTTP
            call_next: Siguiente middleware/handler

        Returns:
            Respuesta HTTP
        """
        # Excluir ciertas rutas
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Registrar tiempo de inicio
        start_time = datetime.now(CDMX_TZ)

        # Procesar peticion
        response = await call_next(request)

        # Calcular tiempo de respuesta
        end_time = datetime.now(CDMX_TZ)
        response_time_ms = (end_time - start_time).total_seconds() * 1000

        # Extraer codigo de estacion de la ruta si existe
        station_code = None
        path_parts = request.url.path.strip("/").split("/")
        
        if "stations" in path_parts and len(path_parts) >= 2:
            station_index = path_parts.index("stations")
            if station_index + 1 < len(path_parts):
                station_code = str(path_parts[station_index + 1])
        elif "history" in path_parts and len(path_parts) >= 2:
            history_index = path_parts.index("history")
            if history_index + 1 < len(path_parts):
                station_code = str(path_parts[history_index + 1])
        elif "predict" in path_parts and len(path_parts) >= 2:
            predict_index = path_parts.index("predict")
            if predict_index + 1 < len(path_parts):
                station_code = str(path_parts[predict_index + 1])

        # Obtener IP del cliente
        client_ip = request.client.host if request.client else None

        # Obtener User-Agent
        user_agent = request.headers.get("user-agent")

        # Registrar estadistica
        await statistics_service.record(
            timestamp=start_time,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            response_time_ms=response_time_ms,
            client_ip=client_ip,
            user_agent=user_agent,
            station_code=station_code,
        )

        return response
