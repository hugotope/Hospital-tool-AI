# Hospital Tool AI

Portal clinico inteligente para hospitales: ingesta de datasets, prediccion de
enfermedades y nivel de riesgo, deteccion de anomalias, clasificacion de
radiografias por CNN y gestion de pacientes, doctores y usuarios.

El stack se levanta entero con Docker Compose (PostgreSQL + MongoDB + Flask +
Nginx) y se accede desde el navegador con un panel multi-idioma (ES / EN / CA).

---

## Indice

1. [Arquitectura](#arquitectura)
2. [Estructura del repositorio](#estructura-del-repositorio)
3. [Como funciona (flujos principales)](#como-funciona-flujos-principales)
4. [Arranque rapido con Docker](#arranque-rapido-con-docker)
5. [Arranque manual sin Docker](#arranque-manual-sin-docker)
6. [Variables de entorno](#variables-de-entorno)
7. [API HTTP](#api-http)
8. [Modelos de IA](#modelos-de-ia)
9. [Pipeline ETL](#pipeline-etl)
10. [Tests](#tests)
11. [Credenciales demo](#credenciales-demo)

---

## Arquitectura

```
                       ┌─────────────────────────────┐
   Navegador  ────────▶│  Frontend (Nginx + HTML/JS) │  http://localhost:8888
                       └──────────────┬──────────────┘
                                      │  /api/*  (proxy_pass)
                                      ▼
                       ┌─────────────────────────────┐
                       │  Backend Flask (Python)     │  http://localhost:8000
                       │  - Auth + sesiones          │
                       │  - Pipeline ETL (pandas)    │
                       │  - Predictor sklearn        │
                       │  - Predictor CNN (Keras)    │
                       └───────┬────────────┬────────┘
                               │            │
                  ┌────────────▼─┐      ┌───▼──────────────┐
                  │ PostgreSQL 15│      │ MongoDB 7        │
                  │ usuarios     │      │ GridFS imagenes  │
                  │ pacientes    │      │ radiologia       │
                  │ doctores     │      │ historial CNN    │
                  │ diagnosticos │      └──────────────────┘
                  │ notif.       │
                  └──────────────┘
```

Componentes:

- **Frontend**: HTML estatico + JS vanilla + Chart.js, servido por Nginx que
  hace `proxy_pass` de `/api/` al backend.
- **Backend Flask** (`back-end/app.py`): API REST con autenticacion por token
  Bearer, CORS configurable y endpoints de dataset, IA, radiologia,
  pacientes, doctores, usuarios, notificaciones e informe.
- **PostgreSQL**: usuarios, pacientes, doctores, enfermedades, sintomas,
  notificaciones (esquema en `back-end/database.py`).
- **MongoDB + GridFS**: almacena imagenes radiologicas y registros del modulo
  dental (`back-end/mongo_radiology.py`, `back-end/mongodb_client.py`).
- **Modelos IA**:
  - `models-ia/train_spark.py`: RandomForest (enfermedad + riesgo) +
    IsolationForest (anomalias), bundle `.joblib`.
  - `models-ia/train_cnn.py`: MobileNetV2 transfer-learning para
    radiografias de torax (Sana / Neumonia / COVID-19).

---

## Estructura del repositorio

```
Hospital-tool-AI/
├── back-end/
│   ├── app.py                # Flask app + todos los endpoints /api/*
│   ├── database.py           # Esquema PostgreSQL y queries
│   ├── pipeline.py           # ETL: ingesta -> limpieza -> transformacion -> EDA
│   ├── logging_config.py     # Logging centralizado (stdout + hospital-ai.log)
│   ├── ai_predictor.py       # Inferencia sklearn (enfermedad/riesgo/anomalia)
│   ├── cnn_predictor.py      # Inferencia Keras (radiografias)
│   ├── mongodb_client.py     # Cliente Mongo compartido
│   ├── mongo_radiology.py    # Capa Mongo+GridFS para radiologia/dental
│   ├── requirements.txt      # Dependencias de runtime
│   ├── requirements-dev.txt  # pytest (solo dev/tests)
│   └── Dockerfile
├── front-end/
│   ├── index.html            # Login + panel (sidebar + main)
│   ├── css/style.css
│   ├── js/
│   │   ├── app.js            # Logica de paginas (renderDashboard, renderDiagnosis, ...)
│   │   ├── charts.js         # Wrappers de Chart.js (bar/doughnut/line)
│   │   └── i18n.js           # Diccionarios ES / EN / CA
│   ├── nginx.conf            # Servidor estatico + proxy /api/ -> backend:8000
│   └── Dockerfile
├── models-ia/
│   ├── train_spark.py        # Entrena RandomForest + IsolationForest -> .joblib
│   ├── train_cnn.py          # Entrena MobileNetV2 -> .keras
│   ├── models/               # Salida (joblib, keras, metrics.json) — no versionado
│   ├── requirements-train.txt
│   └── README.md
├── scripts/
│   └── verify_cnn.py         # Sanity check del modelo CNN sobre imagenes locales
├── tests/
│   └── test_app_core.py      # Tests pytest sobre app.py (requiere Postgres)
├── healthcare_dataset_100k.csv  # Dataset por defecto (100k filas sinteticas)
├── docker-compose.yml        # Stack completo (mongo, db, backend, frontend)
├── start_server.bat          # Lanzador Windows (Docker Desktop + navegador)
├── .gitignore
└── .dockerignore
```

---

## Como funciona (flujos principales)

### Login y sesiones

1. El usuario entra en `http://localhost:8888/` y ve la pagina de login
   (`front-end/index.html`).
2. `POST /api/auth/login` con `{username, password}` devuelve un `token`.
3. El frontend lo guarda en memoria y lo envia en `Authorization: Bearer ...`
   en todas las llamadas siguientes.
4. Las sesiones se mantienen en memoria del proceso Flask
   (`database._sessions`).

### Subida de dataset y ejecucion del pipeline

1. Admin sube un CSV en la seccion **Dataset**
   (`POST /api/dataset/upload`) -> se guarda en `uploaded_datasets/`.
2. El frontend ejecuta automaticamente `POST /api/dataset/pipeline` con el
   path activo.
3. `back-end/pipeline.py` corre 4 etapas y devuelve metadatos por etapa:
   - **Ingesta**: lee el CSV, valida columnas obligatorias
     (`Age`, `Gender`, `Symptoms`, `Diagnosis`).
   - **Limpieza**: elimina duplicados, NAs criticos, edades fuera de
     rango (0-120), normaliza textos y genero.
   - **Transformacion**: codifica genero, crea bins de edad
     (`0-17`, `18-34`, `35-54`, `55-74`, `75+`), traduce sintomas ES→EN.
   - **Analisis (EDA)**: distribucion de diagnosticos, edades, sintomas
     top, edad media por diagnostico.
4. El frontend pinta cada etapa con su estado y tiempo (`elapsed_ms`).

### Diagnostico IA (paciente)

1. El medico introduce nombre, edad, genero y sintomas en
   **Diagnostico IA**.
2. `POST /api/ai/analyze` llama internamente al `HealthcarePredictor`:
   - `predict_disease()`: top-5 enfermedades + confianza.
   - `classify_risk()`: nivel Low/Medium/High + recomendaciones.
   - `anomaly_score()`: IsolationForest sobre el mismo vector TF-IDF.
3. Opcionalmente se guarda el paciente en PostgreSQL
   (`patients` + diagnostico y nivel de riesgo).

### Radiografias (CNN)

1. Admin entrena el modelo:

   ```bash
   python models-ia/train_cnn.py --epochs 12 --no-mongo
   ```

   Salida: `models-ia/models/cnn_xray_model.keras` +
   `cnn_metrics.json`.

2. En **Radiografias** el usuario sube un JPG/PNG.
3. `POST /api/cnn/predict` corre `CNNPredictor.predict()`:
   - Preprocesa la imagen (224x224, RGB, normalizada).
   - Clasifica en `normal` / `pneumonia` / `covid`.
   - Si confianza ≥ 0.60 y la clase es contagiosa, emite alerta clinica
     (mensaje sugerido para el equipo).
4. La imagen se guarda en MongoDB (GridFS) con metadatos.

### Notificaciones

El backend genera eventos al subir datasets, ejecutar el pipeline o detectar
alertas. El frontend los pinta en el campanito superior
(`GET /api/notifications`).

### Informe del sistema

`GET /api/report/view` (con `?access_token=...`) devuelve un HTML imprimible
con el estado actual: KPIs, EDA, metricas de los modelos, top
diagnosticos y top zonas. El boton de **Informe** del menu lo abre en una
pestana nueva.

---

## Arranque rapido con Docker

**Requisitos**: Docker Desktop instalado y arrancado.

```bash
docker compose up -d --build
```

URLs:

- Portal: <http://localhost:8888/>
- API health: <http://localhost:8000/api/health>

Comandos utiles:

```bash
docker compose logs -f backend  # Logs en vivo (stdout)
docker compose down             # Para todo
docker compose down -v          # Para y borra volumenes (datos)
```

Logs persistentes: volumen Docker `hospital_logs` → `logs/hospital-ai.log`
(fichero rotativo dentro del contenedor backend).

**Atajo en Windows**: doble clic en `start_server.bat`. El script:

1. Verifica Docker y `docker compose`.
2. Descarga las imagenes base (con espejo alternativo si Cloudflare
   falla).
3. Levanta el stack y espera a que `/api/health` responda 200.
4. Abre el navegador automaticamente.

---

## Arranque manual sin Docker

Pensado para desarrollo del backend con una base de datos local ya en
marcha.

```bash
# 1. Crear entorno e instalar dependencias
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate      # Linux/macOS
pip install -r back-end/requirements.txt

# 2. Exportar variables (apuntando a tu Postgres y Mongo locales)
$env:DATABASE_URL = "postgresql://hospital:hospital@127.0.0.1:5432/hospital"
$env:MONGO_URI    = "mongodb://hospital:hospital@127.0.0.1:27017/?authSource=admin"

# 3. Arrancar la API
python back-end/app.py
```

El frontend puede abrirse directamente con cualquier servidor estatico que
sirva la carpeta `front-end/` (por ejemplo `python -m http.server 5500`
desde dentro de la carpeta). Configura `HOSPITAL_CORS_ORIGINS` para
permitir el origen desde el que sirvas el HTML.

---

## Variables de entorno

Todas son opcionales (tienen default).

| Variable                     | Default                                                            | Descripcion                                                |
| ---------------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------- |
| `DATABASE_URL`               | `postgresql://hospital:hospital@localhost:5432/hospital`           | Conexion PostgreSQL                                        |
| `MONGO_URI`                  | `mongodb://hospital:hospital@localhost:27017/?authSource=admin`    | Conexion MongoDB                                           |
| `MONGO_DB`                   | `hospital_ai`                                                      | Base general en Mongo                                      |
| `MONGO_DB_RADIOLOGY`         | `medai_radiology`                                                  | Base para estudios radiologicos                            |
| `MONGO_DB_DENTAL`            | `medai_dental`                                                     | Base para estudios dentales                                |
| `HOSPITAL_HOST`              | `127.0.0.1` (en Docker `0.0.0.0`)                                  | Host de Flask                                              |
| `HOSPITAL_PORT`              | `8000`                                                             | Puerto de Flask                                            |
| `HOSPITAL_DEBUG`             | `0`                                                                | `1` activa modo debug                                      |
| `HOSPITAL_CORS_ORIGINS`      | `http://127.0.0.1:5500,http://localhost:5500,null`                 | Orígenes permitidos (lista separada por comas)             |
| `HOSPITAL_MAX_UPLOAD_MB`     | `25`                                                               | Limite de subida de CSV en MB                              |
| `HOSPITAL_MAX_RADIOLOGY_MB`  | `100` (Docker `120`)                                               | Limite de subida de imagenes en MB                         |
| `HOSPITAL_LOG_DIR`           | `logs/` (en Docker `/app/logs`)                                    | Directorio de logs rotativos                               |
| `HOSPITAL_LOG_LEVEL`         | `INFO`                                                             | Nivel de logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`)     |

---

## API HTTP

Resumen de endpoints (todos bajo `/api/`). Los marcados `auth` requieren
token Bearer; los marcados `admin` requieren rol administrador.

**Publicos**

- `GET  /health` — Estado de la API y modelos.
- `POST /auth/login` — Login con `username` + `password`.

**Sesion**

- `POST /auth/logout` *(auth)*
- `GET  /auth/me` *(auth)*

**Dataset**

- `GET  /dataset/preview` *(auth)*
- `GET  /dataset/stats` *(auth)*
- `GET  /dataset/list` *(auth)*
- `POST /dataset/activate` *(auth)*
- `POST /dataset/upload` *(auth)*
- `POST /dataset/pipeline` *(auth)*

**Pacientes**

- `GET  /patients` *(auth)*
- `GET  /patients/search` *(auth)*
- `GET  /patients/<id>` *(auth)*
- `GET  /patients/eda` *(auth)*
- `POST /patients/import-dataset` *(admin)*

**Enfermedades / sintomas**

- `GET  /diseases` *(auth)*
- `POST /diseases` *(auth)*
- `GET  /diseases/symptoms` *(auth)*
- `POST /translate/symptoms` *(auth)*

**IA (sklearn)**

- `POST /ai/analyze` *(auth)*
- `POST /ai/predict-disease` *(auth)*
- `POST /ai/classify-risk` *(auth)*
- `GET  /ai/model-info` *(auth)*
- `POST /ai/train` *(admin)*
- `GET  /ai/train-status` *(auth)*

**CNN (radiografias)**

- `POST /cnn/predict` *(auth)*
- `GET  /cnn/model-info` *(auth)*
- `GET  /cnn/history` *(auth)*
- `GET  /cnn/stats` *(auth)*
- `POST /cnn/train` *(admin)*
- `GET  /cnn/train-status` *(auth)*

**Radiologia (Mongo/GridFS)**

- `POST /radiology/upload` *(auth)*
- `GET  /radiology/list` *(auth)*

**Analitica**

- `GET  /analytics/overview` *(auth)*
- `GET  /analytics/patterns` *(auth)*
- `GET  /analytics/anomalies` *(auth)*

**Doctores**

- `GET  /doctors` *(auth)*
- `POST /doctors` *(admin)*
- `PUT  /doctors/<id>` *(admin)*

**Usuarios (solo admin)**

- `GET    /users`
- `POST   /users`
- `DELETE /users/<id>`

**Notificaciones**

- `GET    /notifications` *(auth)*
- `POST   /notifications/read` *(auth)*
- `DELETE /notifications` *(auth)*

**Informe imprimible**

- `GET  /report/view` *(auth, admite `?access_token=`)*

---

## Modelos de IA

### 1) Modelo tabular (`train_spark.py`)

RandomForest entrenado sobre `healthcare_dataset_100k.csv`. Produce:

- `models-ia/models/healthcare_models.joblib` — bundle con TF-IDF, label
  encoders, RandomForest de enfermedad, RandomForest de riesgo e
  IsolationForest.
- `models-ia/models/metrics.json` — accuracy, F1, cross-validation
  5-fold y classification report.

Tecnicas anti-overfitting incluidas:

- **Symptom dropout**: elimina aleatoriamente 1-2 sintomas por fila en
  entrenamiento para simular historias clinicas incompletas.
- **Ruido de etiqueta** (5%) en el nivel de riesgo para reflejar la
  incertidumbre clinica.
- Se excluye `days_stayed` del vector de features (no esta disponible en
  admision).

Entrenar manualmente:

```bash
pip install -r models-ia/requirements-train.txt   # incluye pyspark (opcional)
python models-ia/train_spark.py --dataset healthcare_dataset_100k.csv
```

### 2) CNN para radiografias (`train_cnn.py`)

MobileNetV2 con transfer learning sobre ImageNet, clasificacion en 3
clases: `normal`, `pneumonia`, `covid`.

Datasets esperados bajo `datasets/`:

- `datasets/covid19/dataset_3_classes` — covid / normal / pneumonia_bac
- `datasets/covid19/dataset_4_classes` — anade pneumonia_vir (fusionada
  en pneumonia)
- `datasets/pneumonia/chest_xray` — NORMAL / PNEUMONIA

Entrenar:

```bash
pip install tensorflow pillow scikit-learn
python models-ia/train_cnn.py --epochs 12 --no-mongo
```

Salida:

- `models-ia/models/cnn_xray_model.keras`
- `models-ia/models/cnn_metrics.json`

Verificar sobre imagenes locales:

```bash
python scripts/verify_cnn.py
```

---

## Pipeline ETL

El modulo `back-end/pipeline.py` implementa el pipeline al estilo Big Data en
4 etapas. Cada etapa devuelve un dict con `ok`, metricas y `elapsed_ms`, lo
que permite al frontend pintar el progreso etapa por etapa.

| Etapa            | Funcion        | Que hace                                                                              |
| ---------------- | -------------- | ------------------------------------------------------------------------------------- |
| Ingesta          | `ingest`       | Lee CSV (UTF-8 con fallback latin-1), valida columnas y tamano                        |
| Limpieza         | `clean`        | Duplicados, NAs criticos, edades 0-120, normaliza Gender, sintomas y diagnostico      |
| Transformacion   | `transform`    | Codifica genero, bins de edad, traduce sintomas con `translate_symptoms` (ES→EN)      |
| Analisis (EDA)   | `analyze`      | Distribucion diagnosticos, edades, sintomas top, edad media por diagnostico           |

El orquestador `run_pipeline(path, translator)` corta tempranamente si una
etapa falla (`ok: false`) y devuelve `{ok, stages, summary}` serializable a JSON.
Cada etapa incluye `quality_checks` (columnas obligatorias, duplicados, nulos,
edades fuera de rango, normalizacion de sintomas).

Endpoint: `POST /api/dataset/pipeline` (auth).

---

## Logging, alertas y monitorizacion

- **Logging centralizado**: `back-end/logging_config.py` — `setup_logging()` al
  arrancar; loggers `hospital_ai.pipeline`, `.training`, `.notifications`, `.health`.
- **Salida**: stdout (`docker logs hospital-ai-backend`) + `logs/hospital-ai.log`
  (rotativo, volumen `hospital_logs`).
- **Alertas**: `_notify()` en `app.py` registra por severidad, persiste en
  PostgreSQL (`notifications`) y se muestran en el dashboard (`GET /api/notifications`).
- **CNN**: alertas clinicas automaticas en COVID-19/neumonia con alta confianza.
- **Anomalias**: IsolationForest via `GET /api/analytics/anomalies`.
- **Healthchecks**: Postgres, Mongo y Flask en `docker-compose.yml` (`GET /api/health`).

---

## Tests

Los tests usan `pytest` y necesitan PostgreSQL accesible (si no, se
skipean automaticamente).

```bash
pip install -r back-end/requirements-dev.txt
docker compose up -d db          # o tu Postgres local
pytest
```

Cubren autenticacion del endpoint de informe, creacion de enfermedades,
resolucion del dataset activo e importacion de pacientes.

---

## Credenciales demo

Se crea automaticamente al iniciar el backend
(`db.ensure_default_doctors()` + bootstrap de usuarios admin):

- Usuario: `admin`
- Contrasena: `1234`

Cambia ambos antes de exponer el servicio fuera de localhost.
