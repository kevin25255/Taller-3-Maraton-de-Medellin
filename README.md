# Mini-Lakehouse: Maratón de Medellín (Ediciones 2016–2026)

**Asignatura:** Tópicos Avanzados de Bases de Datos — Taller 3 (Del Operacional al Analítico)  
**Institución:** Institución Universitaria ITM  
**Profesor:** Roberto Carlos Rahamut Suteu  
**Equipo 5:** Yenifer Foronda · Kevin Castaño · Jerónimo Casas  

---

## 1. Diseño dimensional

Antes de comenzar con la extracción y transformación de los datos, definimos el modelo dimensional que utilizaremos en nuestro Mini-Lakehouse de la Maratón de Medellín. Para esto tomamos como base las tablas de PostgreSQL: `participantes`, `pasos` y `puntos_control`.

### Pregunta 1: ¿Cuál es el proceso de negocio que vamos a analizar?

Vamos a analizar el desempeño de los corredores de la Maratón de Medellín a partir de los tiempos registrados en los diferentes puntos de control (checkpoints) de la carrera.

El objetivo es utilizar esta información para realizar análisis históricos que permitan comparar los resultados entre distintas ediciones, identificar los tramos donde los corredores presentan mayores tiempos de recorrido y evaluar las diferencias de desempeño según su categoría.

Para esto utilizaremos datos sintéticos de las ediciones 2016 a 2026 almacenados en PostgreSQL. Para este taller simulamos que la edición 2026 ya finalizó, permitiéndonos comparar las once ediciones.

### Pregunta 2: ¿Cuál es la granularidad?

**Una fila de la tabla de hechos representa el paso de un corredor por un checkpoint específico en una edición de la Maratón de Medellín.**

Elegimos este nivel de detalle porque nos permite conservar cada registro RFID y, a partir de él, calcular indicadores como los tiempos por tramo, ritmos y promedios por categoría o edición, sin perder información.

Por ejemplo, si un corredor pasa por K5, K10 y K15, se generan tres registros independientes. Esto significa que una fila nunca representa varios pasos al mismo tiempo.

Nuestra tabla de hechos se llamará `FACT_PASOS_RFID` y se construirá a partir de la tabla `pasos` de PostgreSQL, complementándola con la información de `participantes` y `puntos_control`.

### Pregunta 3: ¿Cuáles son las dimensiones?

Para nuestro modelo seleccionamos cuatro dimensiones, tomando como base las tablas que ya tenemos en PostgreSQL.

| Dimensión | Atributos principales | ¿Cambia en el tiempo? (SCD) |
|---|---|---|
| `DIM_TIEMPO` | fecha, año, mes, día, trimestre, día_semana | No (Tipo 0) |
| `DIM_EDICION` | edicion, año de la carrera | No (Tipo 0) |
| `DIM_CORREDOR` | id_participante, nombre, categoria | Raro; las correcciones reemplazan el valor anterior (Tipo 1) |
| `DIM_CHECKPOINT` | id_punto, nombre, distancia_km | Sí; conservaremos el historial de cambios (Tipo 2) |

Estas dimensiones se relacionarán con `FACT_PASOS_RFID`, formando un esquema estrella que nos permitirá analizar los tiempos de los corredores por categoría, checkpoint y edición.

### Pregunta 4: ¿Cuáles son las métricas (hechos)?

Las métricas que utilizaremos en nuestra tabla de hechos son:

| Métrica | Tipo | ¿Para qué sirve? |
|---|---|---|
| Cantidad de pasos RFID | Aditiva | Contar registros por categoría, checkpoint o edición |
| Tiempo acumulado (segundos) | No aditiva | Comparar el tiempo que tardan los corredores en llegar a cada checkpoint, sin sumar tiempos ya acumulados |
| Tiempo por tramo (segundos) | Aditiva para tramos consecutivos | Conocer cuánto tarda un corredor entre dos puntos y sumar sus tramos sin superposición |
| Ritmo por tramo (min/km) | No aditiva | Comparar el rendimiento de los corredores, calculándolo a partir del tiempo y la distancia |

En PostgreSQL ya tenemos el tiempo acumulado de cada corredor. A partir de ese dato calcularemos el tiempo y el ritmo por tramo en la zona Gold.

El tiempo por tramo se obtiene restando el tiempo acumulado del checkpoint anterior al actual. Para el primer checkpoint tomaremos como referencia la salida, con tiempo inicial igual a cero.

El ritmo se calculará así:

