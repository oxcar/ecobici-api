"""
Servicio de tareas programadas para precalcular datos historicos.

Ejecuta tareas a medianoche para precalcular:
- Datos del dia anterior (00:05 hrs)
- Promedios historicos de 2 meses (00:30 hrs)
"""

import logging
from datetime import datetime
from pathlib import Path

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.gbfs import gbfs_service
from app.services.history import history_service

logger = logging.getLogger(__name__)

# Instancia del scheduler
scheduler = AsyncIOScheduler()


async def precalculate_yesterday_data() -> None:
    """
    Precalcula los datos historicos del dia anterior para todas las estaciones activas.
    
    Esta tarea se ejecuta automaticamente a las 00:05 hrs todos los dias.
    Procesa cada estacion y guarda el resultado en cache para respuestas rapidas.
    """
    try:
        logger.info("Iniciando precalculo de datos del dia anterior")
        start_time = datetime.now()
        
        # Obtener todas las estaciones activas desde GBFS
        stations = await gbfs_service.get_all_stations()
        active_stations = [
            s for s in stations 
            if s.get("num_bikes_available", 0) >= 0  # Todas las estaciones con datos
        ]
        
        logger.info(f"Procesando {len(active_stations)} estaciones activas")
        
        # Precalcular datos para cada estacion
        success_count = 0
        error_count = 0
        
        for station in active_stations:
            station_code = station.get("station_code")
            if not station_code:
                continue
                
            try:
                # Obtener datos de yesterday y forzar recalculo
                cache_dir = history_service.cache_dir / "history"
                # Buscar archivos de cache con este station_code
                for cache_file in cache_dir.glob(f"*/{station_code}.parquet"):
                    if cache_file.exists() and "today" not in str(cache_file):
                        cache_file.unlink()
                        logger.debug(f"Cache eliminado: {cache_file}")
                
                # Calcular y guardar en cache
                result = await history_service.get_yesterday(station_code)
                if result:
                    success_count += 1
                    logger.debug(f"Precalculo exitoso: {station_code}")
                else:
                    logger.debug(f"No hay datos para: {station_code}")
                
            except Exception as e:
                error_count += 1
                logger.error(f"Error precalculando datos para estacion {station_code}: {e}")
        
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Precalculo completado en {elapsed:.2f}s - "
            f"Exitosos: {success_count}, Errores: {error_count}"
        )
        
    except Exception as e:
        logger.error(f"Error en precalculo de datos del dia anterior: {e}")


async def precalculate_averages() -> None:
    """
    Precalcula los promedios historicos (ultimos 2 meses) para todas las estaciones activas.
    
    Esta tarea se ejecuta automaticamente a las 00:30 hrs todos los dias.
    Calcula estadisticas separadas para dias entre semana y fin de semana.
    """
    try:
        logger.info("Iniciando precalculo de promedios historicos")
        start_time = datetime.now()
        
        # Obtener todas las estaciones activas desde GBFS
        stations = await gbfs_service.get_all_stations()
        active_stations = [
            s for s in stations 
            if s.get("num_bikes_available", 0) >= 0  # Todas las estaciones con datos
        ]
        
        logger.info(f"Procesando promedios para {len(active_stations)} estaciones activas")
        
        # Precalcular promedios para cada estacion
        success_count = 0
        error_count = 0
        
        for station in active_stations:
            station_code = station.get("station_code")
            if not station_code:
                continue
                
            try:
                # Forzar recalculo eliminando cache existente de averages
                today_str = datetime.now().strftime("%Y_%m_%d")
                cache_file = (
                    history_service.cache_dir / "averages" / today_str / 
                    f"{station_code}_weekly.parquet"
                )
                if cache_file.exists():
                    cache_file.unlink()
                    logger.debug(f"Cache de averages eliminado: {cache_file}")
                
                # Calcular y guardar en cache
                result = await history_service.get_average(station_code)
                if result is not None:
                    success_count += 1
                    logger.debug(f"Promedios calculados: {station_code}")
                else:
                    logger.debug(f"No hay datos suficientes para: {station_code}")
                
            except Exception as e:
                error_count += 1
                logger.error(f"Error precalculando promedios para estacion {station_code}: {e}")
        
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Precalculo de promedios completado en {elapsed:.2f}s - "
            f"Exitosos: {success_count}, Errores: {error_count}"
        )
        
    except Exception as e:
        logger.error(f"Error en precalculo de promedios historicos: {e}")


def start_scheduler() -> None:
    """
    Inicia el scheduler de tareas programadas.
    
    Configura las siguientes tareas:
    - 00:05 hrs: Precalcular datos del dia anterior
    - 00:30 hrs: Precalcular promedios historicos
    """
    mexico_tz = pytz.timezone('America/Mexico_City')
    
    # Programar tarea de yesterday a las 01:00 hrs todos los dias
    scheduler.add_job(
        precalculate_yesterday_data,
        CronTrigger(hour=1, minute=0, timezone=mexico_tz),
        id="precalculate_yesterday",
        name="Precalcular datos del dia anterior",
        replace_existing=True,
    )
    
    # Programar tarea de averages a las 01:30 hrs todos los dias
    scheduler.add_job(
        precalculate_averages,
        CronTrigger(hour=1, minute=30, timezone=mexico_tz),
        id="precalculate_averages",
        name="Precalcular promedios historicos",
        replace_existing=True,
    )
    
    scheduler.start()
    logger.info("Scheduler iniciado con zona horaria America/Mexico_City - Tareas: 00:05 (yesterday), 00:30 (averages)")


def shutdown_scheduler() -> None:
    """
    Detiene el scheduler de forma segura.
    """
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler detenido")
