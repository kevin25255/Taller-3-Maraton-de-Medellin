"""Preparación reproducible de PostgreSQL para el Taller 3.

Uso: docker compose exec app python scripts/init_db.py
"""
import csv
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
SQL = ROOT / 'sql' / 'maraton.sql'
FILES = {
    'participantes': DATA / 'participantes.csv',
    'puntos_control': DATA / 'puntos_control.csv',
    'pasos': DATA / 'pasos.csv',
}
HEADERS = {
    'participantes': ['id_participante', 'chip_id', 'nombre', 'categoria', 'edicion'],
    'puntos_control': ['id_punto', 'nombre', 'distancia_km'],
    'pasos': ['id_participante', 'id_punto', 'tiempo_acumulado_segundos', 'fecha_registro'],
}
PUNTOS = [(1, 'K5', 5.0), (2, 'K10', 10.0), (3, 'K15', 15.0),
          (4, 'K21', 21.0), (5, 'K30', 30.0), (6, 'META', 42.195)]
CATEGORIAS = {'5K': 1, '10K': 2, '15K': 3, '21K': 4, '30K': 5, '42K': 6}
PARTICIPANTES_2026 = {'5K': 2000, '10K': 2000, '15K': 2000,
                      '21K': 2000, '30K': 2000, '42K': 5000}
SEMILLA = 20261014


def generar_csv():
    """Genera las ediciones 2016–2026 con pasos RFID cuando no existen los CSV."""
    print('No hay CSV históricos. Generando conjunto completo con semilla fija...')
    DATA.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEMILLA)
    with FILES['puntos_control'].open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS['puntos_control'])
        writer.writerows(PUNTOS)

    total_pasos = 0
    pid = 1
    with FILES['participantes'].open('w', newline='', encoding='utf-8') as fp, \
         FILES['pasos'].open('w', newline='', encoding='utf-8') as fs:
        wp, ws = csv.writer(fp), csv.writer(fs)
        wp.writerow(HEADERS['participantes'])
        ws.writerow(HEADERS['pasos'])
        for edicion in range(2016, 2027):
            inicio = datetime(edicion, 9, 1, 7)
            factor_edicion = 1 + (2026 - edicion) * 0.003
            for categoria, cantidad_puntos in CATEGORIAS.items():
                cantidad = PARTICIPANTES_2026[categoria] if edicion == 2026 else 2500
                for numero in range(1, cantidad + 1):
                    wp.writerow([pid, f'CHIP-{edicion}-{categoria}-{numero:04d}',
                                 f'Corredor_{edicion}_{categoria}_{numero:04d}', categoria, edicion])

                    ritmo_base = rng.uniform(4.0, 7.0)
                    fatiga = rng.uniform(0.01, 0.06)
                    tiempo = 0
                    anterior = 0
                    for indice, (punto_id, _, distancia) in enumerate(PUNTOS[:cantidad_puntos]):
                        ritmo = (ritmo_base * factor_edicion * (1 + fatiga * indice)
                                 * rng.uniform(0.97, 1.03))
                        tiempo += int(ritmo * 60 * (distancia - anterior))
                        fecha = inicio + timedelta(seconds=tiempo)
                        ws.writerow([pid, punto_id, tiempo, fecha.strftime('%Y-%m-%d %H:%M:%S')])
                        total_pasos += 1
                        anterior = distancia
                    pid += 1
    print(f'Generados: {pid - 1:,} participantes; {total_pasos:,} pasos.')


def verificar_archivos():
    presentes = {name: path.is_file() for name, path in FILES.items()}
    if not any(presentes.values()):
        generar_csv()
    elif not all(presentes.values()):
        faltantes = [name for name, existe in presentes.items() if not existe]
        raise RuntimeError(
            f'Conjunto CSV incompleto: faltan {faltantes}. '
            'Recupéralos del respaldo del Taller 2. Para generar un conjunto nuevo '
            'con IDs coherentes, mueve primero los CSV existentes a una carpeta de respaldo '
            'y vuelve a ejecutar el script.'
        )
    else:
        print('Se utilizarán los tres CSV existentes, sin modificarlos.')

    conteos = {}
    for name, path in FILES.items():
        with path.open('r', newline='', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header != HEADERS[name]:
                raise ValueError(f'Encabezado inválido en {path}: {header!r}')
            conteos[name] = sum(1 for row in reader if row)
        print(f'{name}: {conteos[name]:,} filas ({path.stat().st_size:,} bytes)')
    if conteos['puntos_control'] != 6 or not conteos['participantes'] or not conteos['pasos']:
        raise ValueError('CSV vacíos o catálogo de checkpoints inesperado.')
    return conteos


def conectar():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'db'),
        port=int(os.getenv('DB_PORT', '5432')),
        dbname=os.getenv('DB_NAME', 'maraton'),
        user=os.getenv('DB_USER', 'maraton'),
        password=os.getenv('DB_PASSWORD', 'lakehouse_local_dev'),
    )



