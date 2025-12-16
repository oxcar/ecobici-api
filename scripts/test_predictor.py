#!/usr/bin/env python3
"""
Script para probar el servicio de prediccion y diagnosticar problemas.

Uso:
    uv run scripts/test_predictor.py
    
    # O con el entorno virtual activado:
    python scripts/test_predictor.py
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Agregar directorio raiz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.predictor import predictor_service

# Configurar logging detallado
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Datos de prueba simulados
TEST_STATION_DATA = {
    "num_bikes_available": 10,
    "capacity": 20,
    "commerce_pois_300m": 15,
    "finance_pois_300m": 5,
    "culture_pois_300m": 2,
    "education_pois_300m": 3,
    "sport_recreation_pois_300m": 4,
    "hotels_pois_300m": 1,
    "food_pois_300m": 20,
    "health_pois_300m": 2,
    "drink_pois_300m": 8,
    "transit_nearest_station_m": 250.0,
    "transit_stations_300m": 2,
    "ids_population_300m": 12000,
    "ids_300m": 0.65,
    "utm_x": 486500.0,
    "utm_y": 2151000.0,
    "station_netflow": 0.15,
    "station_intensity": 0.75,
}

TEST_WEATHER_DATA = {
    "temperature_2m": 22.0,
    "rain": 0.0,
    "surface_pressure": 1015.0,
    "cloud_cover": 40.0,
    "wind_speed_10m": 8.0,
    "relative_humidity_2m": 55.0,
}

# Lags simulados con variedad
TEST_LAGS: dict[str, int | None] = {
    "num_bikes_available_lag_1": 11,
    "num_bikes_available_lag_2": 12,
    "num_bikes_available_lag_3": 10,
    "num_bikes_available_lag_6": 9,
    "num_bikes_available_lag_12": 8,
    "num_bikes_available_lag_144": 10,
}


def main() -> None:
    """
    Prueba el servicio de prediccion con datos simulados.
    """
    print("=" * 70)
    print("PRUEBA DEL SERVICIO DE PREDICCION")
    print("=" * 70)
    print()
    
    # Cargar modelos
    print("1. Cargando modelos...")
    success = predictor_service.load_models()
    
    if not success:
        print("ERROR: No se pudieron cargar los modelos")
        print(f"Ruta de modelos: {predictor_service.models_path}")
        return
    
    print(f"   Modelos cargados correctamente")
    print(f"   XGBoost disponible: {predictor_service.is_model_available()}")
    print()
    
    # Realizar prediccion con XGBoost
    if predictor_service.is_model_available():
        print("2. Prediccion con XGBoost...")
        print(f"   Bicicletas actuales: {TEST_STATION_DATA['num_bikes_available']}")
        print(f"   Capacidad: {TEST_STATION_DATA['capacity']}")
        print(f"   Lags: {TEST_LAGS}")
        print()
        
        try:
            predictions_m1 = predictor_service.predict(
                station_data=TEST_STATION_DATA,
                weather_data=TEST_WEATHER_DATA,
                lags=TEST_LAGS,
                timestamp=datetime.now(timezone.utc),
                is_holiday=False,
            )
            
            print("   Resultados XGBoost:")
            for horizon, value in predictions_m1.items():
                print(f"   - {horizon}: {value} bicicletas")
            
            # Verificar si son todos iguales
            values = list(predictions_m1.values())
            if len(set(values)) == 1:
                print()
                print("   ADVERTENCIA: Todos los horizontes tienen el mismo valor!")
                print("   Posibles causas:")
                print("   - Los modelos no estan entrenados correctamente")
                print("   - Las features no coinciden con el entrenamiento")
                print("   - Los lags son todos iguales o no se proporcionan")
                print("   - La capacidad es muy baja y el clamping limita las predicciones")
            else:
                print()
                print("   OK: Los horizontes tienen valores diferentes")
                
        except Exception as e:
            print(f"   ERROR en prediccion XGBoost: {e}")
            import traceback
            traceback.print_exc()
        print()
    else:
        print("2. XGBoost no esta disponible, omitiendo...")
        print()
    
    print()
    print("=" * 70)
    print("PRUEBA COMPLETADA")
    print("=" * 70)
    print()
    print("Revisa los logs DEBUG arriba para ver:")
    print("- Las features construidas (primeras 10 y ultimas 6)")
    print("- Los valores raw de prediccion antes de clampear")
    print("- Los valores finales despues de aplicar min/max con capacity")


if __name__ == "__main__":
    main()
