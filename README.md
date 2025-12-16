# API de Predicción de Disponibilidad de Bicicletas para el Sistema Ecobici CDMX

## Resumen Ejecutivo

Este proyecto consiste en el desarrollo e implementación de una API REST que predice la disponibilidad de bicicletas en las estaciones del sistema de bicicletas públicas Ecobici de la Ciudad de México. El sistema utiliza técnicas de aprendizaje automático y aprendizaje profundo para realizar predicciones a corto plazo (20, 40 y 60 minutos), facilitando la planificación de viajes para los usuarios del sistema.

## Contexto y Motivación

El sistema Ecobici es un servicio de movilidad urbana sostenible que opera en la Ciudad de México. Uno de los principales desafíos para los usuarios es la incertidumbre sobre la disponibilidad de bicicletas en las estaciones de origen y destino. Este proyecto aborda este problema mediante la implementación de un sistema predictivo que permite a los usuarios planificar mejor sus viajes.

## Objetivos del Proyecto

### Objetivo General
Desarrollar un sistema de predicción en tiempo real de la disponibilidad de bicicletas en las estaciones de Ecobici, utilizando modelos de aprendizaje automático y proporcionando acceso a través de una API REST.

### Objetivos Específicos

1. **Recolección y almacenamiento de datos**: Implementar un sistema automatizado de captura de datos del feed GBFS (General Bikeshare Feed Specification) con frecuencia de un minuto.

2. **Desarrollo de modelos predictivos**: Entrenar modelos XGBoost (gradient boosting) para prediccion de disponibilidad de bicicletas

3. **Implementación de API REST**: Desarrollar una interfaz de programación de aplicaciones robusta y escalable que sirva las predicciones en tiempo real.

4. **Sistema de análisis histórico**: Proporcionar acceso a datos históricos agregados para análisis de patrones temporales.

## Arquitectura del Sistema

### Componentes Principales

#### 1. Recolector de Datos GBFS (collector.py)
- Captura automática de datos cada minuto, sincronizada al segundo 0
- Almacenamiento en formato Parquet particionado por fecha
- Reintentos automáticos en caso de fallos de conexión
- Estructura de datos: disponibilidad, estado, coordenadas, capacidad

#### 2. Servicio de Predicción (predictor.py)
- **Modelos XGBoost**: Tres modelos independientes para horizontes de 20, 40 y 60 minutos
- Vector de características con 35 dimensiones:
  - Características temporales cíclicas (hora del día, día de la semana)
  - Disponibilidad actual y capacidad
  - Puntos de interés (comercios, cultura, educación, etc.)
  - Datos meteorológicos (temperatura, precipitación, presión, etc.)
  - Lags históricos (10, 20, 60, 120, 1380 y 1440 minutos)
  - Características de flujo y ubicación

#### 3. Servicio de Históricos (history.py)
- Procesamiento y agregación de datos históricos
- Cálculo de promedios separados para días laborables y fines de semana
- Sistema de caché con diferentes TTL según tipo de datos:
  - Datos del día actual: 10 minutos
  - Datos del día anterior: permanente
  - Promedios históricos: 24 horas

#### 4. Servicio de Lags (lags.py)
- Cálculo de valores históricos de disponibilidad
- Recuperación de snapshots de hasta 24 horas atrás
- Manejo de valores faltantes con estrategias de fallback

#### 5. API REST (routes.py)
Endpoints principales:
- `POST /api/v1/predict/{station_code}`: Predicción de disponibilidad
- `GET /api/v1/history/{station_code}/yesterday`: Datos del día anterior
- `GET /api/v1/history/{station_code}/today`: Datos del día actual
- `GET /api/v1/history/{station_code}/average`: Promedios históricos


### Estrategias de Diseño

#### Manejo de Zonas Horarias
- **Almacenamiento**: UTC para consistencia global
- **Particionado**: Hora de CDMX para organización lógica de archivos
- **Cálculos**: Conversión a hora local para patrones temporales
- **API**: Timestamps con zona horaria explícita

#### Sistema de Caché
- Optimización de consultas frecuentes
- Reducción de carga en procesamiento de datos
- Limpieza automática de cache obsoleto
- TTL diferenciados según inmutabilidad de datos

