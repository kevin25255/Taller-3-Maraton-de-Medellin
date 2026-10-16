"""
PASO 5 - CONSULTAS ANALÍTICAS Y BENCHMARK.

Permite ejecutar:
- Todas las consultas y el benchmark (por defecto)
- Una consulta individual (--consulta 1..5)
- Solo el benchmark (--benchmark)
"""
import argparse
import os
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / 'lakehouse' / 'gold'


def obtener_engine():
    host = os.getenv('DB_HOST', 'db')
    port = os.getenv('DB_PORT', '5432')
    dbname = os.getenv('DB_NAME', 'maraton')
    user = os.getenv('DB_USER', 'maraton')
    password = os.getenv('DB_PASSWORD', 'lakehouse_local_dev')
    url = f'postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}'
    return create_engine(url)


# Diccionario con las 5 consultas analíticas de negocio
CONSULTAS = {
    1: (
        'Consulta 1: Desempeño histórico por edición (2016-2026)',
        """
        SELECT e.anio_carrera,
               e.edicion,
               SUM(f.cantidad_pasos_rfid) AS total_pasos_rfid,
               ROUND(AVG(f.tiempo_tramo_segundos), 2) AS tiempo_tramo_prom_seg,
               ROUND(AVG(f.ritmo_tramo_min_km), 2) AS ritmo_promedio_min_km
        FROM fact_pasos_rfid f
        JOIN dim_edicion e ON f.edicion_sk = e.edicion_sk
        GROUP BY e.anio_carrera, e.edicion
        ORDER BY e.anio_carrera
        """
    ),
    2: (
        'Consulta 2: Tiempos y ritmos por tramo en 42K',
        """
        SELECT c.id_punto,
               MIN(c.nombre) AS punto_control,
               c.distancia_km,
               SUM(f.cantidad_pasos_rfid) AS total_lecturas,
               ROUND(AVG(f.tiempo_tramo_segundos) / 60.0, 2) AS tiempo_tramo_prom_min,
               ROUND(AVG(f.tiempo_acumulado_segundos) / 60.0, 2) AS tiempo_acum_prom_min,
               ROUND(AVG(f.ritmo_tramo_min_km), 2) AS ritmo_tramo_min_km
        FROM fact_pasos_rfid f
        JOIN dim_corredor co ON f.corredor_sk = co.corredor_sk
        JOIN dim_checkpoint c ON f.checkpoint_sk = c.checkpoint_sk
        WHERE co.categoria = '42K'
        GROUP BY c.id_punto, c.distancia_km
        ORDER BY c.id_punto
        """
    ),
    3: (
        'Consulta 3: Comparación de desempeño por categoría',
        """
        SELECT co.categoria,
               COUNT(DISTINCT co.id_participante) AS total_corredores,
               SUM(f.cantidad_pasos_rfid) AS pasos_registrados,
               ROUND(AVG(f.tiempo_tramo_segundos), 2) AS tiempo_tramo_prom_seg,
               ROUND(AVG(f.ritmo_tramo_min_km), 2) AS ritmo_promedio_min_km
        FROM fact_pasos_rfid f
        JOIN dim_corredor co ON f.corredor_sk = co.corredor_sk
        GROUP BY co.categoria
        ORDER BY co.categoria
        """
    ),
    4: (
        'Consulta 4: Comprobación SCD Tipo 2 en DIM_CHECKPOINT (K30 vs KM30)',
        """
        SELECT c.checkpoint_sk,
               c.id_punto,
               c.nombre,
               c.distancia_km,
               c.valido_desde,
               c.valido_hasta,
               c.activo,
               MIN(e.anio_carrera) AS edicion_inicial,
               MAX(e.anio_carrera) AS edicion_final,
               SUM(f.cantidad_pasos_rfid) AS pasos_registrados
        FROM fact_pasos_rfid f
        JOIN dim_checkpoint c ON f.checkpoint_sk = c.checkpoint_sk
        JOIN dim_edicion e ON f.edicion_sk = e.edicion_sk
        WHERE c.id_punto = 5
        GROUP BY c.checkpoint_sk, c.id_punto, c.nombre, c.distancia_km, c.valido_desde, c.valido_hasta, c.activo
        ORDER BY c.checkpoint_sk
        """
    ),
    5: (
        'Consulta 5: Top 10 corredores de 42K en META (Edición 2026)',
        """
        SELECT co.id_participante,
               co.nombre,
               co.categoria,
               e.anio_carrera AS edicion,
               f.tiempo_acumulado_segundos,
               ROUND(f.tiempo_acumulado_segundos / 3600.0, 2) AS horas_totales,
               f.ritmo_tramo_min_km AS ritmo_tramo_meta
        FROM fact_pasos_rfid f
        JOIN dim_corredor co ON f.corredor_sk = co.corredor_sk
        JOIN dim_checkpoint c ON f.checkpoint_sk = c.checkpoint_sk
        JOIN dim_edicion e ON f.edicion_sk = e.edicion_sk
        WHERE co.categoria = '42K'
          AND c.nombre = 'META'
          AND e.anio_carrera = 2026
        ORDER BY f.tiempo_acumulado_segundos ASC
        LIMIT 10
        """
    ),
}


