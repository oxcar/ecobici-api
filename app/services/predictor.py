"""
Servicio de prediccion con modelos entrenados.

Utiliza modelos XGBoost para prediccion en tres horizontes temporales.
"""

import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from app.config import get_settings

logger = logging.getLogger(__name__)


class PredictorService:
    """Servicio para realizar predicciones de disponibilidad de bicicletas."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.models_path = self.settings.models_path
        self._xgboost_models: dict[str, Any] = {}
        self._models_loaded = False

    def load_models(self) -> bool:
        """
        Carga los modelos de prediccion XGBoost.

        Returns:
            True si los modelos se cargaron correctamente.
        """
        self._models_loaded = self._load_xgboost_models()
        return self._models_loaded

    def _load_xgboost_models(self) -> bool:
        """Carga los modelos XGBoost (m1)."""
        model_files = {
            "20": "model_20min.pkl",
            "40": "model_40min.pkl",
            "60": "model_60min.pkl",
        }

        xgboost_path = self.models_path / "xgboost"
        loaded_count = 0

        try:
            for horizon, filename in model_files.items():
                model_path = xgboost_path / filename
                if model_path.exists():
                    self._xgboost_models[horizon] = joblib.load(model_path)
                    logger.info(f"Modelo XGBoost {filename} cargado")
                    loaded_count += 1
                else:
                    logger.warning(f"Modelo XGBoost no encontrado: {model_path}")

            return loaded_count > 0

        except Exception as e:
            logger.error(f"Error al cargar modelos XGBoost: {e}")
            return False

    @property
    def is_loaded(self) -> bool:
        """Verifica si los modelos estan cargados."""
        return self._models_loaded

    def _calculate_temporal_features(self, dt: datetime) -> dict[str, float]:
        """
        Calcula las features temporales ciclicas.

        Args:
            dt: Datetime para calcular features

        Returns:
            Diccionario con features temporales.
        """
        # Convertir a timezone de Mexico si no tiene timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        hour = dt.hour
        minute = dt.minute
        weekday = dt.weekday()  # 0=Lunes, 6=Domingo

        # Calcular fraccion del dia (0-1)
        time_fraction = (hour * 60 + minute) / (24 * 60)

        # Calcular features ciclicas
        time_sin = math.sin(2 * math.pi * time_fraction)
        time_cos = math.cos(2 * math.pi * time_fraction)

        # Dia de la semana ciclico
        day_sin = math.sin(2 * math.pi * weekday / 7)
        day_cos = math.cos(2 * math.pi * weekday / 7)

        # Es fin de semana
        is_weekend = 1 if weekday >= 5 else 0

        return {
            "time_sin": time_sin,
            "time_cos": time_cos,
            "day_sin": day_sin,
            "day_cos": day_cos,
            "is_weekend": is_weekend,
        }

    def _build_feature_vector(
        self,
        station_data: dict[str, Any],
        weather_data: dict[str, float],
        lags: dict[str, int | None],
        timestamp: datetime,
        is_holiday: bool = False,
    ) -> list[float]:
        """
        Construye el vector de features para el modelo.

        El orden de las features debe coincidir con el entrenamiento:
        - num_bikes_available
        - capacity
        - time_sin, time_cos
        - day_sin, day_cos
        - is_weekend
        - Features de POIs (commerce, finance, culture, education, sport_recreation, hotels, food, health, drink)
        - transit_nearest_station_m, transit_stations_300m
        - ids_population_300m, ids_300m
        - utm_x, utm_y
        - station_netflow, station_intensity
        - Weather features
        - is_holiday
        - Lag features
        """
        temporal = self._calculate_temporal_features(timestamp)

        # Vector de features en el orden correcto
        features = [
            # Disponibilidad actual
            float(station_data.get("num_bikes_available", 0)),
            float(station_data.get("capacity", 20)),

            # Features temporales ciclicas
            temporal["time_sin"],
            temporal["time_cos"],
            temporal["day_sin"],
            temporal["day_cos"],
            temporal["is_weekend"],

            # POIs (valores por defecto si no disponibles)
            float(station_data.get("commerce_pois_300m", 0)),
            float(station_data.get("finance_pois_300m", 0)),
            float(station_data.get("culture_pois_300m", 0)),
            float(station_data.get("education_pois_300m", 0)),
            float(station_data.get("sport_recreation_pois_300m", 0)),
            float(station_data.get("hotels_pois_300m", 0)),
            float(station_data.get("food_pois_300m", 0)),
            float(station_data.get("health_pois_300m", 0)),
            float(station_data.get("drink_pois_300m", 0)),

            # Transito
            float(station_data.get("transit_nearest_station_m", 500.0)),
            float(station_data.get("transit_stations_300m", 1)),

            # IDS (indice de desarrollo social)
            float(station_data.get("ids_population_300m", 10000)),
            float(station_data.get("ids_300m", 0.5)),

            # Coordenadas UTM
            float(station_data.get("utm_x", 485000.0)),
            float(station_data.get("utm_y", 2150000.0)),

            # Flujo de estacion
            float(station_data.get("station_netflow", 0.0)),
            float(station_data.get("station_intensity", 0.0)),

            # Weather
            float(weather_data.get("temperature_2m", 20.0)),
            float(weather_data.get("rain", 0.0)),
            float(weather_data.get("surface_pressure", 1013.0)),
            float(weather_data.get("cloud_cover", 50.0)),
            float(weather_data.get("wind_speed_10m", 5.0)),
            float(weather_data.get("relative_humidity_2m", 50.0)),

            # Holiday
            float(1 if is_holiday else 0),

            # Lags
            float(lags.get("num_bikes_available_lag_1") or station_data.get("num_bikes_available", 0)),
            float(lags.get("num_bikes_available_lag_2") or station_data.get("num_bikes_available", 0)),
            float(lags.get("num_bikes_available_lag_3") or station_data.get("num_bikes_available", 0)),
            float(lags.get("num_bikes_available_lag_6") or station_data.get("num_bikes_available", 0)),
            float(lags.get("num_bikes_available_lag_12") or station_data.get("num_bikes_available", 0)),
            float(lags.get("num_bikes_available_lag_144") or station_data.get("num_bikes_available", 0)),
        ]
        
        # Log de debug para verificar variedad en features
        logger.debug(f"Features construidas - Lags: {features[-6:]}")
        logger.debug(f"Features completas (primeras 10): {features[:10]}")

        return features

    def predict(
        self,
        station_data: dict[str, Any],
        weather_data: dict[str, float],
        lags: dict[str, int | None],
        timestamp: datetime | None = None,
        is_holiday: bool = False,
    ) -> dict[str, int]:
        """
        Realiza predicciones para los tres horizontes usando XGBoost.

        Args:
            station_data: Datos de la estacion
            weather_data: Datos meteorologicos
            lags: Lags historicos
            timestamp: Timestamp de la prediccion
            is_holiday: Si es dia festivo

        Returns:
            Diccionario con predicciones para 20, 40 y 60 minutos.
        """
        if not self._models_loaded:
            raise RuntimeError("Los modelos no estan cargados")

        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        features = self._build_feature_vector(
            station_data=station_data,
            weather_data=weather_data,
            lags=lags,
            timestamp=timestamp,
            is_holiday=is_holiday,
        )

        capacity = int(station_data.get("capacity", 20))
        return self._predict_xgboost(features, capacity, station_data)

    def _predict_xgboost(
        self,
        features: list[float],
        capacity: int,
        station_data: dict[str, Any],
    ) -> dict[str, int]:
        """Realiza prediccion con modelos XGBoost (m1)."""
        X = [features]
        predictions = {}
        
        logger.debug(f"Prediccion XGBoost - Modelos disponibles: {list(self._xgboost_models.keys())}")
        logger.debug(f"Features (primeras 10): {features[:10]}")
        logger.debug(f"Features (ultimas 6 - lags): {features[-6:]}")

        for horizon in ["20", "40", "60"]:
            if horizon in self._xgboost_models:
                try:
                    pred = self._xgboost_models[horizon].predict(X)[0]
                    pred_clamped = max(0, min(int(round(pred)), capacity))
                    
                    logger.info(
                        f"Prediccion {horizon}min - Raw: {pred:.2f}, Clamped: {pred_clamped}, "
                        f"Capacity: {capacity}, Current: {station_data.get('num_bikes_available', 0)}"
                    )
                    
                    predictions[f"bikes_{horizon}min"] = pred_clamped
                except Exception as e:
                    logger.error(f"Error en prediccion XGBoost {horizon}min: {e}")
                    current = int(station_data.get("num_bikes_available", 0))
                    predictions[f"bikes_{horizon}min"] = current
                    logger.warning(f"Usando valor actual como fallback: {current}")
            else:
                logger.warning(f"Modelo XGBoost {horizon}min no disponible")
                predictions[f"bikes_{horizon}min"] = int(
                    station_data.get("num_bikes_available", 0)
                )

        return predictions

    def is_model_available(self) -> bool:
        """Verifica si los modelos XGBoost estan disponibles."""
        return len(self._xgboost_models) > 0


# Instancia singleton del servicio
predictor_service = PredictorService()
