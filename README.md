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

