"""
PASO 6 - Orquestación del pipeline del Mini-Lakehouse.

Modos de uso:
- Pipeline completo (por defecto):
    python main.py
- Ejecutar uno de los 5 pasos individualmente:
    python main.py --paso 1   (Preparación e ingesta en PostgreSQL)
    python main.py --paso 2   (Extracción hacia Zona Bronze)
    python main.py --paso 3   (Limpieza y Calidad hacia Zona Silver)
    python main.py --paso 4   (Modelo Dimensional hacia Zona Gold)
    python main.py --paso 5   (Todas las Consultas Analíticas y Benchmark)
- Ejecutar una de las 5 consultas individualmente:
    python main.py --consulta 1 .. 5
- Ejecutar solo el Benchmark:
    python main.py --benchmark
"""
import argparse
import subprocess
import sys
import time

MAPA_PASOS = {
    1: ('Paso 1: Preparación e Ingesta OLTP -> PostgreSQL', ['scripts/init_db.py']),
    2: ('Paso 2: Extracción -> Zona Bronze', ['scripts/extract.py']),
    3: ('Paso 3: Limpieza y Calidad -> Zona Silver', ['scripts/transform_silver.py']),
    4: ('Paso 4: Modelo Dimensional y SCD Tipo 2 -> Zona Gold', ['scripts/transform_gold.py']),
    5: ('Paso 5: Consultas Analíticas y Benchmark', ['scripts/analyze.py']),
}


def correr_comando(nombre: str, args_script: list[str]):
    print(f'\n>>> {nombre}')
    t0 = time.time()
    result = subprocess.run([sys.executable] + args_script, capture_output=False)
    if result.returncode != 0:
        print(f'ERROR ejecutando {" ".join(args_script)}. Ejecución detenida.')
        sys.exit(1)
    print(f'Completado en {time.time() - t0:.2f}s')


def parse_args():
    parser = argparse.ArgumentParser(
        description='Orquestador del Mini-Lakehouse Maratón de Medellín.'
    )
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        '--paso',
        type=int,
        choices=[1, 2, 3, 4, 5],
        help='Ejecuta únicamente el paso indicado (1 a 5).'
    )
    grupo.add_argument(
        '--consulta',
        type=int,
        choices=[1, 2, 3, 4, 5],
        help='Ejecuta únicamente la consulta analítica indicada (1 a 5).'
    )
    grupo.add_argument(
        '--benchmark',
        action='store_true',
        help='Ejecuta únicamente el benchmark entre PostgreSQL y DuckDB.'
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print('=' * 65)
    print('  MINI-LAKEHOUSE MARATÓN DE MEDELLÍN - Orquestador de Pipeline')
    print('=' * 65)

    # Caso 1: Ejecutar un paso específico (1 al 5)
    if args.paso is not None:
        nombre, cmd = MAPA_PASOS[args.paso]
        correr_comando(nombre, cmd)
        return

    # Caso 2: Ejecutar una consulta específica (1 al 5)
    if args.consulta is not None:
        correr_comando(
            f'Ejecutando Consulta Analítica #{args.consulta}',
            ['scripts/analyze.py', '--consulta', str(args.consulta)]
        )
        return

    # Caso 3: Ejecutar únicamente el benchmark
    if args.benchmark:
        correr_comando(
            'Ejecutando Benchmark PostgreSQL vs DuckDB',
            ['scripts/analyze.py', '--benchmark']
        )
        return

    # Caso por defecto (sin argumentos): ejecuta todo el pipeline en secuencia
    t_total = time.time()
    for num_paso in [1, 2, 3, 4, 5]:
        nombre, cmd = MAPA_PASOS[num_paso]
        correr_comando(nombre, cmd)

    print('\n' + '=' * 65)
    print(f'Pipeline completo ejecutado con éxito en {time.time() - t_total:.2f}s')
    print('Archivos Gold disponibles en: lakehouse/gold/')
    print('=' * 65)


if __name__ == '__main__':
    main()