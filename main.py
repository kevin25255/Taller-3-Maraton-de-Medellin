"""
PASO 6 - Orquestación del pipeline.
Ejecuta en orden:
1. scripts/extract.py
2. scripts/transform_silver.py
3. scripts/transform_gold.py
4. scripts/analyze.py
"""
import subprocess
import sys
import time

PASOS = [
    ('Paso 2: Extracción -> Bronze', 'scripts/extract.py'),
    ('Paso 3: Limpieza -> Silver', 'scripts/transform_silver.py'),
    ('Paso 4: Modelo Dimensional -> Gold', 'scripts/transform_gold.py'),
    ('Paso 5: Consultas Analíticas y Benchmark', 'scripts/analyze.py'),
]


def main():
    print('=' * 65)
    print('  MINI-LAKEHOUSE MARATÓN DE MEDELLÍN - Pipeline de Datos')
    print('=' * 65)

    t_total = time.time()

    for nombre, script in PASOS:
        print(f'\n>>> {nombre}')
        t0 = time.time()
        result = subprocess.run([sys.executable, script], capture_output=False)
        if result.returncode != 0:
            print(f'ERROR en {script}. Pipeline detenido.')
            sys.exit(1)
        print(f'Completado en {time.time() - t0:.2f}s')

    print('\n' + '=' * 65)
    print(f'Pipeline completo en {time.time() - t_total:.2f}s')
    print('Archivos Gold disponibles en: lakehouse/gold/')
    print('=' * 65)


if __name__ == '__main__':
    main()