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

        # Rellenar huecos en la serie temporal con ceros
        if not df_result.is_empty():
            # Obtener rango completo de tiempos
            min_time = df_result["snapshot_time"].min()
            max_time = df_result["snapshot_time"].max()
            
            # Crear serie temporal completa con intervalos de 10 minutos
            full_range = pl.datetime_range(
                min_time,
                max_time,
                interval="10m",
                eager=True,
            ).alias("snapshot_time")
            
            # Crear DataFrame con el rango completo
            df_full = pl.DataFrame({"snapshot_time": full_range})
            
            # Hacer join y rellenar huecos con ceros
            df_result = df_full.join(df_result, on="snapshot_time", how="left")
            
            # Rellenar valores faltantes: capacity con el ultimo valor conocido, resto con 0
            df_result = df_result.with_columns([
                pl.col("capacity").forward_fill().fill_null(0),
                pl.col("bikes_available").fill_null(0),
                pl.col("bikes_disabled").fill_null(0),
                pl.col("docks_available").fill_null(0),
                pl.col("docks_disabled").fill_null(0),
            ])

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
    ) -> Optional[pl.DataFrame]:
        """
        Calcula promedios de disponibilidad para una estacion.
        
        Calcula promedios separados para dias entre semana (lunes-viernes)
        y fines de semana (sabado-domingo).

        Parametros
        ----------
        station_code : str
            Codigo de la estacion

        Retorna
        -------
        DataFrame | None
            DataFrame con promedios por hora del dia con columnas separadas
            para dias entre semana y fin de semana, o None si no hay datos
        """
        today = datetime.now(CDMX_TZ)
        today_str = today.strftime("%Y_%m_%d")

        # Verificar cache (TTL 24 horas)
        cache_file = self.cache_dir / "averages" / today_str / f"{station_code}_weekly.parquet"

        if cache_file.exists():
            logger.debug(f"Cache hit: average {station_code} weekly")
            return pl.read_parquet(cache_file)

        # Obtener station_id
        station_id = await self._resolve_station_id(station_code)
        if not station_id:
            return None

        # Recolectar datos de los ultimos 30 dias separando por tipo de dia
        weekday_data = []
        weekend_data = []
        
        for days_ago in range(1, 31):
            check_date = today - timedelta(days=days_ago)
            weekday_num = check_date.weekday()

            parquet_path = self._get_parquet_path(check_date)
            if parquet_path:
                try:
                    df = pl.read_parquet(parquet_path)
                    df_station = df.filter(pl.col("station_id") == station_id)
                    if not df_station.is_empty():
                        # Clasificar: lunes-viernes (0-4) = entre semana, sabado-domingo (5-6) = fin de semana
                        if weekday_num < 5:
                            weekday_data.append(df_station)
                        else:
                            weekend_data.append(df_station)
                except Exception as e:
                    logger.warning(f"Error al leer {parquet_path}: {e}")

        if not weekday_data and not weekend_data:
            return None

        # Procesar datos de dias entre semana
        df_weekday = None
        if weekday_data:
            df_weekday_concat = pl.concat(weekday_data)
            df_weekday_concat = df_weekday_concat.with_columns([
                pl.col("snapshot_time").dt.convert_time_zone("America/Mexico_City").dt.truncate("10m").dt.time().alias("time_of_day"),
                pl.col("bikes_available").cast(pl.Float64),
            ])
            df_weekday = df_weekday_concat.group_by("time_of_day").agg([
                pl.col("bikes_available").mean().round(1).alias("avg_bikes_weekday"),
                pl.col("bikes_available").std().round(1).alias("std_bikes_weekday"),
                pl.col("bikes_available").min().alias("min_bikes_weekday"),
                pl.col("bikes_available").max().alias("max_bikes_weekday"),
                pl.col("bikes_available").count().alias("sample_count_weekday"),
            ])

        # Procesar datos de fin de semana
        df_weekend = None
        if weekend_data:
            df_weekend_concat = pl.concat(weekend_data)
            df_weekend_concat = df_weekend_concat.with_columns([
                pl.col("snapshot_time").dt.convert_time_zone("America/Mexico_City").dt.truncate("10m").dt.time().alias("time_of_day"),
                pl.col("bikes_available").cast(pl.Float64),
            ])
            df_weekend = df_weekend_concat.group_by("time_of_day").agg([
                pl.col("bikes_available").mean().round(1).alias("avg_bikes_weekend"),
                pl.col("bikes_available").std().round(1).alias("std_bikes_weekend"),
                pl.col("bikes_available").min().alias("min_bikes_weekend"),
                pl.col("bikes_available").max().alias("max_bikes_weekend"),
                pl.col("bikes_available").count().alias("sample_count_weekend"),
            ])

        # Combinar ambos DataFrames mediante join por time_of_day
        if df_weekday is not None and df_weekend is not None:
            df_avg = df_weekday.join(df_weekend, on="time_of_day", how="outer").sort("time_of_day")
        elif df_weekday is not None:
            df_avg = df_weekday.sort("time_of_day")
        else:
            df_avg = df_weekend.sort("time_of_day")

        # Guardar en cache
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        df_avg.write_parquet(cache_file, compression="snappy")
        logger.debug(f"Cache guardado: average {station_code} weekly")

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
