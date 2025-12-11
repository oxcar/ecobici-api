"""
Script para migrar archivos parquet legacy al nuevo esquema.

Esquema legacy:
- station_id, num_bikes_available, num_bikes_disabled, num_docks_available,
  num_docks_disabled, is_installed, is_renting, is_returning, last_reported,
  eightd_has_available_keys, is_charging, Snapshot_Time, month, year

Esquema nuevo:
- snapshot_time, station_id, station_code, name, capacity, latitude, longitude,
  bikes_available, bikes_disabled, docks_available, docks_disabled,
  is_installed, is_renting, is_returning, last_reported
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import polars as pl

# Zona horaria de Ciudad de Mexico
CDMX_TZ = ZoneInfo("America/Mexico_City")


def fetch_station_info() -> dict[str, dict]:
    """Obtiene informacion de estaciones desde GBFS."""
    print("Obteniendo informacion de estaciones desde GBFS...")
    url = "https://gbfs.mex.lyftbikes.com/gbfs/es/station_information.json"
    
    response = httpx.get(url, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    stations = {}
    for station in data.get("data", {}).get("stations", []):
        station_id = station.get("station_id")
        stations[station_id] = {
            "station_code": station.get("short_name"),
            "name": station.get("name", ""),
            "latitude": station.get("lat"),
            "longitude": station.get("lon"),
            "capacity": station.get("capacity", 0),
        }
    
    print(f"  Se encontraron {len(stations)} estaciones")
    return stations


def is_legacy_schema(df: pl.DataFrame) -> bool:
    """Detecta si el DataFrame tiene el esquema legacy."""
    columns = df.columns
    # El esquema legacy tiene Snapshot_Time (con mayusculas) y no tiene station_code
    return "Snapshot_Time" in columns and "station_code" not in columns


def migrate_parquet(file_path: Path, station_info: dict[str, dict]) -> bool:
    """
    Migra un archivo parquet del esquema legacy al nuevo.
    
    Retorna True si se migro, False si ya tenia el esquema correcto.
    """
    print(f"\nProcesando: {file_path.name}")
    
    # Leer archivo
    df = pl.read_parquet(file_path)
    
    # Verificar si necesita migracion
    if not is_legacy_schema(df):
        print(f"  Ya tiene el esquema correcto, saltando...")
        return False
    
    print(f"  Esquema legacy detectado, migrando {len(df)} registros...")
    
    # Crear listas para los nuevos datos
    records = []
    skipped = 0
    
    for row in df.iter_rows(named=True):
        station_id = row["station_id"]
        info = station_info.get(station_id)
        
        if info is None or info.get("station_code") is None:
            skipped += 1
            continue
        
        # Convertir Snapshot_Time: esta guardado como si fuera UTC pero es hora de Mexico
        # Primero lo interpretamos como hora de Mexico, luego convertimos a UTC
        snapshot_time = row["Snapshot_Time"]
        if isinstance(snapshot_time, datetime):
            if snapshot_time.tzinfo is None:
                # Sin timezone: asumir que es hora de Mexico
                snapshot_time = snapshot_time.replace(tzinfo=CDMX_TZ)
            else:
                # Con timezone UTC pero es realmente hora de Mexico
                # Quitar el TZ y asignar Mexico
                snapshot_time = snapshot_time.replace(tzinfo=None).replace(tzinfo=CDMX_TZ)
            # Convertir a UTC para almacenamiento
            snapshot_time = snapshot_time.astimezone(timezone.utc)
        
        # Convertir last_reported de epoch a datetime
        last_reported = row.get("last_reported")
        if last_reported is not None and isinstance(last_reported, int):
            last_reported = datetime.fromtimestamp(last_reported, tz=timezone.utc)
        
        records.append({
            "snapshot_time": snapshot_time,
            "station_id": station_id,
            "station_code": info["station_code"],
            "name": info["name"],
            "capacity": info["capacity"],
            "latitude": info["latitude"],
            "longitude": info["longitude"],
            "bikes_available": row.get("num_bikes_available", 0),
            "bikes_disabled": row.get("num_bikes_disabled", 0),
            "docks_available": row.get("num_docks_available", 0),
            "docks_disabled": row.get("num_docks_disabled", 0),
            "is_installed": row.get("is_installed", 0),
            "is_renting": row.get("is_renting", 0),
            "is_returning": row.get("is_returning", 0),
            "last_reported": last_reported,
        })
    
    if not records:
        print(f"  No se encontraron registros validos para migrar")
        return False
    
    # Crear nuevo DataFrame
    new_df = pl.DataFrame(records)
    
    # Eliminar duplicados
    new_df = new_df.unique(subset=["snapshot_time", "station_code"], keep="last")
    new_df = new_df.sort(["station_code", "snapshot_time"])
    
    # Hacer backup del archivo original
    backup_path = file_path.with_suffix(".parquet.bak")
    file_path.rename(backup_path)
    
    # Guardar nuevo archivo
    new_df.write_parquet(file_path)
    
    print(f"  Migrado: {len(new_df)} registros ({skipped} estaciones omitidas sin station_code)")
    print(f"  Backup guardado en: {backup_path.name}")
    
    return True


def main():
    """Funcion principal."""
    # Directorio base de datos GBFS
    base_dir = Path(__file__).parent.parent / "data" / "gbfs"
    
    if not base_dir.exists():
        print(f"Error: No se encontro el directorio {base_dir}")
        sys.exit(1)
    
    # Buscar todos los archivos parquet
    parquet_files = list(base_dir.rglob("*.parquet"))
    
    if not parquet_files:
        print("No se encontraron archivos parquet")
        sys.exit(0)
    
    print(f"Se encontraron {len(parquet_files)} archivos parquet")
    
    # Obtener informacion de estaciones
    station_info = fetch_station_info()
    
    # Migrar cada archivo
    migrated = 0
    skipped = 0
    errors = 0
    
    for file_path in sorted(parquet_files):
        try:
            if migrate_parquet(file_path, station_info):
                migrated += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  Error: {e}")
            errors += 1
    
    # Resumen
    print("\n" + "=" * 50)
    print("Resumen de migracion:")
    print(f"  Archivos migrados: {migrated}")
    print(f"  Archivos saltados (ya correctos): {skipped}")
    print(f"  Errores: {errors}")
    print("=" * 50)


if __name__ == "__main__":
    main()