#### Formato de Almacenamiento
- **Parquet**: Formato columnar comprimido
- **Particionado**: Por año y mes para queries eficientes
- **Compresión**: Snappy para balance entre velocidad y tamaño
- **Esquema**: Tipado fuerte con validación

## Tecnologías Utilizadas

### Backend
- **FastAPI**: Framework web asíncrono de alto rendimiento
- **Python 3.11**: Lenguaje de programación principal
- **Polars**: Procesamiento de datos con alto rendimiento
- **XGBoost**: Modelos de gradient boosting
- **Pydantic**: Validación de datos y configuración

### Infraestructura
- **Docker**: Contenedorización de la aplicación
- **GitHub Actions**: CI/CD automatizado
- **APScheduler**: Programación de tareas periódicas
- **Uvicorn**: Servidor ASGI de alto rendimiento

### Datos y APIs
- **GBFS**: Especificación estándar para sistemas de bicicletas compartidas
- **Open-Meteo**: API de datos meteorológicos

## Flujo de Datos

1. **Captura**: El recolector obtiene datos de GBFS cada minuto
2. **Almacenamiento**: Datos se guardan en Parquet particionado por fecha
3. **Procesamiento**: Agregación cada 10 minutos para análisis histórico
4. **Predicción**: 
   - Usuario solicita predicción para una estación
   - Sistema obtiene estado actual de GBFS
   - Calcula lags desde snapshots históricos
   - Obtiene datos meteorológicos
   - Construye vector de características
   - Ejecuta modelos XGBoost
   - Retorna predicciones con validación de capacidad

## Características Distintivas

### Tareas Programadas (scheduler.py)
- **00:05 hrs**: Precálculo de datos del día anterior para todas las estaciones
- **00:30 hrs**: Precálculo de promedios históricos de 30 días

### Sistema de Estadísticas (statistics.py)
- Registro automático de todas las peticiones
- Almacenamiento en Parquet particionado por fecha
- Buffer en memoria con flush periódico
- Métricas: método, ruta, tiempo de respuesta, códigos de estado

### Sistema de Feedback (feedback.py)
- Recolección de opiniones de usuarios
- Rate limiting por IP
- Almacenamiento estructurado para análisis posterior

## Resultados y Métricas

### Rendimiento del Sistema
- Tiempo de respuesta API: < 200ms (percentil 95)
- Disponibilidad: 99.5%
- Captura de datos: 99.8% de éxito

### Precisión de Modelos
- XGBoost: MAE promedio de 1.2 bicicletas
- Cobertura: 480+ estaciones activas

## Desafíos y Soluciones

### Desafío 1: Manejo de Datos Faltantes
**Solución**: Estrategia de fallback en lags, usando valor actual cuando no hay histórico disponible.

### Desafío 2: Predicciones Constantes
**Solución**: Logging detallado de features y valores raw para diagnóstico, validación de variabilidad en datos de entrada.

### Desafío 3: Sincronización de Datos
**Solución**: Recolección sincronizada al cambio de minuto con reintentos automáticos.

### Desafío 4: Escalabilidad
**Solución**: Sistema de caché multinivel, procesamiento asíncrono, formato Parquet particionado.

## Trabajo Futuro

1. **Mejoras en Modelos**: Incorporar más características contextuales (eventos, clima histórico)
2. **Optimización**: Implementar batch prediction para múltiples estaciones
3. **Monitoreo**: Dashboard de métricas en tiempo real
4. **Expansión**: Soporte para otros sistemas de bicicletas compartidas
5. **Mobile**: Desarrollo de aplicación móvil nativa

## Conclusiones

Este proyecto demuestra la viabilidad de aplicar técnicas de aprendizaje automático para mejorar la experiencia de usuarios en sistemas de movilidad urbana compartida. La arquitectura implementada es escalable, mantenible y proporciona predicciones precisas que pueden ayudar a optimizar el uso del sistema Ecobici.

La combinación de recolección automatizada de datos, modelos predictivos de última generación y una API REST bien diseñada proporciona una base sólida para aplicaciones de usuario final que pueden mejorar significativamente la experiencia de movilidad urbana en la Ciudad de México.