**Ritmo (min/km) = (tiempo del tramo / 60) / distancia del tramo**

Por ejemplo, si un corredor llega al K5 en 1.500 segundos y al K10 en 3.200 segundos, tardó **1.700 segundos en recorrer ese tramo de 5 km**, con un ritmo aproximado de **5,67 min/km**.

### Pregunta 5: Estrategia SCD para al menos 1 dimensión

Utilizaremos **SCD Tipo 2 en `DIM_CHECKPOINT`**, porque nos permite conservar los valores anteriores cuando cambia la información de un punto de control.

Para demostrarlo, simularemos que el checkpoint K30 cambia su nombre a KM30 en la edición 2026, manteniendo su distancia de 30 km.

| checkpoint_sk | id_punto | nombre | distancia_km | valido_desde | valido_hasta | activo | Ediciones asociadas |
|---|---|---|---|---|---|---|---|
| 5 | 5 | K30 | 30.0 | 2016-01-01 | 2025-12-31 | false | 2016–2025 |
| 6 | 5 | KM30 | 30.0 | 2026-01-01 | 9999-12-31 | true | 2026 |

En la zona Gold guardaremos ambas versiones con diferentes claves sustitutas (`checkpoint_sk`) y sus respectivas fechas de vigencia (`valido_desde`, `valido_hasta`) y estado (`activo`). Cada registro en `FACT_PASOS_RFID` se relacionará con la clave sustituta de la versión que corresponda a su edición.

De esta manera podremos comprobar que los pasos de las ediciones anteriores (2016–2025) permanecen relacionados con K30 (`checkpoint_sk = 5`), mientras que los de 2026 se relacionan con KM30 (`checkpoint_sk = 6`).

Este cambio será únicamente una simulación en la capa analítica para demostrar SCD Tipo 2. Los datos originales de PostgreSQL no se modificarán.

---

## 2. Arquitectura Medallion y Estructura del Proyecto

Este proyecto que les mostramos, implementa un pipeline analítico **Medallion (Bronze, Silver y Gold)** sobre contenedores Docker, integrando **PostgreSQL 16**, **Python 3.12 (pandas / PyArrow)**, **Apache Parquet** y **DuckDB**:

```text
PostgreSQL (OLTP) --> Bronze (Parquet Crudo + Auditoría) --> Silver (Limpieza + Calidad) --> Gold (Esquema Estrella + SCD2) --> DuckDB (Consultas + Benchmark)
```

### Estructura de Directorios

```text
Taller-3-Maraton-de-Medellin/
├── data/                        # Archivos CSV base (participantes, puntos_control, pasos)
├── docs/
│   ├── Diagrama_lakehouse.png   # Diagrama del Esquema Estrella (dbdiagram.io)
│   └── reporte_calidad.txt      # Reporte estadístico generado automáticamente por Silver
├── lakehouse/
│   ├── bronze/                  # Parquet crudos con sufijo timestamp y metadatos de auditoría
│   ├── silver/                  # Parquet depurados, tipados y validados referencialmente
│   └── gold/                    # Modelo Estrella (4 dimensiones + 1 tabla de hechos Parquet)
├── scripts/
│   ├── init_db.py               # Paso 1: Verifica/genera CSV y pobla PostgreSQL vía COPY
│   ├── extract.py               # Paso 2: Extrae tablas OLTP hacia Zona Bronze (Parquet)
│   ├── transform_silver.py      # Paso 3: Limpia datos, valida calidad y genera Zona Silver
│   ├── transform_gold.py        # Paso 4: Construye Esquema Estrella y SCD Tipo 2 en Zona Gold
│   └── analyze.py               # Paso 5: Ejecuta 5 consultas analíticas en DuckDB y Benchmark
├── sql/                         # Scripts DDL de soporte para inicialización de PostgreSQL
├── docker-compose.yml           # Orquestación de contenedores (db: Postgres 16, app: Python 3.12)
├── Dockerfile                   # Imagen de la aplicación Python y sus dependencias
└── main.py                      # Orquestador CLI del pipeline (completo o modular)
```

---

## 3. Guía de Reproducibilidad (Ejecución desde Cero)

Cualquier usuario externo puede reproducir el proyecto completo desde cero siguiendo unicamente estos pasos.

### 3.1 Requisitos previos

* Tener instalado **Git**.
* Tener instalado **Docker** y **Docker Compose** (por ejemplo, *Docker Desktop* activo).
* Contar con el puerto local `5432` libre para el contenedor de PostgreSQL.

