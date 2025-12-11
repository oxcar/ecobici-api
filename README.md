# API de Prediccion Ecobici

API FastAPI para servir predicciones de disponibilidad de bicicletas del sistema Ecobici CDMX con recoleccion automatica de datos GBFS y analisis historico.

## Descripcion

Esta API proporciona:
- Predicciones de disponibilidad de bicicletas para 20, 40 y 60 minutos usando modelos XGBoost y LSTM
- Recoleccion automatica de datos GBFS cada minuto sincronizada al cambio de minuto
- Analisis historico con datos agregados cada 10 minutos
- Estadisticas de promedios por dia de semana

## Estructura del Proyecto

```
ecobici-api/
├── app/
│   ├── main.py                  # Aplicacion FastAPI con ciclo de vida
│   ├── config.py                # Configuracion y variables de entorno
│   ├── api/
│   │   └── routes.py            # Endpoints de la API
│   ├── services/
│   │   ├── collector.py         # Recolector GBFS (captura cada minuto)
│   │   ├── gbfs.py              # Cliente GBFS (datos en tiempo real)
│   │   ├── history.py           # Servicio de historico con cache
│   │   ├── lags.py              # Servicio de lags historicos
│   │   ├── predictor.py         # Servicio de prediccion (XGBoost + LSTM)
│   │   ├── statistics.py        # Servicio de estadisticas
│   │   └── weather.py           # Cliente Open-Meteo (clima)
│   └── models/
│       └── schemas.py           # Esquemas Pydantic
├── data/
│   ├── gbfs/                    # Datos GBFS particionado por fecha
│   │   └── year=YYYY/month=MM/
│   ├── models/                  # Modelos entrenados
│   │   ├── xgboost/             # Modelos XGBoost (m1)
│   │   └── lstm/                # Modelos LSTM (m2)
│   ├── cache/                   # Cache de consultas
│   └── statistics/              # Estadisticas de uso de la API
├── tests/                       # Tests
├── .github/workflows/
│   └── docker-build.yml         # CI/CD con GitHub Actions
├── docker-compose.yml           # Configuracion para produccion
├── Dockerfile
└── pyproject.toml
```

## Uso

### Desarrollo local

```bash
# Instalar dependencias con uv
uv sync

# Ejecutar servidor con recarga automatica
uv run --package api uvicorn app.main:app --reload --port 8000 --host 0.0.0.0
```

### Docker

```bash
# Construir imagen
docker build -t ecobici-api .

# Ejecutar con docker-compose
docker-compose up -d

# Ver logs
docker-compose logs -f
```

## Endpoints

### POST /api/v1/predict/{station_code}

Obtiene predicciones para una estacion especifica.

**Parametros:**
- `station_code`: Codigo de la estacion (ej: "001", "123")

**Cuerpo de la solicitud:**
```json
{
  "temperature_2m": 18.5,
  "rain": 0.0,
  "surface_pressure": 1013.25,
  "cloud_cover": 25.0,
  "wind_speed_10m": 5.0,
  "relative_humidity_2m": 65.0,
  "model": "m1"
}
```

**Respuesta:**
```json
{
  "station_code": "001",
  "timestamp": "2025-12-11T10:30:00-06:00",
  "current_bikes": 10,
  "capacity": 20,
  "predictions": {
    "bikes_20min": 8,
    "bikes_40min": 7,
    "bikes_60min": 6
  },
  "weather": {
    "temperature_2m": 18.5,
    "rain": 0.0,
    "surface_pressure": 1013.25,
    "cloud_cover": 25.0,
    "wind_speed_10m": 5.0,
    "relative_humidity_2m": 65.0
  }
}
```

**Modelos disponibles:**
- `m1`: XGBoost (por defecto) - Modelos gradient boosting rapidos y precisos
- `m2`: LSTM - Redes neuronales recurrentes para capturar patrones temporales

### GET /api/v1/history/{station_code}/yesterday

Obtiene historial del dia anterior (datos cada 10 minutos). Retorna archivo parquet.

**Columnas del archivo:**
- `snapshot_time`: Marca de tiempo
- `capacity`: Capacidad de la estacion
- `bikes_available`: Bicicletas disponibles
- `bikes_disabled`: Bicicletas deshabilitadas
- `docks_available`: Espacios disponibles
- `docks_disabled`: Espacios deshabilitados

### GET /api/v1/history/{station_code}/today