def cargar_tablas_gold(con: duckdb.DuckDBPyConnection):
    tablas = ['fact_pasos_rfid', 'dim_tiempo', 'dim_edicion', 'dim_corredor', 'dim_checkpoint']
    for tabla in tablas:
        archivo = GOLD / f'{tabla}.parquet'
        if not archivo.is_file():
            raise FileNotFoundError(
                f'No se encontró {archivo.relative_to(ROOT)}. '
                'Ejecuta primero los pasos 2, 3 y 4 para generar la Zona Gold.'
            )
        ruta = str(archivo.as_posix())
        con.execute(f"CREATE TABLE {tabla} AS SELECT * FROM read_parquet('{ruta}')")


def ejecutar_consulta(con: duckdb.DuckDBPyConnection, num: int):
    titulo, query = CONSULTAS[num]
    inicio = time.time()
    df_res = con.execute(query).fetchdf()
    ms = (time.time() - inicio) * 1000
    print(f'\n[{titulo}] - {ms:.2f} ms ({len(df_res)} filas)')
    print(df_res.to_string(index=False))


def ejecutar_benchmark(con: duckdb.DuckDBPyConnection):
    print('\n' + '=' * 70)
    print('  BENCHMARK: PostgreSQL (OLTP) vs DuckDB (Columnar)')
    print('=' * 70)

    engine = obtener_engine()

    QUERY_OLTP = text("""
        SELECT p.edicion AS anio_carrera,
               p.categoria,
               s.id_punto,
               COUNT(*) AS total_pasos,
               AVG(s.tiempo_acumulado_segundos) AS promedio_acumulado_seg
        FROM pasos s
        JOIN participantes p ON p.id_participante = s.id_participante
        GROUP BY p.edicion, p.categoria, s.id_punto
        ORDER BY p.edicion, p.categoria, s.id_punto
    """)

    QUERY_DUCKDB = """
        SELECT e.anio_carrera,
               co.categoria,
               c.id_punto,
               SUM(f.cantidad_pasos_rfid) AS total_pasos,
               AVG(f.tiempo_acumulado_segundos) AS promedio_acumulado_seg
        FROM fact_pasos_rfid f
        JOIN dim_edicion e ON f.edicion_sk = e.edicion_sk
        JOIN dim_corredor co ON f.corredor_sk = co.corredor_sk
        JOIN dim_checkpoint c ON f.checkpoint_sk = c.checkpoint_sk
        GROUP BY e.anio_carrera, co.categoria, c.id_punto
        ORDER BY e.anio_carrera, co.categoria, c.id_punto
    """

    t0 = time.time()
    with engine.connect() as conn:
        df_pg = pd.read_sql(QUERY_OLTP, conn)
    t_pg = (time.time() - t0) * 1000

    t0 = time.time()
    df_dk = con.execute(QUERY_DUCKDB).fetchdf()
    t_dk = (time.time() - t0) * 1000

    factor = t_pg / t_dk if t_dk > 0 else 0
    print(f'PostgreSQL (OLTP) : {t_pg:>8.2f} ms ({len(df_pg)} filas)')
    print(f'DuckDB (Columnar) : {t_dk:>8.2f} ms ({len(df_dk)} filas)')
    print(f'Factor de mejora  : {factor:>8.1f}x más rápido en DuckDB')


def parse_args():
    parser = argparse.ArgumentParser(description='Consultas analíticas y Benchmark en DuckDB.')
    parser.add_argument(
        '--consulta',
        type=int,
        choices=[1, 2, 3, 4, 5],
        help='Ejecuta únicamente la consulta indicada (1 a 5).'
    )
    parser.add_argument(
        '--benchmark',
        action='store_true',
        help='Ejecuta únicamente el benchmark PostgreSQL vs DuckDB.'
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        con = duckdb.connect()
        cargar_tablas_gold(con)

        # Si se pidió una consulta específica (1 a 5)
        if args.consulta is not None:
            print('=' * 70)
            print(f'  EJECUTANDO CONSULTA ANALÍTICA #{args.consulta} EN DUCKDB (ZONA GOLD)')
            print('=' * 70)
            ejecutar_consulta(con, args.consulta)

        # Si se pidió únicamente el benchmark
        if args.benchmark:
            ejecutar_benchmark(con)

        # Si no se pasaron filtros, ejecuta las 5 consultas y el benchmark
        if args.consulta is None and not args.benchmark:
            print('=' * 70)
            print('  CONSULTAS ANALÍTICAS EN DUCKDB SOBRE ZONA GOLD')
            print('=' * 70)
            for num in range(1, 6):
                ejecutar_consulta(con, num)
            ejecutar_benchmark(con)

    except Exception as e:
        print(f'ERROR en analyze.py: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
