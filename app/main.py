"""
Aplicacion principal FastAPI para prediccion de disponibilidad de bicicletas Ecobici.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.services.collector import gbfs_collector
from app.services.history import history_service
from app.services.predictor import predictor_service
from app.services.statistics import StatisticsMiddleware, statistics_service

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
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

    # Iniciar colector GBFS si esta habilitado
    if settings.gbfs_collector_enabled:
        await gbfs_collector.start()
        logger.info(f"Colector GBFS iniciado. Ruta: {settings.gbfs_snapshots_path}")

    yield

    # Shutdown
    logger.info("Cerrando aplicacion...")

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
    )

    # Configurar CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # En produccion, especificar dominios permitidos
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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
            "health": "/api/v1/health",
        }

    return app


# Crear instancia de la aplicacion
app = create_app()
