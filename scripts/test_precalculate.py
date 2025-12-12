#!/usr/bin/env python3
"""
Script para probar las funciones de precalculo sin esperar al scheduler.

Este script ejecuta manualmente las tareas de precalculo que normalmente
se ejecutan a medianoche, permitiendo probarlas en cualquier momento.

Uso:
    uv run scripts/test_precalculate.py
    
    # O con el entorno virtual activado:
    python scripts/test_precalculate.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Agregar directorio raiz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.scheduler import precalculate_averages, precalculate_yesterday_data

# Configurar logging para ver la salida
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """
    Ejecuta las funciones de precalculo para probar.
    """
    print("=" * 70)
    print("PRUEBA DE FUNCIONES DE PRECALCULO")
    print("=" * 70)
    print()
    
    # Probar precalculo de datos de ayer
    print("1. PRECALCULO DE DATOS DEL DIA ANTERIOR")
    print("-" * 70)
    try:
        await precalculate_yesterday_data()
        print("✓ Precalculo de ayer completado exitosamente")
    except Exception as e:
        print(f"✗ Error en precalculo de ayer: {e}")
        logger.exception("Error detallado:")
    
    print()
    print("-" * 70)
    print()
    
    # Probar precalculo de promedios
    print("2. PRECALCULO DE PROMEDIOS HISTORICOS (2 MESES)")
    print("-" * 70)
    try:
        await precalculate_averages()
        print("✓ Precalculo de promedios completado exitosamente")
    except Exception as e:
        print(f"✗ Error en precalculo de promedios: {e}")
        logger.exception("Error detallado:")
    
    print()
    print("=" * 70)
    print("PRUEBA COMPLETADA")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
