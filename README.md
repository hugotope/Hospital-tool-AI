# Hospital Tool AI

Estructura base del proyecto para evolucionar a una aplicacion completa con frontend web y backend Python.

## Estructura

- `front-end/`: interfaz web (HTML, CSS, JS)
- `back-end/`: API en Python (Flask)
- `models-ia/`: espacio para modelos, notebooks y experimentos
- `healthcare_dataset_100k.csv`: dataset principal

## Credenciales de acceso (demo)

- Usuario: `admin`
- Contrasena: `1234`

## Ejecutar frontend

Abre `front-end/index.html` con un servidor local (recomendado) o desde navegador.

## Ejecutar backend (Python)

1. Crea entorno virtual e instala dependencias:
   - `pip install -r back-end/requirements.txt`
2. Inicia servidor:
   - `python back-end/app.py`
3. Endpoint de preview:
   - `http://127.0.0.1:8000/api/dataset/preview?rows=12`

## Ejecutar con Docker (recomendado)

1. Construir y levantar contenedores:
   - `docker compose up --build`
2. Abrir aplicacion:
   - `http://localhost`
3. Credenciales demo:
   - Usuario: `admin`
   - Contrasena: `1234`

Comandos utiles:

- Detener contenedores:
  - `docker compose down`
- Ver logs:
  - `docker compose logs -f`

## Configuracion local

Variables opcionales del backend:

- `HOSPITAL_HOST`: host de Flask. Por defecto `127.0.0.1`.
- `HOSPITAL_PORT`: puerto de Flask. Por defecto `8000`.
- `HOSPITAL_DEBUG`: usa `1` solo para desarrollo local. Por defecto desactivado.
- `HOSPITAL_CORS_ORIGINS`: origenes permitidos separados por coma.
- `HOSPITAL_MAX_UPLOAD_MB`: limite de subida de CSV en MB. Por defecto `25`.

Para tests:

- `pip install -r back-end/requirements-dev.txt`
- `pytest`

Para entrenamiento con Spark opcional:

- `pip install -r models-ia/requirements-train.txt`