### 3.2 Paso a paso para levantar el entorno y correr el pipeline completo

**1. Clonar el repositorio e ingresar al directorio del proyecto:**

```bash
git clone https://github.com/kevin25255/Taller-3-Maraton-de-Medellin.git
cd Taller-3-Maraton-de-Medellin
```

**2. Construir y levantar los contenedores en segundo plano:**

```bash
docker compose up -d --build
```

*(Puedes verificar que los servicios `db` y `app` estén corriendo correctamente con `docker compose ps`).*

**3. Ejecutar el pipeline completo de extremo a extremo (Pasos 1 al 5):**

```bash
docker compose exec app python main.py
```

Al ejecutar este comando único (~19 segundos en total), el orquestador `main.py` realizará automáticamente:

1. **Paso 1 (`init_db.py`):** Verificación o generación determinística de los archivos CSV y carga por `COPY` en PostgreSQL (**165,000 participantes**, **6 puntos de control** y **585,000 pasos RFID** en las ediciones 2016–2026).
2. **Paso 2 (`extract.py`):** Extracción desde PostgreSQL hacia `lakehouse/bronze/` en archivos Parquet fechados con columnas de auditoría (`_extraido_en` y `_fuente`).
3. **Paso 3 (`transform_silver.py`):** Limpieza, validación de integridad referencial, escritura en `lakehouse/silver/` y generación del archivo `docs/reporte_calidad.txt`.
4. **Paso 4 (`transform_gold.py`):** Creación de las 4 dimensiones (`dim_tiempo.parquet`, `dim_edicion.parquet`, `dim_corredor.parquet`, `dim_checkpoint.parquet` con **SCD Tipo 2** en `K30`/`KM30`) y la tabla de hechos (`fact_pasos_rfid.parquet`) en `lakehouse/gold/`.
5. **Paso 5 (`analyze.py`):** Materialización en memoria de DuckDB, ejecución de las **5 consultas analíticas de negocio** e impresión del **Benchmark PostgreSQL vs. DuckDB**.

---

### 3.3 Comandos de Ejecución Modular (Orquestador CLI y Scripts Individuales)

El orquestador `main.py` soporta argumentos por línea de comandos (`argparse`) para ejecutar fases específicas o consultas puntuales durante la sustentación en vivo:

#### A. Ejecución por Etapas del Pipeline (`--paso`)

| Etapa | Comando mediante `main.py` | Comando directo equivalente | Acción realizada |
|---|---|---|---|
| **Pipeline Completo** | `docker compose exec app python main.py` | — | Corre los Pasos 1 a 5 secuencialmente y se detiene si ocurre algún error. |
| **Paso 1 (OLTP)** | `docker compose exec app python main.py --paso 1` | `docker compose exec app python scripts/init_db.py` | Verifica/genera los CSV y carga las tablas en PostgreSQL. |
| **Paso 2 (Bronze)** | `docker compose exec app python main.py --paso 2` | `docker compose exec app python scripts/extract.py` | Extrae las tablas crudas de PostgreSQL a Parquet en `lakehouse/bronze/`. |
| **Paso 3 (Silver)** | `docker compose exec app python main.py --paso 3` | `docker compose exec app python scripts/transform_silver.py` | Valida calidad, genera Parquet en `lakehouse/silver/` y `docs/reporte_calidad.txt`. |
| **Paso 4 (Gold)** | `docker compose exec app python main.py --paso 4` | `docker compose exec app python scripts/transform_gold.py` | Construye el Esquema Estrella y aplica SCD Tipo 2 en `lakehouse/gold/`. |
| **Paso 5 (Análisis)** | `docker compose exec app python main.py --paso 5` | `docker compose exec app python scripts/analyze.py` | Ejecuta las 5 consultas analíticas en DuckDB y el Benchmark. |

#### B. Ejecución Individual de Consultas Analíticas y Benchmark en DuckDB (`--consulta` / `--benchmark`)

