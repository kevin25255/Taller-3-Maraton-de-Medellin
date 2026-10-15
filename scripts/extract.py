"""
PASO 2 - EXTRACCIÓN HACIA BRONZE.

Fuente: PostgreSQL del proyecto Maratón de Medellín.
Tablas: participantes, puntos_control, pasos.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
BRONZE = ROOT / 'lakehouse' / 'bronze'
BRONZE.mkdir(parents=True, exist_ok=True)


def obtener_engine():
    host = os.getenv('DB_HOST', 'db')
    port = os.getenv('DB_PORT', '5432')
    dbname = os.getenv('DB_NAME', 'maraton')
    user = os.getenv('DB_USER', 'maraton')
    password = os.getenv('DB_PASSWORD', 'lakehouse_local_dev')
    url = f'postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}'
    return create_engine(url)


def extraer_tabla(engine, query: str, nombre: str, fecha_extraccion: str) -> Path:
    print(f'Extrayendo {nombre}...')
    df = pd.read_sql(query, engine)

    # Añadir metadata de auditoría (inmutabilidad y trazabilidad en Bronze)
    df['_extraido_en'] = datetime.now()
    df['_fuente'] = 'postgresql'

    ruta = BRONZE / f'{nombre}_{fecha_extraccion}.parquet'
    df.to_parquet(ruta, index=False)
    print(f'  -> {len(df):,} filas guardadas en {ruta.relative_to(ROOT)}')
    return ruta


def main():
    try:
        engine = obtener_engine()
        fecha_extraccion = datetime.now().strftime('%Y%m%d_%H%M%S')

        extraer_tabla(engine, 'SELECT * FROM participantes', 'participantes', fecha_extraccion)
        extraer_tabla(engine, 'SELECT * FROM puntos_control', 'puntos_control', fecha_extraccion)
        extraer_tabla(engine, 'SELECT * FROM pasos', 'pasos', fecha_extraccion)

        # Verificación rápida de Bronze con DuckDB
        con = duckdb.connect()
        patron_pasos = str((BRONZE / 'pasos_*.parquet').as_posix())
        verificacion = con.execute(f"""
            SELECT COUNT(*) AS filas_en_bronze,
                   MIN(_extraido_en) AS primera_extraccion,
                   MAX(_extraido_en) AS ultima_extraccion
            FROM read_parquet('{patron_pasos}')
        """).fetchdf()
        print('\nVerificación de Bronze con DuckDB (pasos):')
        print(verificacion.to_string(index=False))
        print('Extracción a Zona Bronze completada correctamente.')

    except Exception as e:
        print(f'ERROR en extract.py: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
    
 