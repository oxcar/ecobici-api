"""
Servicio para gestionar feedback de usuarios.

Guarda feedback en formato parquet organizado por fecha.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import polars as pl

from app.config import get_settings

logger = logging.getLogger(__name__)

# Timezone de Ciudad de Mexico
CDMX_TZ = ZoneInfo("America/Mexico_City")


class FeedbackService:
    """Servicio para gestionar feedback de usuarios."""

    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def feedback_dir(self) -> Path:
        """Directorio de feedback."""
        return self._settings.data_path / "feedback"

    def save_feedback(self, thumb: Optional[str], text: Optional[str]) -> None:
        """
        Guarda feedback del usuario en parquet diario.

        Parametros
        ----------
        thumb : str | None
            Valoracion con pulgar (por ejemplo: "up", "down")
        text : str | None
            Comentario del usuario
        """
        now = datetime.now(CDMX_TZ)
        
        # Crear registro de feedback
        record = {
            "timestamp": now,
            "thumb": thumb,
            "text": text,
        }

        df_new = pl.DataFrame([record])

        # Determinar archivo del dia
        year = now.strftime("%Y")
        month = now.strftime("%m")
        date_str = now.strftime("%Y%m%d")

        # Crear directorio
        output_dir = self.feedback_dir / f"year={year}" / f"month={month}"
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / f"feedback_{date_str}.parquet"

        # Si existe, concatenar con datos existentes
        if output_file.exists():
            df_existing = pl.read_parquet(output_file)
            df_combined = pl.concat([df_existing, df_new])
            df_combined.write_parquet(output_file, compression="snappy")
        else:
            df_new.write_parquet(output_file, compression="snappy")

        logger.info(f"Feedback guardado: thumb={thumb}, text_length={len(text) if text else 0}")


# Instancia singleton del servicio
feedback_service = FeedbackService()