| Consulta / Prueba | Comando mediante `main.py` | Comando directo en `analyze.py` | Descripción del análisis |
|---|---|---|---|
| **Consulta 1** | `docker compose exec app python main.py --consulta 1` | `docker compose exec app python scripts/analyze.py --consulta 1` | Desempeño histórico por edición (2016–2026): pasos totales, tiempo y ritmo promedio. |
| **Consulta 2** | `docker compose exec app python main.py --consulta 2` | `docker compose exec app python scripts/analyze.py --consulta 2` | Tiempos y ritmos por tramo en 42K (curva de fatiga desde `K5` hasta `META`). |
| **Consulta 3** | `docker compose exec app python main.py --consulta 3` | `docker compose exec app python scripts/analyze.py --consulta 3` | Comparación de desempeño (corredores, pasos y ritmo promedio) entre las 6 categorías. |
| **Consulta 4** | `docker compose exec app python main.py --consulta 4` | `docker compose exec app python scripts/analyze.py --consulta 4` | Comprobación de **SCD Tipo 2** en `DIM_CHECKPOINT` (`K30` 2016–2025 vs. `KM30` 2026). |
| **Consulta 5** | `docker compose exec app python main.py --consulta 5` | `docker compose exec app python scripts/analyze.py --consulta 5` | Top 10 corredores más rápidos de la categoría 42K en `META` (Edición 2026). |
| **Benchmark** | `docker compose exec app python main.py --benchmark` | `docker compose exec app python scripts/analyze.py --benchmark` | Compara tiempos de ejecución de la misma consulta agregada en PostgreSQL vs. DuckDB. |

#### C. Inspección de Archivos Generados y Reinicio Limpio del Entorno

* **Ver el Reporte de Calidad Silver en consola:**
  ```bash
  docker compose exec app cat docs/reporte_calidad.txt
  ```
* **Listar los archivos Parquet generados en las tres capas del Lakehouse:**
  ```bash
  docker compose exec app ls -lh lakehouse/bronze lakehouse/silver lakehouse/gold
  ```
* **Reiniciar todo el entorno y la base de datos desde cero (borrando volúmenes):**
  ```bash
  docker compose down -v
  docker compose up -d --build
  docker compose exec app python main.py
  ```

---

## 4. Resumen del Reporte de Calidad (Zona Silver)

Al ejecutar el Paso 3 (`transform_silver.py`), se genera automáticamente el archivo `docs/reporte_calidad.txt` con el siguiente resumen de auditoría sobre el lote más reciente extraído de Bronze:

```text
--- REPORTE DE CALIDAD SILVER ---
Filas Bronze originales (pasos) :    585,000
Filas Silver resultantes (pasos):    585,000
Filas eliminadas                :          0
Duplicados RFID eliminados      :          0
Nulos resueltos                 : 0 -> 0
Porcentaje retenido             :    100.00%
Participantes válidos en Silver :    165,000
Checkpoints válidos en Silver   :          6
Rango de fechas de pasos        : 2016-09-01 07:20:03 -> 2026-09-01 12:52:40
Tiempo acumulado promedio (seg) :   5,183.47
```

---

## 5. Benchmark: PostgreSQL (OLTP) vs. DuckDB (Columnar)

Se evaluó la misma consulta de agregación masiva (agrupación de los **585,000 pasos RFID** por año de edición, categoría y punto de control, generando **231 filas agrupadas** con conteo de lecturas y promedio de tiempo acumulado) tanto en la base de datos operacional **PostgreSQL** como en **DuckDB** sobre el modelo estrella de la Zona Gold:

| Motor | Tiempo medido (`--benchmark`) | Tiempo medido (`main.py` completo) | Filas resultantes | Observación |
|---|---|---|---|---|
| **PostgreSQL 16 (OLTP)** | `186.78 ms` | `233.63 ms` | 231 filas | Consulta operacional por filas (`pasos` JOIN `participantes`). |
| **DuckDB (Columnar)** | `29.68 ms` | `36.06 ms` | 231 filas | Consulta analítica columnar sobre tablas Gold cargadas desde Parquet. |
| **Factor de mejora** | **6.3x más rápido** | **6.5x más rápido** | — | Calculado directamente con las mediciones obtenidas. |

**Análisis del resultado:**  
En las pruebas que ejecutamos, postgreSQL tardó entre `186.78 ms` y `233.63 ms`, mientras que duckDB resolvió la misma agregación en solo `29.68 ms` a `36.06 ms`, logrando ser entre **6.3x y 6.5x más rápido**. Esta ventaja de rendimiento se explica por como trabaja duckDB que es el motor de ejecución columnar vectorizado y por la estructura dimensional de la Zona Gold, los cuales permiten procesar únicamente las columnas involucradas en las agrupaciones y promedios sin necesidad de escanear filas transaccionales completas. Los tiempos corresponden a ejecuciones en el entorno contenedorizado local y puede variar ligeramente según el estado de la memoria cache y los recursos disponibles del equipo en donde se ejecute.