def comprobar_integridad(cur):
    # Verificar que las once ediciones tengan registros RFID.
    cur.execute("""
        SELECT p.edicion, COUNT(*)
        FROM pasos s
        JOIN participantes p
          ON p.id_participante = s.id_participante
        GROUP BY p.edicion
        ORDER BY p.edicion
    """)

    conteos = dict(cur.fetchall())

    for edicion in range(2016, 2027):
        esperado = 60000 if edicion == 2026 else 52500

        if conteos.get(edicion) != esperado:
            raise ValueError(
                f'Edición {edicion}: se esperaban '
                f'{esperado} pasos y se encontraron '
                f'{conteos.get(edicion, 0)}.'
            )

    # Verificar que los tiempos aumenten entre checkpoints.
    cur.execute("""
        SELECT COUNT(*)
        FROM (
            SELECT
                id_participante,
                tiempo_acumulado_segundos,
                LAG(tiempo_acumulado_segundos) OVER (
                    PARTITION BY id_participante
                    ORDER BY id_punto
                ) AS tiempo_anterior
            FROM pasos
        ) x
        WHERE tiempo_anterior IS NOT NULL
          AND tiempo_acumulado_segundos <= tiempo_anterior
    """)

    if cur.fetchone()[0] > 0:
        raise ValueError(
            'Existen tiempos acumulados que no aumentan '
            'entre checkpoints.'
        )


def cargar_postgres(con, esperados):
    with con.cursor() as cur:
        # El script SQL ya se revisó durante la etapa anterior.
        cur.execute(SQL.read_text(encoding='utf-8-sig'))
        cur.execute('SELECT COUNT(*) FROM participantes')
        participantes_db = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM pasos')
        pasos_db = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM puntos_control')
        puntos_db = cur.fetchone()[0]

        if (participantes_db, pasos_db, puntos_db) == (
            esperados['participantes'], esperados['pasos'], esperados['puntos_control']
        ):
            print('La base ya tiene los conteos esperados. No se cargarán duplicados.')
            comprobar_integridad(cur)
            return

        # No borrar datos ni sobrescribir una carga parcial inesperada.
        if participantes_db != 0 or pasos_db != 0:
            raise RuntimeError(
                'PostgreSQL contiene una carga parcial o un conjunto con tamaños diferentes '
                f'(participantes={participantes_db:,}, pasos={pasos_db:,}). '
                'No se modifica automáticamente. Revisar antes de intervenir.'
            )
        if puntos_db != esperados['puntos_control']:
            raise RuntimeError('El catálogo de puntos no coincide con el CSV.')

        print('Cargando CSV mediante COPY en una sola transacción...')
        for tabla in ('participantes', 'pasos'):
            columnas = ', '.join(HEADERS[tabla])
            with FILES[tabla].open('r', encoding='utf-8-sig', newline='') as f:
                cur.copy_expert(
                    f'COPY {tabla} ({columnas}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE)', f
                )
            print(f'  {tabla}: COPY completado')

        for tabla, columna in [('participantes', 'id_participante'), ('pasos', 'id_paso')]:
            cur.execute('''SELECT setval(pg_get_serial_sequence(%s, %s),
                           COALESCE((SELECT MAX(id_participante) FROM participantes), 1), true)'''
                        if tabla == 'participantes' else
                        '''SELECT setval(pg_get_serial_sequence(%s, %s),
                           COALESCE((SELECT MAX(id_paso) FROM pasos), 1), true)''',
                        (tabla, columna))
        comprobar_integridad(cur)
        cur.execute('SELECT COUNT(*) FROM participantes')
        cp = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM pasos')
        cs = cur.fetchone()[0]
        if cp != esperados['participantes'] or cs != esperados['pasos']:
            raise RuntimeError('Los conteos cargados no coinciden con los CSV.')
    print('Carga e integridad verificadas.')


def main():
    esperados = verificar_archivos()
    with conectar() as con:
        cargar_postgres(con, esperados)
        with con.cursor() as cur:
            cur.execute('SELECT edicion, COUNT(*) FROM participantes GROUP BY edicion ORDER BY edicion')
            print('Participantes por edición:', cur.fetchall())
            cur.execute('SELECT COUNT(*) FROM pasos')
            print('Pasos RFID:', cur.fetchone()[0])
    print('Preparación OLTP finalizada correctamente.')


if __name__ == '__main__':
    main()
