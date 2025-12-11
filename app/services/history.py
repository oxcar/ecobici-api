"""
Servicio de historial y cache para datos de estaciones.

Gestiona la lectura de datos historicos desde parquet,
calculo de promedios y manejo de cache.
"""

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

import polars as pl
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.gbfs import gbfs_service

logger = logging.getLogger(__name__)

# Timezone de Ciudad de Mexico
CDMX_TZ = ZoneInfo("America/Mexico_City")

# Mapeo de nombres de dias en ingles
WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

WeekdayName = Literal[
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]


class HistoryService:
    """Servicio para gestionar historicos y cache de estaciones."""

    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def gbfs_data_dir(self) -> Path:
        """Directorio de datos GBFS."""
        return self._settings.gbfs_snapshots_path

    @property
    def cache_dir(self) -> Path:
        """Directorio base de cache."""
        return self._settings.data_path / "cache"

    def _get_parquet_path(self, date: datetime) -> Optional[Path]:
        """Obtiene la ruta del parquet para una fecha."""
        year = date.strftime("%Y")
        month = date.strftime("%m")
        date_str = date.strftime("%Y%m%d")

        path = self.gbfs_data_dir / f"year={year}" / f"month={month}" / f"gbfs_{date_str}.parquet"
        return path if path.exists() else None

    def _find_recent_parquet(self, days_back: int = 7) -> Optional[tuple[Path, str]]:
        """Busca el parquet mas reciente disponible."""
        for days_ago in range(1, days_back + 1):
            check_date = datetime.now(CDMX_TZ) - timedelta(days=days_ago)
            path = self._get_parquet_path(check_date)
            if path:
                date_str = check_date.strftime("%Y_%m_%d")
                return path, date_str
        return None

    async def _resolve_station_id(self, station_code: str) -> Optional[str]:
        """Resuelve station_code a station_id usando GBFS."""
        await gbfs_service._refresh_station_info()
        return gbfs_service._resolve_station_id(station_code)

    def _process_station_data(self, df: pl.DataFrame, station_id: str) -> Optional[pl.DataFrame]:
        """Filtra y procesa datos de una estacion."""
        df_station = df.filter(pl.col("station_id") == station_id)

        if df_station.is_empty():
            return None

        # Seleccionar columnas y ordenar
        df_result = df_station.select([
            pl.col("snapshot_time"),
            pl.col("capacity"),
            pl.col("bikes_available"),
            pl.col("bikes_disabled"),
            pl.col("docks_available"),
            pl.col("docks_disabled"),
        ]).sort("snapshot_time")

        # Rellenar valores nulos
        df_result = df_result.fill_null(0)

        # Agrupar en bloques de 10 minutos
        df_result = df_result.group_by_dynamic(
            "snapshot_time",
            every="10m",
        ).agg([
            pl.col("capacity").last(),
            pl.col("bikes_available").last(),
            pl.col("bikes_disabled").last(),
            pl.col("docks_available").last(),
            pl.col("docks_disabled").last(),
        ]).sort("snapshot_time")

        return df_result

    async def get_yesterday(self, station_code: str) -> Optional[tuple[pl.DataFrame, str]]:
        """
        Obtiene datos del dia anterior para una estacion.

        Retorna
        -------
        tuple[DataFrame, str] | None
            DataFrame con datos y fecha, o None si no hay datos
        """
        result = self._find_recent_parquet()
        if not result:
            return None

        parquet_path, date_str = result

        # Verificar cache
        cache_file = self.cache_dir / "history" / date_str / f"{station_code}.parquet"
        if cache_file.exists():
            logger.debug(f"Cache hit: yesterday {station_code} {date_str}")
            return pl.read_parquet(cache_file), date_str

        # Procesar datos
        station_id = await self._resolve_station_id(station_code)
        if not station_id:
            return None

        df = pl.read_parquet(parquet_path)
        df_result = self._process_station_data(df, station_id)

        if df_result is None:
            return None

        # Guardar en cache
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        df_result.write_parquet(cache_file, compression="snappy")
        logger.debug(f"Cache guardado: yesterday {station_code} {date_str}")

        return df_result, date_str

    async def get_today(self, station_code: str) -> Optional[tuple[pl.DataFrame, str]]:
        """
        Obtiene datos del dia actual para una estacion.

        Usa cache de 10 minutos.

        Retorna
        -------
        tuple[DataFrame, str] | None
            DataFrame con datos y fecha, o None si no hay datos
        """
        today = datetime.now(CDMX_TZ)
        date_str = today.strftime("%Y_%m_%d")

        parquet_path = self._get_parquet_path(today)
        if not parquet_path:
            return None

        # Verificar cache (TTL 10 minutos)
        cache_file = self.cache_dir / "history" / "today" / f"{station_code}.parquet"
        if cache_file.exists():
            cache_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if cache_age < timedelta(minutes=10):
                logger.debug(f"Cache hit: today {station_code}")
                return pl.read_parquet(cache_file), date_str

        # Procesar datos
        station_id = await self._resolve_station_id(station_code)
        if not station_id:
            return None

        df = pl.read_parquet(parquet_path)
        df_result = self._process_station_data(df, station_id)

        if df_result is None:
            return None

        # Guardar en cache
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        df_result.write_parquet(cache_file, compression="snappy")
        logger.debug(f"Cache guardado: today {station_code}")

        return df_result, date_str

    async def get_average(
        self,
        station_code: str,
        weekday: Optional[WeekdayName] = None,
    ) -> Optional[pl.DataFrame]:
        """
        Calcula promedios de disponibilidad para una estacion.

        Parametros
        ----------
        station_code : str
            Codigo de la estacion
        weekday : str | None
            Dia de la semana (monday, tuesday, etc.) o None para todos

        Retorna
        -------
        DataFrame | None
            DataFrame con promedios por hora, o None si no hay datos
        """
        today = datetime.now(CDMX_TZ)
        today_str = today.strftime("%Y_%m_%d")

        # Verificar cache (TTL 24 horas)
        cache_suffix = weekday if weekday else "all"
        cache_file = self.cache_dir / "averages" / today_str / f"{station_code}_{cache_suffix}.parquet"

        if cache_file.exists():
            logger.debug(f"Cache hit: average {station_code} {cache_suffix}")
            return pl.read_parquet(cache_file)

        # Obtener station_id
        station_id = await self._resolve_station_id(station_code)
        if not station_id:
            return None

        # Recolectar datos de los ultimos 30 dias
        all_data = []
        for days_ago in range(1, 31):
            check_date = today - timedelta(days=days_ago)

            # Filtrar por dia de semana si se especifica
            if weekday and check_date.weekday() != WEEKDAY_MAP[weekday]:
                continue

            parquet_path = self._get_parquet_path(check_date)
            if parquet_path:
                try:
                    df = pl.read_parquet(parquet_path)
                    df_station = df.filter(pl.col("station_id") == station_id)
                    if not df_station.is_empty():
                        all_data.append(df_station)
                except Exception as e:
                    logger.warning(f"Error al leer {parquet_path}: {e}")

        if not all_data:
            return None

        # Concatenar todos los datos
        df_all = pl.concat(all_data)

        # Convertir snapshot_time de UTC a hora de Mexico antes de extraer la hora del dia
        df_all = df_all.with_columns([
            pl.col("snapshot_time").dt.convert_time_zone("America/Mexico_City").dt.truncate("10m").dt.time().alias("time_of_day"),
            pl.col("bikes_available").cast(pl.Float64),
        ])

        # Calcular estadisticas por hora del dia
        df_avg = df_all.group_by("time_of_day").agg([
            pl.col("bikes_available").mean().round(1).alias("avg_bikes"),
            pl.col("bikes_available").std().round(1).alias("std_bikes"),
            pl.col("bikes_available").min().alias("min_bikes"),
            pl.col("bikes_available").max().alias("max_bikes"),
            pl.col("bikes_available").count().alias("sample_count"),
        ]).sort("time_of_day")

        # Guardar en cache
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        df_avg.write_parquet(cache_file, compression="snappy")
        logger.debug(f"Cache guardado: average {station_code} {cache_suffix}")

        return df_avg

    def cleanup_cache(self) -> None:
        """
        Limpia cache obsoleto.

        - Elimina cache de /today (datos del dia anterior)
        - Elimina cache de averages con fecha < hoy
        - Elimina cache de history con fecha < ayer - 1 dia
        """
        today = datetime.now(CDMX_TZ)
        today_str = today.strftime("%Y_%m_%d")
        yesterday = today - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y_%m_%d")

        # Limpiar cache de today
        today_cache = self.cache_dir / "history" / "today"
        if today_cache.exists():
            shutil.rmtree(today_cache)
            logger.info("Cache de today limpiado")

        # Limpiar cache de averages antiguos
        averages_dir = self.cache_dir / "averages"
        if averages_dir.exists():
            for subdir in averages_dir.iterdir():
                if subdir.is_dir() and subdir.name != today_str:
                    shutil.rmtree(subdir)
                    logger.info(f"Cache de averages {subdir.name} limpiado")

        # Limpiar cache de history antiguos (mantener solo ayer)
        history_dir = self.cache_dir / "history"
        if history_dir.exists():
            for subdir in history_dir.iterdir():
                if subdir.is_dir() and subdir.name not in [yesterday_str, "today"]:
                    shutil.rmtree(subdir)
                    logger.info(f"Cache de history {subdir.name} limpiado")


# Instancia singleton
history_service = HistoryService()
