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
