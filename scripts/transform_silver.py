"""
PASO 3 - TRANSFORMACIÓN SILVER.

Lee los archivos Bronze más recientes, valida nulos, tipos de datos,
duplicados, fechas/tiempos e integridad de identificadores, y genera
los archivos Parquet en Silver junto con el reporte de calidad.
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BRONZE = ROOT / 'lakehouse' / 'bronze'
SILVER = ROOT / 'lakehouse' / 'silver'
DOCS = ROOT / 'docs'
SILVER.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)


def ultimo_archivo_bronze(prefijo: str) -> str:
    archivos = sorted(BRONZE.glob(f'{prefijo}_*.parquet'))
    if not archivos:
        raise FileNotFoundError(f'No se encontraron archivos en Bronze para {prefijo}_*.parquet')
    return str(archivos[-1].as_posix())


def main():
    try:
        con = duckdb.connect()

        ruta_part = ultimo_archivo_bronze('participantes')
        ruta_puntos = ultimo_archivo_bronze('puntos_control')
        ruta_pasos = ultimo_archivo_bronze('pasos')

        df_part_raw = con.execute(f"SELECT * FROM read_parquet('{ruta_part}')").fetchdf()
        df_puntos_raw = con.execute(f"SELECT * FROM read_parquet('{ruta_puntos}')").fetchdf()
        df_pasos_raw = con.execute(f"SELECT * FROM read_parquet('{ruta_pasos}')").fetchdf()

        print(f'Bronze cargado -> participantes: {len(df_part_raw):,} | puntos: {len(df_puntos_raw):,} | pasos: {len(df_pasos_raw):,}')

        # 1. Limpieza de puntos_control
        df_puntos = df_puntos_raw.copy()
        df_puntos['id_punto'] = pd.to_numeric(df_puntos['id_punto'], errors='coerce')
        df_puntos['nombre'] = df_puntos['nombre'].astype(str).str.strip().str.upper()
        df_puntos['distancia_km'] = pd.to_numeric(df_puntos['distancia_km'], errors='coerce')
        df_puntos = df_puntos.dropna(subset=['id_punto', 'nombre', 'distancia_km'])
        df_puntos['id_punto'] = df_puntos['id_punto'].astype(int)
        df_puntos = df_puntos.drop_duplicates(subset=['id_punto'], keep='first').sort_values('id_punto')

        # 2. Limpieza de participantes
        df_part = df_part_raw.copy()
        df_part['id_participante'] = pd.to_numeric(df_part['id_participante'], errors='coerce')
        df_part['edicion'] = pd.to_numeric(df_part['edicion'], errors='coerce')
        df_part['chip_id'] = df_part['chip_id'].fillna('SIN_CHIP').astype(str).str.strip()
        df_part['nombre'] = df_part['nombre'].fillna('SIN_NOMBRE').astype(str).str.strip()
        df_part['categoria'] = df_part['categoria'].fillna('SIN_CATEGORIA').astype(str).str.strip().str.upper()
        df_part = df_part.dropna(subset=['id_participante', 'edicion'])
        df_part['id_participante'] = df_part['id_participante'].astype(int)
        df_part['edicion'] = df_part['edicion'].astype(int)
        df_part = df_part.drop_duplicates(subset=['id_participante'], keep='first').sort_values('id_participante')

        # 3. Limpieza de pasos
        df_pasos = df_pasos_raw.copy()
        nulos_antes = int(df_pasos.isnull().sum().sum())

        df_pasos['id_participante'] = pd.to_numeric(df_pasos['id_participante'], errors='coerce')
        df_pasos['id_punto'] = pd.to_numeric(df_pasos['id_punto'], errors='coerce')
        df_pasos['tiempo_acumulado_segundos'] = pd.to_numeric(df_pasos['tiempo_acumulado_segundos'], errors='coerce')
        df_pasos['fecha_registro'] = pd.to_datetime(df_pasos['fecha_registro'], errors='coerce')

        # Si PostgreSQL incluyó id_paso lo tipamos; si no, generamos secuencia limpia
        if 'id_paso' in df_pasos.columns:
            df_pasos['id_paso'] = pd.to_numeric(df_pasos['id_paso'], errors='coerce')
        else:
            df_pasos.insert(0, 'id_paso', range(1, len(df_pasos) + 1))

        # Eliminar nulos y tiempos inválidos
        df_pasos = df_pasos.dropna(subset=['id_paso', 'id_participante', 'id_punto', 'tiempo_acumulado_segundos', 'fecha_registro'])
        df_pasos = df_pasos[df_pasos['tiempo_acumulado_segundos'] > 0].copy()

        df_pasos['id_paso'] = df_pasos['id_paso'].astype(int)
        df_pasos['id_participante'] = df_pasos['id_participante'].astype(int)
        df_pasos['id_punto'] = df_pasos['id_punto'].astype(int)
        df_pasos['tiempo_acumulado_segundos'] = df_pasos['tiempo_acumulado_segundos'].astype(int)

        # Validar integridad referencial con participantes y puntos_control
        df_pasos = df_pasos[
            df_pasos['id_participante'].isin(df_part['id_participante']) &
            df_pasos['id_punto'].isin(df_puntos['id_punto'])
        ].copy()

        # Eliminar duplicados de lecturas RFID (1 paso único por participante y punto de control)
        filas_antes_dup = len(df_pasos)
        df_pasos = df_pasos.sort_values(['id_participante', 'id_punto', 'fecha_registro', 'id_paso'])
        df_pasos = df_pasos.drop_duplicates(subset=['id_participante', 'id_punto'], keep='first')
        duplicados_eliminados = filas_antes_dup - len(df_pasos)
        nulos_despues = int(df_pasos.isnull().sum().sum())

        # 4. Guardar en Zona Silver
        df_part.to_parquet(SILVER / 'participantes_silver.parquet', index=False)
        df_puntos.to_parquet(SILVER / 'puntos_control_silver.parquet', index=False)
        df_pasos.to_parquet(SILVER / 'pasos_silver.parquet', index=False)

        # 5. Reporte de calidad Silver (impreso y guardado en docs/reporte_calidad.txt)
        reporte = (
            "=== REPORTE DE CALIDAD SILVER ===\n"
            f"Filas Bronze originales (pasos) : {len(df_pasos_raw):>10,}\n"
            f"Filas Silver resultantes (pasos): {len(df_pasos):>10,}\n"
            f"Filas eliminadas                : {len(df_pasos_raw) - len(df_pasos):>10,}\n"
            f"Duplicados RFID eliminados      : {duplicados_eliminados:>10,}\n"
            f"Nulos resueltos                 : {nulos_antes} -> {nulos_despues}\n"
            f"Porcentaje retenido             : {len(df_pasos) / len(df_pasos_raw) * 100:>9.2f}%\n"
            f"Participantes válidos en Silver : {len(df_part):>10,}\n"
            f"Checkpoints válidos en Silver   : {len(df_puntos):>10,}\n"
            f"Rango de fechas de pasos        : {df_pasos['fecha_registro'].min()} -> {df_pasos['fecha_registro'].max()}\n"
            f"Tiempo acumulado promedio (seg) : {df_pasos['tiempo_acumulado_segundos'].mean():>10,.2f}\n"
        )
        print('\n' + reporte)
        (DOCS / 'reporte_calidad.txt').write_text(reporte, encoding='utf-8')
        print('Transformación a Zona Silver completada correctamente.')

    except Exception as e:
        print(f'ERROR en transform_silver.py: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()