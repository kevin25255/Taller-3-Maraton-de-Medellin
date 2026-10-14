# ============================================================
# TALLER 3 - MARATON DE MEDELLIN
# Contenedor Python para el Mini-Lakehouse.
# ============================================================

FROM python:3.12-slim

# Directorio de trabajo del proyecto.
WORKDIR /app

# Evitar archivos temporales de Python y salida almacenada.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instalar las dependencias de la guia.
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# El codigo del proyecto se montara desde Docker Compose.
# Mantenemos el contenedor disponible para ejecutar cada paso.
CMD ["sleep", "infinity"]
