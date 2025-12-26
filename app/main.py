"""
Aplicacion principal FastAPI para prediccion de disponibilidad de bicicletas Ecobici.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

import pytz
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.services.collector import gbfs_collector
from app.services.history import history_service
from app.services.predictor import predictor_service
from app.services.scheduler import shutdown_scheduler, start_scheduler
from app.services.statistics import StatisticsMiddleware, statistics_service


class CDMXFormatter(logging.Formatter):
    """Formatter que muestra timestamps en timezone de Ciudad de Mexico."""
    
    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        self.tz = pytz.timezone("America/Mexico_City")
    
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, self.tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S")


# Configurar logging con timezone CDMX
handler = logging.StreamHandler()
handler.setFormatter(CDMXFormatter(
    fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
))
logging.basicConfig(
    level=logging.INFO,
    handlers=[handler],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Contexto de ciclo de vida de la aplicacion.
    Carga los modelos al iniciar y los libera al cerrar.
    """
    # Startup
    logger.info("Iniciando aplicacion...")
    settings = get_settings()

    # Limpiar cache obsoleto
    history_service.cleanup_cache()
    logger.info("Cache de historial limpiado")

    logger.info(f"Cargando modelos desde: {settings.models_path}")
    if predictor_service.load_models():
        logger.info("Modelos cargados correctamente")
    else:
        logger.warning("No se pudieron cargar todos los modelos")

    # Inicializar servicio de estadisticas
    statistics_service.initialize(settings.statistics_path)
    await statistics_service.start_background_flush()
    logger.info(f"Servicio de estadisticas iniciado. Ruta: {settings.statistics_path}")

    # Inicializar cliente HTTP del colector GBFS si esta habilitado
    logger.info(f"Configuracion collector: enabled={settings.gbfs_collector_enabled}")
    if settings.gbfs_collector_enabled:
        try:
            await gbfs_collector.start()
            logger.info(f"Cliente HTTP del colector GBFS inicializado. Ruta: {settings.gbfs_snapshots_path}")
        except Exception as e:
            logger.error(f"Error al iniciar colector GBFS: {e}", exc_info=True)
    else:
        logger.info("Colector GBFS deshabilitado por configuracion")

    # Iniciar scheduler de tareas programadas
    start_scheduler()
    logger.info("Scheduler de tareas programadas iniciado")

    yield

    # Shutdown
    logger.info("Cerrando aplicacion...")

    # Detener scheduler
    shutdown_scheduler()
    logger.info("Scheduler detenido")

    # Detener colector GBFS si esta habilitado
    if settings.gbfs_collector_enabled:
        await gbfs_collector.stop()
        logger.info("Colector GBFS detenido")

    await statistics_service.stop_background_flush()
    logger.info("Servicio de estadisticas detenido")


def create_app() -> FastAPI:
    """Crea y configura la aplicacion FastAPI."""
    settings = get_settings()

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=settings.api_description,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
    )

    # Configurar CORS - solo permitir peticiones desde dominios autorizados
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # Middleware de estadisticas
    app.add_middleware(StatisticsMiddleware)

    # Incluir rutas
    app.include_router(router, prefix="/api/v1")

    # Ruta raiz
    @app.get("/")
    async def root() -> dict:
        """Ruta raiz con informacion basica."""
        return {
            "name": settings.api_title,
            "version": settings.api_version,
            "docs": "/docs",
        }

    return app


# Crear instancia de la aplicacion
app = create_app()
