"""
PASO 5 - CONSULTAS ANALÍTICAS Y BENCHMARK.

Ejecuta 5 consultas analíticas con DuckDB sobre los archivos Parquet de Gold
y compara el tiempo de ejecución frente a PostgreSQL (OLTP).
"""
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


def main():
    try:
        con = duckdb.connect()

        # Registrar vistas sobre los archivos Parquet de la Zona Gold
        for tabla in ['fact_pasos_rfid', 'dim_tiempo', 'dim_edicion', 'dim_corredor', 'dim_checkpoint']:
            ruta = str((GOLD / f'{tabla}.parquet').as_posix())
            con.execute(f"CREATE TABLE {tabla} AS SELECT * FROM read_parquet('{ruta}')")

        # Q1: Comparación histórica entre las 11 ediciones (2016 a 2026)
        q1 = """
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

        # Q2: Identificación de tramos con mayores tiempos de recorrido y ritmo en 42K
        q2 = """
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

        # Q3: Desempeño comparado según la categoría del corredor
        q3 = """
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

        # Q4: Demostración de SCD Tipo 2 en DIM_CHECKPOINT (K30 en 2016-2025 vs KM30 en 2026)
        q4 = """
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

        # Q5: Top 10 corredores de 42K en META durante la edición 2026
        q5 = """
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

        consultas = [
            ('Consulta 1: Desempeño histórico por edición (2016-2026)', q1),
            ('Consulta 2: Tiempos y ritmos por tramo en 42K', q2),
            ('Consulta 3: Comparación de desempeño por categoría', q3),
            ('Consulta 4: Comprobación SCD Tipo 2 en DIM_CHECKPOINT (K30 vs KM30)', q4),
            ('Consulta 5: Top 10 corredores de 42K en META (Edición 2026)', q5),
        ]

        print('=' * 70)
        print('  CONSULTAS ANALÍTICAS EN DUCKDB SOBRE ZONA GOLD')
        print('=' * 70)

        for titulo, query in consultas:
            inicio = time.time()
            df_res = con.execute(query).fetchdf()
            ms = (time.time() - inicio) * 1000
            print(f'\n[{titulo}] - {ms:.2f} ms ({len(df_res)} filas)')
            print(df_res.to_string(index=False))

        # -----------------------------------------------------------------
        # 5.2 BENCHMARK: PostgreSQL (OLTP) vs DuckDB (Columnar)
        # -----------------------------------------------------------------
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
        print(f'Factor de mejora  : {factor:>8.1f}x')

    except Exception as e:
        print(f'ERROR en analyze.py: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