Obtiene historial del dia actual (datos cada 10 minutos, cache de 10 min). Retorna archivo parquet con la misma estructura que `/yesterday`.

### GET /api/v1/history/{station_code}/average

Obtiene promedios de disponibilidad de los ultimos 30 dias (cache de 24h). Retorna archivo parquet con estadisticas agregadas por hora del dia.

**Columnas del archivo:**
- `time_of_day`: Hora del dia (cada 10 minutos)
- `avg_bikes`: Promedio de bicicletas disponibles
- `std_bikes`: Desviacion estandar
- `min_bikes`: Minimo observado
- `max_bikes`: Maximo observado
- `sample_count`: Numero de observaciones

### GET /api/v1/history/{station_code}/average/{weekday}

Obtiene promedios para un dia de semana especifico.

**Parametros:**
- `weekday`: Dia de la semana (`monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`, `sunday`)

Retorna la misma estructura que `/average` pero filtrado por el dia especificado.

### GET /api/v1/health

Verifica el estado del servicio.

**Respuesta:**
```json
{
  "status": "healthy",
  "timestamp": "2025-12-11T10:30:00-06:00",
  "models_loaded": true,
  "gbfs_available": true
}
```

## Recolector GBFS

El servicio incluye un recolector automatico que:
- Captura datos de estaciones cada minuto sincronizado al segundo 0
- Guarda en formato Parquet particionado por fecha (hora de CDMX)
- Incluye 3 reintentos con intervalo de 5 segundos en caso de error
- Almacena: disponibilidad, estado, coordenadas, capacidad, ultima actualizacion

**Estructura de archivos:**
```
data/gbfs/year=2025/month=12/gbfs_20251211.parquet
```

**Columnas almacenadas:**
- `snapshot_time`: Marca de tiempo en UTC
- `station_id`: ID unico de la estacion
- `station_code`: Codigo corto (ej: "001")
- `name`: Nombre de la estacion
- `capacity`: Capacidad total
- `latitude`, `longitude`: Coordenadas geograficas
- `bikes_available`, `bikes_disabled`: Bicicletas disponibles y deshabilitadas
- `docks_available`, `docks_disabled`: Espacios disponibles y deshabilitados
- `is_installed`, `is_renting`, `is_returning`: Estados de la estacion
- `last_reported`: Ultima actualizacion de la estacion

## Variables de Entorno

| Variable                 | Descripcion                         | Valor por defecto            |
| ------------------------ | ----------------------------------- | ---------------------------- |
| `LOG_LEVEL`              | Nivel de registro de logs           | `INFO`                       |
| `GBFS_BASE_URL`          | URL base del feed GBFS              | (Ecobici CDMX)               |
| `GBFS_TIMEOUT`           | Timeout para peticiones GBFS (seg)  | `10.0`                       |
| `GBFS_COLLECTOR_ENABLED` | Activar recolector automatico       | `true`                       |
| `OPEN_METEO_BASE_URL`    | URL base de Open-Meteo              | `https://api.open-meteo.com` |
| `OPEN_METEO_TIMEOUT`     | Timeout para peticiones clima (seg) | `10.0`                       |

## Despliegue

### GitHub Actions

El proyecto incluye CI/CD automatico que:
- Construye imagen Docker en cada push a `main`
- Publica a GitHub Container Registry (ghcr.io)
- Usa cache de Docker para builds rapidos

### Docker Compose

```yaml
version: '3.8'
services:
  api:
    image: ghcr.io/oxcar/ecobici-api:latest
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

## Desarrollo

### Requisitos

- Python 3.11+
- uv (gestor de paquetes)

### Tests

```bash
uv run pytest
```

### Linting

```bash
uv run ruff check .
uv run ruff format .
```

## Arquitectura

### Estrategia de Zonas Horarias

- **Almacenamiento**: Siempre UTC para consistencia
- **Particionado**: Usa hora de CDMX para nombres de archivo
- **Promedios**: Convierte a hora de CDMX para calcular patrones diarios
- **API**: Timestamps en UTC con zona horaria

### Estrategia de Cache

- **Hoy**: TTL de 10 minutos (datos cambian durante el dia)
- **Ayer**: Cache permanente (datos inmutables)
- **Promedios**: TTL de 24 horas (actualizacion diaria)
- **Limpieza**: Limpieza automatica al iniciar la aplicacion
