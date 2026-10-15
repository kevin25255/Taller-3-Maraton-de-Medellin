"""
PASO 4 - MODELO DIMENSIONAL GOLD.

Construye las tablas del esquema estrella en lakehouse/gold/:
- dim_tiempo.parquet (SCD Tipo 0)
- dim_edicion.parquet (SCD Tipo 0)
- dim_corredor.parquet (SCD Tipo 1)
- dim_checkpoint.parquet (SCD Tipo 2: K30 en 2016-2025 -> KM30 en 2026)
- fact_pasos_rfid.parquet (Granularidad: 1 paso de corredor por checkpoint en una edición)
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SILVER = ROOT / 'lakehouse' / 'silver'
GOLD = ROOT / 'lakehouse' / 'gold'
GOLD.mkdir(parents=True, exist_ok=True)


def main():
    try:
        con = duckdb.connect()

        p_part = str((SILVER / 'participantes_silver.parquet').as_posix())
        p_puntos = str((SILVER / 'puntos_control_silver.parquet').as_posix())
        p_pasos = str((SILVER / 'pasos_silver.parquet').as_posix())

        part = con.execute(f"SELECT * FROM read_parquet('{p_part}')").fetchdf()
        puntos = con.execute(f"SELECT * FROM read_parquet('{p_puntos}')").fetchdf()
        pasos = con.execute(f"SELECT * FROM read_parquet('{p_pasos}')").fetchdf()

        # -----------------------------------------------------------------
        # 1. DIM_TIEMPO (SCD Tipo 0)
        # Atributos: tiempo_sk, fecha, anio, mes, dia, trimestre, dia_semana
        # -----------------------------------------------------------------
        fechas_unicas = pd.to_datetime(pasos['fecha_registro']).dt.normalize().sort_values().unique()
        s_fechas = pd.Series(fechas_unicas)

        dim_tiempo = pd.DataFrame({
            'tiempo_sk': range(1, len(s_fechas) + 1),
            'fecha': s_fechas.dt.date,
            'anio': s_fechas.dt.year,
            'mes': s_fechas.dt.month,
            'dia': s_fechas.dt.day,
            'trimestre': s_fechas.dt.quarter,
            'dia_semana': s_fechas.dt.day_name()
        })
        dim_tiempo.to_parquet(GOLD / 'dim_tiempo.parquet', index=False)
        print(f'DIM_TIEMPO creada     : {len(dim_tiempo):,} filas')

        # -----------------------------------------------------------------
        # 2. DIM_EDICION (SCD Tipo 0)
        # Atributos: edicion_sk, edicion, anio_carrera
        # -----------------------------------------------------------------
        anios = sorted(part['edicion'].unique())
        dim_edicion = pd.DataFrame({
            'edicion_sk': range(1, len(anios) + 1),
            'edicion': [f'Edición {a}' for a in anios],
            'anio_carrera': anios
        })
        dim_edicion.to_parquet(GOLD / 'dim_edicion.parquet', index=False)
        print(f'DIM_EDICION creada    : {len(dim_edicion):,} filas')

        # -----------------------------------------------------------------
        # 3. DIM_CORREDOR (SCD Tipo 1)
        # Atributos: corredor_sk, id_participante, nombre, categoria
        # -----------------------------------------------------------------
        dim_corredor = (
            part[['id_participante', 'nombre', 'categoria']]
            .drop_duplicates(subset=['id_participante'], keep='last')
            .sort_values('id_participante')
            .reset_index(drop=True)
        )
        dim_corredor.insert(0, 'corredor_sk', range(1, len(dim_corredor) + 1))
        dim_corredor.to_parquet(GOLD / 'dim_corredor.parquet', index=False)
        print(f'DIM_CORREDOR creada   : {len(dim_corredor):,} filas')

        # -----------------------------------------------------------------
        # 4. DIM_CHECKPOINT (SCD Tipo 2)
        # Simulación Pregunta 5: id_punto = 5 es K30 (2016-2025) y cambia a KM30 (2026)
        # -----------------------------------------------------------------
        filas_cp = []
        for _, row in puntos.sort_values('id_punto').iterrows():
            id_p = int(row['id_punto'])
            dist = float(row['distancia_km'])
            nom = str(row['nombre'])

            if id_p == 5:
                # Versión histórica 2016-2025: K30 (checkpoint_sk = 5)
                filas_cp.append({
                    'id_punto': 5,
                    'nombre': 'K30',
                    'distancia_km': dist,
                    'valido_desde': pd.Timestamp('2016-01-01').date(),
                    'valido_hasta': pd.Timestamp('2025-12-31').date(),
                    'activo': False,
                    'anio_ini': 2016,
                    'anio_fin': 2025
                })
                # Versión vigente 2026: KM30 (checkpoint_sk = 6)
                filas_cp.append({
                    'id_punto': 5,
                    'nombre': 'KM30',
                    'distancia_km': dist,
                    'valido_desde': pd.Timestamp('2026-01-01').date(),
                    'valido_hasta': pd.Timestamp('9999-12-31').date(),
                    'activo': True,
                    'anio_ini': 2026,
                    'anio_fin': 9999
                })
            else:
                filas_cp.append({
                    'id_punto': id_p,
                    'nombre': nom,
                    'distancia_km': dist,
                    'valido_desde': pd.Timestamp('2016-01-01').date(),
                    'valido_hasta': pd.Timestamp('9999-12-31').date(),
                    'activo': True,
                    'anio_ini': 2016,
                    'anio_fin': 9999
                })

        dim_cp_full = pd.DataFrame(filas_cp)
        dim_cp_full.insert(0, 'checkpoint_sk', range(1, len(dim_cp_full) + 1))

        dim_checkpoint = dim_cp_full[[
            'checkpoint_sk', 'id_punto', 'nombre', 'distancia_km',
            'valido_desde', 'valido_hasta', 'activo'
        ]].copy()
        dim_checkpoint.to_parquet(GOLD / 'dim_checkpoint.parquet', index=False)
        print(f'DIM_CHECKPOINT creada : {len(dim_checkpoint):,} filas (con SCD Tipo 2 en K30/KM30)')

        # -----------------------------------------------------------------
        # 5. FACT_PASOS_RFID
        # -----------------------------------------------------------------
        # Traer la edición de cada participante y la distancia de cada punto
        pasos = pasos.merge(part[['id_participante', 'edicion']], on='id_participante', how='left')
        pasos = pasos.merge(puntos[['id_punto', 'distancia_km']], on='id_punto', how='left')

        # Ordenar por participante y orden de checkpoint para calcular el tramo respecto al anterior
        pasos = pasos.sort_values(['id_participante', 'id_punto']).reset_index(drop=True)

        grupo_corredor = pasos.groupby('id_participante')
        tiempo_ant = grupo_corredor['tiempo_acumulado_segundos'].shift(1).fillna(0)
        dist_ant = grupo_corredor['distancia_km'].shift(1).fillna(0.0)

        # Cálculo de las 4 métricas definidas en la Pregunta 4 del README
        pasos['cantidad_pasos_rfid'] = 1
        pasos['tiempo_tramo_segundos'] = (pasos['tiempo_acumulado_segundos'] - tiempo_ant).astype(int)
        distancia_tramo = pasos['distancia_km'] - dist_ant
        pasos['ritmo_tramo_min_km'] = ((pasos['tiempo_tramo_segundos'] / 60.0) / distancia_tramo).round(2)

        # Lookups de claves sustitutas (_sk)
        pasos['fecha_date'] = pd.to_datetime(pasos['fecha_registro']).dt.date
        pasos = pasos.merge(dim_tiempo[['tiempo_sk', 'fecha']], left_on='fecha_date', right_on='fecha', how='left')
        pasos = pasos.merge(dim_edicion[['edicion_sk', 'anio_carrera']], left_on='edicion', right_on='anio_carrera', how='left')
        pasos = pasos.merge(dim_corredor[['corredor_sk', 'id_participante']], on='id_participante', how='left')

        # Lookup SCD Tipo 2 para checkpoint_sk según el año de la edición
        pasos = pasos.merge(
            dim_cp_full[['checkpoint_sk', 'id_punto', 'anio_ini', 'anio_fin']],
            on='id_punto',
            how='left'
        )
        pasos = pasos[(pasos['edicion'] >= pasos['anio_ini']) & (pasos['edicion'] <= pasos['anio_fin'])].copy()

        fact_pasos_rfid = pasos[[
            'id_paso',
            'tiempo_sk',
            'edicion_sk',
            'corredor_sk',
            'checkpoint_sk',
            'cantidad_pasos_rfid',
            'tiempo_acumulado_segundos',
            'tiempo_tramo_segundos',
            'ritmo_tramo_min_km'
        ]].sort_values('id_paso').reset_index(drop=True)

        fact_pasos_rfid.to_parquet(GOLD / 'fact_pasos_rfid.parquet', index=False)
        print(f'FACT_PASOS_RFID creada: {len(fact_pasos_rfid):,} filas')
        print('Modelado dimensional en Zona Gold completado correctamente.')

    except Exception as e:
        print(f'ERROR en transform_gold.py: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()