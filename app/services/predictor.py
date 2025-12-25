"""
Servicio de prediccion con modelos XGBoost.

Utiliza modelos XGBoost para prediccion en tres horizontes temporales (20, 40, 60 min).
Carga features desde parquets enriquecidos, calcula ocupacion desde snapshots GBFS,
y detecta horarios fuera de operacion (5:00-00:30).
"""

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import pytz
import joblib

from app.config import get_settings

logger = logging.getLogger(__name__)

CDMX_TZ = pytz.timezone("America/Mexico_City")


class PredictorService:
    """Servicio para realizar predicciones de disponibilidad de bicicletas con XGBoost."""

    # Codigos de salida
    SUCCESS = 0
    STATION_NOT_FOUND = 1
    INSUFFICIENT_DATA = 2
    MODEL_NOT_LOADED = 3
    INVALID_FEATURES = 4

    # Orden exacto de las 42 features
    FEATURE_COLS = [
        # Ocupacion actual y lags
        "ocu",
        "ocu_lag_1",
        "ocu_lag_2",
        "ocu_lag_6",
        "ocu_lag_12",
        "ocu_lag_138",
        "ocu_lag_144",
        # Features de tendencia
        "ocu_trend_1",
        "ocu_trend_2",
        "ocu_trend_6",
        "ocu_trend_12",
        # Temporales ciclicas
        "time_sin",
        "time_cos",
        "day_sin",
        "day_cos",
        "is_weekend",
        "is_holiday",
        # Capacidad y estado operativo
        "capacity",
        "is_operating",
        # POIs cercanos
        "commerce_pois_300m",
        "finance_pois_300m",
        "culture_pois_300m",
        "education_pois_300m",
        "sport_recreation_pois_300m",
        "hotels_pois_300m",
        "food_pois_300m",
        "health_pois_300m",
        "drink_pois_300m",
        # Transporte publico
        "transit_nearest_station_m",
        "transit_stations_300m",
        # Demografia
        "ids_population_300m",
        "ids_300m",
        # Ubicacion
        "utm_x",
        "utm_y",
        # Flujo de estacion
        "station_netflow_rate",
        "station_turnover_rate",
        # Meteorologia
        "temperature_2m",
        "rain",
        "surface_pressure",
        "cloud_cover",
        "wind_speed_10m",
        "relative_humidity_2m",
    ]

    def __init__(self) -> None:
        self.settings = get_settings()
        self.models_path = self.settings.models_path
        self.gbfs_path = self.settings.gbfs_snapshots_path
        self._xgboost_models: dict[str, Any] = {}
        self._models_loaded = False
        self.holidays_df: Optional[pd.DataFrame] = None
        self.stations_enriched: Optional[pd.DataFrame] = None
        self.station_activity: Optional[pd.DataFrame] = None

    def load_models(self) -> bool:
        """
        Carga los modelos XGBoost y archivos de features.

        Returns:
            True si los modelos se cargaron correctamente.
        """
        try:
            # Cargar modelos XGBoost
            model_files = {
                "20": "model_20min.pkl",
                "40": "model_40min.pkl",
                "60": "model_60min.pkl",
            }

            xgboost_path = self.models_path / "xgboost"
            loaded_count = 0

            for horizon, filename in model_files.items():
                model_path = xgboost_path / filename
                if model_path.exists():
                    self._xgboost_models[horizon] = joblib.load(model_path)
                    logger.info(f"Modelo XGBoost {filename} cargado")
                    loaded_count += 1
                else:
                    logger.warning(f"Modelo XGBoost no encontrado: {model_path}")

            if loaded_count == 0:
                logger.error("No se pudo cargar ningun modelo XGBoost")
                return False

            # Cargar holidays
            holidays_path = self.models_path / "features" / "holidays.csv"
            if holidays_path.exists():
                self.holidays_df = pd.read_csv(holidays_path)
                self.holidays_df["date"] = pd.to_datetime(self.holidays_df["date"])
                logger.info(f"Holidays cargados: {len(self.holidays_df)} registros")
            else:
                logger.warning(f"Archivo de holidays no encontrado: {holidays_path}")
                self.holidays_df = pd.DataFrame(columns=["date"])

            # Cargar estaciones enriquecidas
            enriched_path = self.models_path / "features" / "1_stations_enriched.parquet"
            if enriched_path.exists():
                self.stations_enriched = pd.read_parquet(enriched_path)
                if "station_code" in self.stations_enriched.columns:
                    self.stations_enriched.set_index("station_code", inplace=True)
                logger.info(f"Estaciones enriquecidas cargadas: {len(self.stations_enriched)} estaciones")
            else:
                logger.warning(f"Archivo de estaciones enriquecidas no encontrado: {enriched_path}")
                self.stations_enriched = pd.DataFrame()

            # Cargar actividad de estaciones
            activity_path = self.models_path / "features" / "2_stations_activity_features.parquet"
            if activity_path.exists():
                self.station_activity = pd.read_parquet(activity_path)
                if not isinstance(self.station_activity.index, pd.MultiIndex):
                    if all(col in self.station_activity.columns for col in ["station_code", "weekday", "hour"]):
                        self.station_activity.set_index(["station_code", "weekday", "hour"], inplace=True)
                logger.info(f"Actividad de estaciones cargada: {len(self.station_activity)} registros")
            else:
                logger.warning(f"Archivo de actividad no encontrado: {activity_path}")
                self.station_activity = pd.DataFrame()

            self._models_loaded = loaded_count > 0
            return self._models_loaded

        except Exception as e:
            logger.error(f"Error al cargar modelos y features: {e}")
            return False

    @property
    def is_loaded(self) -> bool:
        """Verifica si los modelos están cargados."""
        return self._models_loaded

    @lru_cache(maxsize=10)
    def _load_parquet_cached(self, file_path: str) -> pd.DataFrame:
        """Cache LRU para parquets GBFS cargados recientemente."""
        return pd.read_parquet(file_path)

    def _load_gbfs_data(
        self, station_code: str, timestamp_utc: datetime
    ) -> tuple[Optional[dict], int]:
        """
        Carga datos GBFS y calcula ocupación y lags.

        Args:
            station_code: Código de estación
            timestamp_utc: Timestamp UTC

        Returns:
            Tupla (diccionario con ocu y lags, código de salida)
        """
        try:
            # Asegurar que timestamp_utc esté realmente en UTC
            if timestamp_utc.tzinfo != timezone.utc:
                timestamp_utc = timestamp_utc.astimezone(timezone.utc)
            
            timestamp_cdmx = timestamp_utc.astimezone(CDMX_TZ)
            
            # Determinar archivos parquet necesarios
            current_date = timestamp_cdmx.date()
            previous_date = (timestamp_cdmx - timedelta(days=1)).date()
            
            parquet_files = []
            for date in [current_date, previous_date]:
                parquet_path = (
                    self.gbfs_path
                    / f"year={date.year}"
                    / f"month={date.month:02d}"
                    / f"gbfs_{date.strftime('%Y%m%d')}.parquet"
                )
                if parquet_path.exists():
                    parquet_files.append(str(parquet_path))
            
            if not parquet_files:
                logger.warning(f"No se encontraron parquets GBFS para {station_code}")
                return None, self.INSUFFICIENT_DATA
            
            # Leer parquets con cache
            dfs = []
            for file_path in parquet_files:
                try:
                    df = self._load_parquet_cached(file_path)
                    df = df[df["station_code"] == station_code]
                    if not df.empty:
                        dfs.append(df)
                except Exception as e:
                    logger.warning(f"Error leyendo {file_path}: {e}")
            
            if not dfs:
                logger.warning(f"Estación {station_code} no encontrada en parquets")
                return None, self.STATION_NOT_FOUND
            
            df = pd.concat(dfs, ignore_index=True)
            df = df.sort_values("snapshot_time")
            
            # Asegurar que snapshot_time tenga timezone UTC
            if df["snapshot_time"].dt.tz is None:
                df["snapshot_time"] = pd.to_datetime(df["snapshot_time"], utc=True)
            
            # Calcular ocupación
            df["ocu"] = df["bikes_available"] / df["capacity"]
            
            # Buscar snapshots con tolerancia de ±5 minutos
            tolerance = pd.Timedelta("5min")
            lag_minutes = [0, 10, 20, 60, 120, 1380, 1440]
            lag_names = ["ocu", "ocu_lag_1", "ocu_lag_2", "ocu_lag_6", "ocu_lag_12", "ocu_lag_138", "ocu_lag_144"]
            
            result = {}
            capacity = None
            
            for lag_min, lag_name in zip(lag_minutes, lag_names):
                # Convertir target_time a UTC para comparar con df
                target_time_cdmx = timestamp_cdmx - timedelta(minutes=lag_min)
                target_time_utc = target_time_cdmx.astimezone(timezone.utc)
                
                mask = (df["snapshot_time"] >= target_time_utc - tolerance) & (df["snapshot_time"] <= target_time_utc + tolerance)
                matches = df[mask]
                
                if not matches.empty:
                    closest = matches.iloc[(matches["snapshot_time"] - target_time_utc).abs().argmin()]
                    result[lag_name] = float(closest["ocu"])
                    if capacity is None:
                        capacity = int(closest["capacity"])
                else:
                    logger.debug(f"No se encontro snapshot para {lag_name} en {station_code} (target UTC: {target_time_utc}, df range: {df['snapshot_time'].min()} - {df['snapshot_time'].max()})")
                    result[lag_name] = None
            
            # Verificar datos críticos - relajar requisitos si tiene snapshot actual
            if result.get("ocu") is None:
                logger.warning(f"No se encontró ocupación actual para {station_code} (timestamp CDMX: {timestamp_cdmx}, timestamp UTC: {timestamp_utc}, df range: {df['snapshot_time'].min()} - {df['snapshot_time'].max()})")
                return None, self.INSUFFICIENT_DATA
            
            # Permitir prediccion incluso si faltan algunos lags (usar forward-fill)
            missing_lags = [name for name in lag_names[1:] if result.get(name) is None]
            if missing_lags:
                logger.debug(f"Aplicando forward-fill para lags faltantes en {station_code}: {missing_lags}")
                # Forward-fill: usar el valor mas reciente disponible
                for i, lag_name in enumerate(lag_names):
                    if result.get(lag_name) is None and i > 0:
                        # Buscar el lag anterior mas cercano que tenga valor
                        for j in range(i - 1, -1, -1):
                            if result.get(lag_names[j]) is not None:
                                result[lag_name] = result[lag_names[j]]
                                break
                
                # Verificar que ahora todos tengan valor
                still_missing = [name for name in lag_names if result.get(name) is None]
                if still_missing:
                    logger.warning(f"Lags criticos faltantes para {station_code} despues de forward-fill: {still_missing}")
                    return None, self.INSUFFICIENT_DATA
            
            result["capacity"] = capacity if capacity else 20
            return result, self.SUCCESS
            
        except Exception as e:
            logger.error(f"Error cargando datos GBFS para {station_code}: {e}")
            return None, self.INSUFFICIENT_DATA

    def _calculate_temporal_features(self, timestamp_cdmx: datetime) -> dict[str, float]:
        """
        Calcula features temporales ciclicas.

        Args:
            timestamp_cdmx: Timestamp en timezone CDMX

        Returns:
            Diccionario con features temporales
        """
        hour = timestamp_cdmx.hour
        minute = timestamp_cdmx.minute
        weekday = timestamp_cdmx.weekday()
        
        # Encoding ciclico de hora
        time_sin = np.sin(2 * np.pi * (hour + minute / 60) / 24)
        time_cos = np.cos(2 * np.pi * (hour + minute / 60) / 24)
        
        # Encoding ciclico de dia
        day_sin = np.sin(2 * np.pi * weekday / 7)
        day_cos = np.cos(2 * np.pi * weekday / 7)
        
        # Fin de semana
        is_weekend = 1 if weekday >= 5 else 0
        
        # Dia festivo
        date_only = timestamp_cdmx.date()
        is_holiday = 1 if date_only in self.holidays_df["date"].dt.date.values else 0
        
        # Sistema operativo (5:00-00:30)
        is_operating = 1 if (hour >= 5) or (hour == 0 and minute <= 30) else 0
        
        return {
            "time_sin": float(time_sin),
            "time_cos": float(time_cos),
            "day_sin": float(day_sin),
            "day_cos": float(day_cos),
            "is_weekend": float(is_weekend),
            "is_holiday": float(is_holiday),
            "is_operating": float(is_operating),
        }

    def _is_operating_at_time(self, timestamp_cdmx: datetime) -> bool:
        """Verifica si el sistema opera en el horario dado (5:00-00:30)."""
        hour = timestamp_cdmx.hour
        minute = timestamp_cdmx.minute
        return (hour >= 5) or (hour == 0 and minute <= 30)

    def _calculate_trends(self, ocu_dict: dict) -> tuple[Optional[dict], int]:
        """
        Calcula tendencias de ocupacion.

        Args:
            ocu_dict: Diccionario con ocupacion y lags

        Returns:
            Tupla (diccionario con tendencias, codigo de salida)
        """
        required_keys = ["ocu", "ocu_lag_1", "ocu_lag_2", "ocu_lag_6", "ocu_lag_12"]
        if not all(key in ocu_dict and ocu_dict[key] is not None for key in required_keys):
            return None, self.INSUFFICIENT_DATA
        
        trends = {
            "ocu_trend_1": float(ocu_dict["ocu"] - ocu_dict["ocu_lag_1"]),
            "ocu_trend_2": float(ocu_dict["ocu"] - ocu_dict["ocu_lag_2"]),
            "ocu_trend_6": float(ocu_dict["ocu"] - ocu_dict["ocu_lag_6"]),
            "ocu_trend_12": float(ocu_dict["ocu"] - ocu_dict["ocu_lag_12"]),
        }
        
        return trends, self.SUCCESS

    def _assemble_features(
        self,
        ocu_dict: dict,
        temporal_dict: dict,
        trends_dict: dict,
        station_enriched: pd.Series,
        station_activity: pd.Series,
        weather_params: dict,
        capacity_fallback: int,
    ) -> tuple[Optional[np.ndarray], int]:
        """
        Ensambla el vector de 42 features en orden especifico.

        Args:
            ocu_dict: Ocupacion y lags
            temporal_dict: Features temporales
            trends_dict: Tendencias
            station_enriched: Features de estacion enriquecida
            station_activity: Features de actividad
            weather_params: Parametros meteorologicos
            capacity_fallback: Capacidad desde GBFS

        Returns:
            Tupla (array NumPy (1, 42), codigo de salida)
        """
        try:
            # Obtener capacity
            capacity = station_enriched.get("capacity", capacity_fallback) if not station_enriched.empty else capacity_fallback
            
            # Construir features en orden de FEATURE_COLS
            features = []
            
            # Ocupacion y lags (7)
            features.append(float(ocu_dict["ocu"]))
            features.append(float(ocu_dict["ocu_lag_1"]))
            features.append(float(ocu_dict["ocu_lag_2"]))
            features.append(float(ocu_dict["ocu_lag_6"]))
            features.append(float(ocu_dict["ocu_lag_12"]))
            features.append(float(ocu_dict["ocu_lag_138"]))
            features.append(float(ocu_dict["ocu_lag_144"]))
            
            # Tendencias (4)
            features.append(float(trends_dict["ocu_trend_1"]))
            features.append(float(trends_dict["ocu_trend_2"]))
            features.append(float(trends_dict["ocu_trend_6"]))
            features.append(float(trends_dict["ocu_trend_12"]))
            
            # Temporales (6)
            features.append(float(temporal_dict["time_sin"]))
            features.append(float(temporal_dict["time_cos"]))
            features.append(float(temporal_dict["day_sin"]))
            features.append(float(temporal_dict["day_cos"]))
            features.append(float(temporal_dict["is_weekend"]))
            features.append(float(temporal_dict["is_holiday"]))
            
            # Capacity e is_operating (2)
            features.append(float(capacity))
            features.append(float(temporal_dict["is_operating"]))
            
            # POIs (9)
            features.append(float(station_enriched.get("commerce_pois_300m", 0)))
            features.append(float(station_enriched.get("finance_pois_300m", 0)))
            features.append(float(station_enriched.get("culture_pois_300m", 0)))
            features.append(float(station_enriched.get("education_pois_300m", 0)))
            features.append(float(station_enriched.get("sport_recreation_pois_300m", 0)))
            features.append(float(station_enriched.get("hotels_pois_300m", 0)))
            features.append(float(station_enriched.get("food_pois_300m", 0)))
            features.append(float(station_enriched.get("health_pois_300m", 0)))
            features.append(float(station_enriched.get("drink_pois_300m", 0)))
            
            # Transit (2)
            features.append(float(station_enriched.get("transit_nearest_station_m", 500.0)))
            features.append(float(station_enriched.get("transit_stations_300m", 1)))
            
            # IDS (2)
            features.append(float(station_enriched.get("ids_population_300m", 10000)))
            features.append(float(station_enriched.get("ids_300m", 0.5)))
            
            # UTM (2)
            features.append(float(station_enriched.get("utm_x", 485000.0)))
            features.append(float(station_enriched.get("utm_y", 2150000.0)))
            
            # Actividad (2)
            features.append(float(station_activity.get("station_netflow_rate", 0.0)))
            features.append(float(station_activity.get("station_turnover_rate", 0.0)))
            
            # Meteorologia (6)
            features.append(float(weather_params["temperature_2m"]))
            features.append(float(weather_params["rain"]))
            features.append(float(weather_params["surface_pressure"]))
            features.append(float(weather_params["cloud_cover"]))
            features.append(float(weather_params["wind_speed_10m"]))
            features.append(float(weather_params["relative_humidity_2m"]))
            
            # Validar longitud
            if len(features) != 42:
                logger.error(f"Vector de features tiene longitud incorrecta: {len(features)} != 42")
                return None, self.INVALID_FEATURES
            
            # Validar ausencia de NaN
            X = np.array(features).reshape(1, 42)
            if np.isnan(X).any():
                logger.error("Vector de features contiene valores NaN")
                return None, self.INVALID_FEATURES
            
            return X, self.SUCCESS
            
        except Exception as e:
            logger.error(f"Error ensamblando features: {e}")
            return None, self.INVALID_FEATURES

    def predict(
        self,
        station_data: dict[str, Any],
        weather_data: dict[str, float],
        lags: dict[str, int | None],
        timestamp: datetime | None = None,
        is_holiday: bool = False,
        model_type: str = "m1",
    ) -> dict[str, int]:
        """
        Realiza predicciones para los tres horizontes usando XGBoost.

        Mantiene compatibilidad con interfaz anterior para routes.py.

        Args:
            station_data: Datos de la estacion desde GBFS
            weather_data: Datos meteorologicos
            lags: Lags historicos (no usado, se cargan desde parquet)
            timestamp: Timestamp de la prediccion
            is_holiday: Si es dia festivo (no usado, se calcula desde CSV)
            model_type: Tipo de modelo (solo "m1" soportado)

        Returns:
            Diccionario con predicciones para 20, 40 y 60 minutos.
        """
        if not self._models_loaded:
            raise RuntimeError("Los modelos no estan cargados")
        
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        station_code = station_data.get("station_code")
        if not station_code:
            raise ValueError("station_code no encontrado en station_data")
        
        # Llamar nueva implementacion
        result, code = self.predict_xgboost(
            station_code=station_code,
            temperature_2m=weather_data["temperature_2m"],
            rain=weather_data["rain"],
            surface_pressure=weather_data["surface_pressure"],
            cloud_cover=weather_data["cloud_cover"],
            wind_speed_10m=weather_data["wind_speed_10m"],
            relative_humidity_2m=weather_data["relative_humidity_2m"],
            timestamp_utc=timestamp,
        )
        
        if code != self.SUCCESS or result is None:
            # Fallback a valores actuales
            current_bikes = int(station_data.get("bikes_available", 0))
            return {
                "bikes_20min": current_bikes,
                "bikes_40min": current_bikes,
                "bikes_60min": current_bikes,
            }
        
        # Convertir formato de respuesta
        predictions = {}
        for pred in result["predictions"]:
            horizon = pred["horizon_minutes"]
            predictions[f"bikes_{horizon}min"] = pred["bikes_predicted"]
        
        return predictions

    def predict_xgboost(
        self,
        station_code: str,
        temperature_2m: float,
        rain: float,
        surface_pressure: float,
        cloud_cover: float,
        wind_speed_10m: float,
        relative_humidity_2m: float,
        timestamp_utc: Optional[datetime] = None,
    ) -> tuple[Optional[dict], int]:
        """
        Realiza prediccion con modelos XGBoost usando nueva arquitectura.

        Args:
            station_code: Codigo de estacion
            temperature_2m: Temperatura a 2m (C)
            rain: Lluvia (mm)
            surface_pressure: Presion superficial (hPa)
            cloud_cover: Cobertura de nubes (%)
            wind_speed_10m: Velocidad del viento (km/h)
            relative_humidity_2m: Humedad relativa (%)
            timestamp_utc: Timestamp UTC (opcional)

        Returns:
            Tupla (diccionario con resultados, codigo de salida)
        """
        if not self._models_loaded:
            return None, self.MODEL_NOT_LOADED
        
        if timestamp_utc is None:
            timestamp_utc = datetime.now(timezone.utc)
        
        timestamp_cdmx = timestamp_utc.astimezone(CDMX_TZ)
        
        # Cargar datos GBFS
        ocu_dict, code = self._load_gbfs_data(station_code, timestamp_utc)
        if code != self.SUCCESS:
            return None, code
        
        # Extraer features de estacion enriquecida
        try:
            station_enriched = self.stations_enriched.loc[station_code] if not self.stations_enriched.empty else pd.Series()
        except KeyError:
            logger.warning(f"Estacion {station_code} no encontrada en features enriquecidas")
            station_enriched = pd.Series()
        
        # Extraer features de actividad
        weekday = timestamp_cdmx.weekday()
        hour = timestamp_cdmx.hour
        try:
            if not self.station_activity.empty:
                station_activity = self.station_activity.loc[(station_code, weekday, hour)]
            else:
                station_activity = pd.Series({"station_netflow_rate": 0.0, "station_turnover_rate": 0.0})
        except KeyError:
            logger.debug(f"Sin datos de actividad para {station_code}, weekday={weekday}, hour={hour}")
            station_activity = pd.Series({"station_netflow_rate": 0.0, "station_turnover_rate": 0.0})
        
        # Calcular features temporales y tendencias
        temporal_dict = self._calculate_temporal_features(timestamp_cdmx)
        trends_dict, code = self._calculate_trends(ocu_dict)
        if code != self.SUCCESS:
            return None, code
        
        # Ensamblar features
        weather_params = {
            "temperature_2m": temperature_2m,
            "rain": rain,
            "surface_pressure": surface_pressure,
            "cloud_cover": cloud_cover,
            "wind_speed_10m": wind_speed_10m,
            "relative_humidity_2m": relative_humidity_2m,
        }
        
        X, code = self._assemble_features(
            ocu_dict=ocu_dict,
            temporal_dict=temporal_dict,
            trends_dict=trends_dict,
            station_enriched=station_enriched,
            station_activity=station_activity,
            weather_params=weather_params,
            capacity_fallback=ocu_dict["capacity"],
        )
        if code != self.SUCCESS:
            return None, code
        
        # Obtener ocupacion actual y capacity
        ocu_actual = ocu_dict["ocu"]
        capacity = ocu_dict["capacity"]
        
        # Realizar predicciones para cada horizonte
        predictions = []
        for horizon in [20, 40, 60]:
            future_timestamp = timestamp_cdmx + timedelta(minutes=horizon)
            
            # Verificar si esta en horario operativo
            if not self._is_operating_at_time(future_timestamp):
                predictions.append({
                    "timestamp_utc": future_timestamp.astimezone(timezone.utc).isoformat(),
                    "horizon_minutes": horizon,
                    "occupancy_predicted": 0.0,
                    "bikes_predicted": 0,
                })
                continue
            
            # Ejecutar modelo
            try:
                delta_pred = self._xgboost_models[str(horizon)].predict(X)[0]
                ocu_pred = np.clip(ocu_actual + delta_pred, 0, 1)
                bikes = int(np.round(ocu_pred * capacity))
                bikes = max(0, min(bikes, capacity))
                
                predictions.append({
                    "timestamp_utc": future_timestamp.astimezone(timezone.utc).isoformat(),
                    "horizon_minutes": horizon,
                    "occupancy_predicted": float(ocu_pred),
                    "bikes_predicted": bikes,
                })
            except Exception as e:
                logger.error(f"Error en prediccion {horizon}min: {e}")
                fallback_bikes = int(np.round(ocu_actual * capacity))
                fallback_bikes = max(0, min(fallback_bikes, capacity))
                predictions.append({
                    "timestamp_utc": future_timestamp.astimezone(timezone.utc).isoformat(),
                    "horizon_minutes": horizon,
                    "occupancy_predicted": float(ocu_actual),
                    "bikes_predicted": fallback_bikes,
                })
        
        # Construir respuesta
        current_bikes = int(np.round(ocu_actual * capacity))
        current_bikes = max(0, min(current_bikes, capacity))
        
        result = {
            "current_state": {
                "timestamp_utc": timestamp_utc.isoformat(),
                "occupancy": float(ocu_actual),
                "bikes_available": current_bikes,
                "capacity": capacity,
                "is_operating": bool(temporal_dict["is_operating"]),
            },
            "predictions": predictions,
        }
        
        return result, self.SUCCESS

    def is_model_available(self) -> bool:
        """Verifica si los modelos XGBoost estan disponibles."""
        return len(self._xgboost_models) > 0


# Instancia singleton del servicio
predictor_service = PredictorService()
