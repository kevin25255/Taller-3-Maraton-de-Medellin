-- ============================================================
-- 1. PARTICIPANTES
-- ============================================================

CREATE TABLE IF NOT EXISTS participantes (
    id_participante SERIAL PRIMARY KEY,
    chip_id VARCHAR(50) NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    categoria VARCHAR(10) NOT NULL,
    edicion INT NOT NULL,

    CONSTRAINT uq_chip_edicion
        UNIQUE (chip_id, edicion)
);


-- ============================================================
-- 2. PUNTOS DE CONTROL
-- ============================================================

CREATE TABLE IF NOT EXISTS puntos_control (
    id_punto SERIAL PRIMARY KEY,
    nombre VARCHAR(20) NOT NULL UNIQUE,
    distancia_km NUMERIC(6,3) NOT NULL
);


-- ============================================================
-- 3. REGISTROS RFID
-- ============================================================

CREATE TABLE IF NOT EXISTS pasos (
    id_paso BIGSERIAL PRIMARY KEY,

    id_participante INT NOT NULL,
    id_punto INT NOT NULL,

    tiempo_acumulado_segundos INT NOT NULL,

    fecha_registro TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_pasos_participante
        FOREIGN KEY (id_participante)
        REFERENCES participantes(id_participante),

    CONSTRAINT fk_pasos_punto
        FOREIGN KEY (id_punto)
        REFERENCES puntos_control(id_punto),

    CONSTRAINT uq_corredor_punto
        UNIQUE (id_participante, id_punto)
);


INSERT INTO puntos_control (
    id_punto,
    nombre,
    distancia_km
)
VALUES
    (1, 'K5',    5.000),
    (2, 'K10',  10.000),
    (3, 'K15',  15.000),
    (4, 'K21',  21.000),
    (5, 'K30',  30.000),
    (6, 'META', 42.195)
ON CONFLICT DO NOTHING;


-- ============================================================
-- 5. SINCRONIZAR SECUENCIA DE CHECKPOINTS
-- ============================================================

SELECT setval(
    pg_get_serial_sequence(
        'puntos_control',
        'id_punto'
    ),
    (SELECT MAX(id_punto) FROM puntos_control)
);