# Imagen base con Python
FROM python:3.11-slim

# Variables de entorno
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivos de configuracion del proyecto
COPY pyproject.toml README.md ./

# Copiar codigo fuente (necesario para que hatchling construya el wheel)
COPY app/ ./app/

# Instalar PyTorch CPU-only desde indice especifico (reduce imagen de 4GB a 600MB)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Instalar dependencias de Python
RUN pip install --no-cache-dir .

# Crear directorio de datos (modelos se montan como volumen en produccion)
RUN mkdir -p ./data

# Puerto de la aplicacion
EXPOSE 8000

# Health check
# HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
#   CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Usuario no-root para seguridad
RUN useradd --create-home --shell /bin/bash appuser
RUN chown -R appuser:appuser /app
USER appuser

# Comando de inicio
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
