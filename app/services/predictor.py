"""
Servicio de prediccion con modelos entrenados.

Soporta dos tipos de modelos:
- m1: XGBoost (modelos tradicionales de ML)
- m2: LSTM (modelos de deep learning)
"""

import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import joblib

from app.config import get_settings

logger = logging.getLogger(__name__)

ModelType = Literal["m1", "m2"]


class PredictorService:
    """Servicio para realizar predicciones de disponibilidad de bicicletas."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.models_path = self.settings.models_path
        self._xgboost_models: dict[str, Any] = {}  # m1
        self._lstm_model: Any = None  # m2
        self._lstm_scaler: Any = None
        self._lstm_config: dict[str, Any] = {}
        self._models_loaded = False

    def load_models(self) -> bool:
        """
        Carga los modelos de prediccion (XGBoost y LSTM).

        Returns:
            True si al menos un tipo de modelo se cargo correctamente.
        """
        xgboost_loaded = self._load_xgboost_models()
        lstm_loaded = self._load_lstm_model()

        self._models_loaded = xgboost_loaded or lstm_loaded
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

    def _load_lstm_model(self) -> bool:
        """Carga el modelo LSTM (m2)."""
        lstm_path = self.models_path / "lstm"

        try:
            model_path = lstm_path / "model.pth"
            config_path = lstm_path / "model_config.pkl"
            scaler_path = lstm_path / "scaler.pkl"

            if not all(p.exists() for p in [model_path, config_path, scaler_path]):
                logger.warning(f"Archivos LSTM incompletos en {lstm_path}")
                return False

            # Cargar configuracion y scaler
            self._lstm_config = joblib.load(config_path)
            self._lstm_scaler = joblib.load(scaler_path)

            # Cargar modelo PyTorch (lazy import para evitar dependencia si no se usa)
            try:
                import torch

                # Reconstruir modelo desde config
                self._lstm_model = self._build_lstm_model(self._lstm_config)
                
                # Cargar checkpoint (puede ser state_dict o checkpoint completo)
                checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
                
                # Si es un checkpoint completo, extraer model_state_dict
                if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
                    self._lstm_model.load_state_dict(checkpoint["model_state_dict"])
                else:
                    self._lstm_model.load_state_dict(checkpoint)
                
                self._lstm_model.eval()
                logger.info("Modelo LSTM cargado correctamente")
                return True

            except ImportError:
                logger.warning("PyTorch no instalado, modelo LSTM no disponible")
                return False

        except Exception as e:
            logger.error(f"Error al cargar modelo LSTM: {e}")
            return False

    def _build_lstm_model(self, config: dict[str, Any]) -> Any:
        """Construye el modelo LSTM desde la configuracion."""
        import torch
        import torch.nn as nn

        class LSTMModel(nn.Module):
            def __init__(self, input_size: int, hidden_size: int, num_layers: int, output_size: int, dropout: float = 0.2):
                super().__init__()
                self.hidden_size = hidden_size
                self.num_layers = num_layers

                self.lstm = nn.LSTM(
                    input_size=input_size,
                    hidden_size=hidden_size,
                    num_layers=num_layers,
                    batch_first=True,
                    dropout=dropout if num_layers > 1 else 0,
                )
                # Dos capas fully connected
                self.fc1 = nn.Linear(hidden_size, hidden_size // 2)
                self.fc2 = nn.Linear(hidden_size // 2, output_size)
                self.relu = nn.ReLU()
                self.dropout = nn.Dropout(dropout)

            def forward(self, x):
                lstm_out, _ = self.lstm(x)
                out = self.fc1(lstm_out[:, -1, :])
                out = self.relu(out)
                out = self.dropout(out)
                out = self.fc2(out)
                return out

        return LSTMModel(
            input_size=config.get("input_size", 35),
            hidden_size=config.get("hidden_size", 128),
            num_layers=config.get("num_layers", 2),
            output_size=config.get("output_size", 3),
            dropout=config.get("dropout", 0.2),
        )

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

        return features

    def predict(
        self,
        station_data: dict[str, Any],
        weather_data: dict[str, float],
        lags: dict[str, int | None],
        timestamp: datetime | None = None,
        is_holiday: bool = False,
        model_type: ModelType = "m1",
    ) -> dict[str, int]:
        """
        Realiza predicciones para los tres horizontes.

        Args:
            station_data: Datos de la estacion
            weather_data: Datos meteorologicos
            lags: Lags historicos
            timestamp: Timestamp de la prediccion
            is_holiday: Si es dia festivo
            model_type: Tipo de modelo a usar ("m1"=XGBoost, "m2"=LSTM)

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

        if model_type == "m2" and self._lstm_model is not None:
            return self._predict_lstm(features, capacity)
        else:
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

        for horizon in ["20", "40", "60"]:
            if horizon in self._xgboost_models:
                try:
                    pred = self._xgboost_models[horizon].predict(X)[0]
                    pred_clamped = max(0, min(int(round(pred)), capacity))
                    predictions[f"bikes_{horizon}min"] = pred_clamped
                except Exception as e:
                    logger.error(f"Error en prediccion XGBoost {horizon}min: {e}")
                    predictions[f"bikes_{horizon}min"] = int(
                        station_data.get("num_bikes_available", 0)
                    )
            else:
                predictions[f"bikes_{horizon}min"] = int(
                    station_data.get("num_bikes_available", 0)
                )

        return predictions

    def _predict_lstm(self, features: list[float], capacity: int) -> dict[str, int]:
        """Realiza prediccion con modelo LSTM (m2)."""
        import numpy as np
        import torch

        try:
            # Escalar features
            features_array = np.array(features).reshape(1, -1)
            features_scaled = self._lstm_scaler.transform(features_array)

            # Preparar input para LSTM (batch, seq_len, features)
            # Usamos seq_len=1 para prediccion en tiempo real
            X = torch.FloatTensor(features_scaled).unsqueeze(1)

            # Prediccion
            with torch.no_grad():
                output = self._lstm_model(X)
                preds = output.numpy()[0]  # [pred_20, pred_40, pred_60]

            # Clampear predicciones
            predictions = {
                "bikes_20min": max(0, min(int(round(preds[0])), capacity)),
                "bikes_40min": max(0, min(int(round(preds[1])), capacity)),
                "bikes_60min": max(0, min(int(round(preds[2])), capacity)),
            }

            return predictions

        except Exception as e:
            logger.error(f"Error en prediccion LSTM: {e}")
            # Fallback: retornar valor actual (ultimo conocido de features)
            current_bikes = int(features[0])  # num_bikes_available es el primer feature
            return {
                "bikes_20min": current_bikes,
                "bikes_40min": current_bikes,
                "bikes_60min": current_bikes,
            }

    def is_model_available(self, model_type: ModelType) -> bool:
        """Verifica si un tipo de modelo esta disponible."""
        if model_type == "m1":
            return len(self._xgboost_models) > 0
        elif model_type == "m2":
            return self._lstm_model is not None
        return False


# Instancia singleton del servicio
predictor_service = PredictorService()
