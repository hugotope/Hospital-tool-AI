# MedAI Hospital — Informe técnico del sistema

> Documento funcional que explica cómo funciona la plataforma MedAI Hospital:
> arquitectura, modelos IA, endpoints, anti-data-leakage, i18n y despliegue.

---

## 1. Resumen ejecutivo

MedAI Hospital es una plataforma clínica que asiste al personal médico en:

| Capacidad | Cómo se implementa |
|---|---|
| **Análisis de datos clínicos / operativos** | Endpoints `/api/analytics/overview`, `/api/analytics/patterns`, `/api/dataset/stats` |
| **Identificación de patrones, anomalías y clasificaciones** | `/api/analytics/patterns` (co-ocurrencia), `/api/analytics/anomalies` (IsolationForest), `/api/ai/analyze` (clasificación multiclase) |
| **Automatización de tareas repetitivas** | Diagnóstico + triaje + asignación de zona/médico + persistencia en un solo click |
| **Generación de información para toma de decisiones** | KPIs en dashboard, informe PDF (`/api/report/view`), EDA en tiempo real |
| **Clasificación de pacientes** | `RandomForest` sobre síntomas + edad + género → `Low/Medium/High` |
| **Predicción de enfermedades** | `RandomForest` + `TF-IDF` sobre síntomas → top-5 diagnósticos |

---

## 2. Arquitectura

```
┌─────────────────┐        ┌──────────────┐        ┌──────────────┐
│  Frontend SPA   │ <───>  │  Flask API   │ <───>  │  SQLite DB   │
│  (HTML/CSS/JS)  │  JSON  │  Python 3.13 │  ORM   │  hospital.db │
│  i18n ES/EN/CA  │        │              │        └──────────────┘
│  Chart.js v4    │        │              │
└─────────────────┘        │              │        ┌──────────────┐
                           │              │ <───── │ pipeline.py  │
                           │              │  ETL   │ pandas       │
                           │              │        └──────────────┘
                           │              │        ┌──────────────┐
                           │              │ <───── │ sklearn      │
                           │              │        │ RandomForest │
                           │              │        │ + TF-IDF     │
                           │              │        │ + IsoForest  │
                           └──────────────┘        └──────────────┘
```

- **Backend**: Flask, `back-end/app.py`
- **Pipeline ETL**: `back-end/pipeline.py` (ingesta → limpieza → transformación → análisis)
- **Predicción**: `back-end/ai_predictor.py` (wrapper thread-safe sobre el bundle `.joblib`)
- **Entrenamiento**: `models-ia/train_spark.py` (sklearn con fallback PySpark)
- **Persistencia**: `back-end/database.py` (SQLite + tabla `patients` + búsqueda incremental)
- **Frontend**: `front-end/index.html` + `css/style.css` + `js/app.js` + `js/i18n.js` + `js/charts.js`

---

## 3. Modelos de Machine Learning

### 3.1 Clasificador de enfermedades
- Algoritmo: `RandomForestClassifier(n_estimators=120, max_depth=10, min_samples_leaf=5)`
- Features: `TF-IDF(ngram 1-2, max_features=400, min_df=2)` + `age` + `gender_enc`
- 10 clases: Heart Disease, Hypertension, Cancer, Diabetes, COVID-19, Stroke, Asthma, Kidney Disease, Liver Disease, Depression

### 3.2 Clasificador de riesgo
- Algoritmo: `RandomForestClassifier(max_depth=8, min_samples_leaf=10)` — más regularizado para evitar overfitting
- Target: `Low / Medium / High` derivado de `assign_risk(diagnosis, age, days_stayed)`
- **Importante**: `days_stayed` no se usa como feature en inferencia

### 3.3 Detector de anomalías
- Algoritmo: `IsolationForest(n_estimators=120, contamination=0.02)`
- Marca pacientes cuyo perfil clínico (sintomatología + edad + género) es estadísticamente atípico

---

## 4. 🔥 Metodología de evaluación honesta (anti-data-leakage)

**Problema original detectado**: el modelo reportaba **100% accuracy**. Eso es clínicamente imposible.

**Causas identificadas**:

1. El dataset sintético mapea síntomas a diagnóstico de forma **casi determinista**
   (cada enfermedad siempre tiene exactamente los mismos síntomas).
2. La variable `risk_level` se **derivaba algorítmicamente** de
   `(diagnosis, age, days_stayed)`. Pasábamos los 3 al modelo → data leakage total.
3. `days_stayed` se usaba en entrenamiento pero no existe al momento de
   admitir un paciente (en inferencia lo forzábamos a 0 → distribution shift).

**Correcciones aplicadas** (en `models-ia/train_spark.py`):

| Corrección | Efecto |
|---|---|
| **Eliminar `days_stayed`** de las features | Consistencia train/inference |
| **Symptom dropout** (`keep_prob=0.65`) | Simula historia clínica incompleta |
| **5% label noise** en target de riesgo | Simula incertidumbre clínica |
| Regularización mayor (`min_samples_leaf=10`, `max_depth=8`) | Evita memorización |
| **Validación cruzada 3-fold** estratificada | Métricas más robustas |

**Resultado** (entrenamiento sobre 100.000 registros):

| Modelo | Accuracy (test) | F1 weighted | CV accuracy |
|---|---|---|---|
| **Enfermedades** | **88.29%** | 89.37% | **88.52% ± 0.03%** |
| **Riesgo** | **71.50%** | 73.05% | **72.59% ± 0.66%** |

Valores realistas, reproducibles y sin leakage.

---

## 5. Clasificación de pacientes

Cada diagnóstico predicho se mapea automáticamente a una zona hospitalaria y un
médico especialista (`DIAGNOSIS_ASSIGNMENTS` en `app.py`):

| Diagnóstico | Zona | Médico |
|---|---|---|
| Heart Disease | Cardiología | Dr. Andrés Morales |
| Hypertension | Cardiología | Dra. Laura Castillo |
| Stroke | Neurología | Dr. Javier Rojas |
| Asthma | Neumología | Dra. Sofía Ibáñez |
| COVID-19 | Infectología | Dr. Miguel Torres |
| Diabetes | Endocrinología | Dra. Daniela Paredes |
| Kidney Disease | Nefrología | Dr. Ricardo Méndez |
| Liver Disease | Hepatología | Dra. Paula Jiménez |
| Cancer | Oncología | Dr. Sebastián Vega |
| Depression | Salud Mental | Dra. Valeria Núñez |
| Otros | Medicina General | Dr. Equipo de Guardia |

Al invocar `POST /api/ai/analyze` con `save: true` (por defecto), el paciente se
persiste en la tabla `patients` de SQLite con todos los campos calculados.

---

## 6. Endpoints de la API

### Públicos
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado del servicio + modelos cargados |
| POST | `/api/auth/login` | Login. Devuelve token |
| GET | `/api/report/view` | Informe HTML imprimible a PDF |

### Autenticados
| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/auth/logout` | Cierra sesión |
| POST | `/api/ai/analyze` | Diagnóstico + riesgo + anomalía + persistencia |
| POST | `/api/ai/predict-disease` | Solo enfermedad |
| POST | `/api/ai/classify-risk` | Solo riesgo |
| GET | `/api/ai/model-info` | Métricas del modelo |
| POST | `/api/translate/symptoms` | ES → EN |
| GET | `/api/diseases` | Catálogo del dataset |
| GET | `/api/dataset/list` | Datasets disponibles |
| GET | `/api/dataset/preview` | Preview de filas |
| GET | `/api/dataset/stats` | Stats del dataset |
| GET | `/api/patients` | Lista pacientes guardados |
| GET | `/api/patients/eda` | EDA de pacientes |
| GET | `/api/analytics/overview` | KPIs del sistema |
| GET | `/api/analytics/patterns` | Co-ocurrencia de síntomas + edad por diagnóstico |
| GET | `/api/analytics/anomalies` | Pacientes atípicos detectados |
| GET | `/api/patients/search?q=…` | Búsqueda incremental (autocomplete) por nombre o ID |
| GET | `/api/patients/<id>` | Informe completo de un paciente (con anomalía y recomendaciones) |
| POST | `/api/dataset/pipeline` | Ejecuta el pipeline ETL (ingesta → limpieza → transformación → análisis) |

### Solo admin
| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/ai/train` | Reentrena el modelo con un dataset seleccionado |
| GET | `/api/ai/train-status` | Estado del entrenamiento en curso |
| POST | `/api/dataset/upload` | Sube un CSV nuevo |
| POST | `/api/patients/import-dataset` | Importa masivamente pacientes a SQL |
| GET/POST/DELETE | `/api/users[/id]` | Gestión de usuarios |

---

## 7. Interfaz de usuario

### Secciones disponibles
- **Dashboard** — KPIs globales, accesos rápidos
- **Diagnóstico IA** — Formulario de paciente con chips de síntomas comunes
- **Pacientes** — Listado de pacientes guardados + importación masiva
- **Enfermedades** — Catálogo del dataset con síntomas frecuentes
- **Análisis** — Patrones de co-ocurrencia y edad media por diagnóstico
- **Anomalías** — Pacientes clínicamente atípicos detectados
- **Dataset** — Gestión de CSVs (drag & drop + listado)
- **Modelo** — Métricas honestas + botón de reentrenamiento con dataset a elegir
- **Usuarios** — Gestión de cuentas (solo admin)
- **Informe** — Visor embebido del informe + botón de imprimir a PDF

### Internacionalización
- Idiomas: **Español (es)**, **Inglés (en)**, **Catalán (ca)**
- Selector disponible en la pantalla de login y en la barra superior
- Persistencia en `localStorage` (`medai_lang`)
- Implementación en `front-end/js/i18n.js`

### Diseño
- Paleta corporativa: navy `#0b1220`, primario teal `#0f766e`, acento sky `#0ea5e9`
- Tipografía: Inter / Segoe UI / system sans
- Sidebar dark 248px, contenido principal claro, cards con `shadow-xs`
- Responsive (sidebar colapsable en mobile)

---

## 8. Puesta en marcha

```bash
# 1. Instalar dependencias
pip install flask scikit-learn pandas numpy scipy joblib

# 2. Entrenar modelos (primera vez)
python models-ia/train_spark.py --dataset healthcare_dataset_100k.csv

# 3. Arrancar backend
python back-end/app.py     # http://127.0.0.1:8000

# 4. Abrir el frontend
# Abrir front-end/index.html en el navegador
# (o servirlo con:  python -m http.server 5500 --directory front-end)
```

Credenciales demo: **admin / 1234**.

---

## 9. Generación del informe PDF

Hay tres formas de obtener un PDF del sistema:

1. **Desde la app**: sección **Informe** → botón "Imprimir / Guardar PDF".
2. **Directo en navegador**: abrir `http://127.0.0.1:8000/api/report/view`
   y usar `Ctrl+P` → "Guardar como PDF".
3. **Automatizado** (requiere Chrome):
   ```
   chrome --headless --disable-gpu --print-to-pdf=informe.pdf http://127.0.0.1:8000/api/report/view
   ```

---

## 10. Pipeline ETL y arquitectura Big Data

### 10.1 Pipeline de datos (`back-end/pipeline.py`)

Cada vez que se sube un dataset nuevo (o se pulsa el botón **Ejecutar pipeline** en la
sección *Dataset*), se ejecutan en orden cuatro etapas que devuelven un reporte
estructurado con tiempo por etapa y estadísticas:

```
   [ Ingesta ]  ─▶  [ Limpieza ]  ─▶  [ Transformación ]  ─▶  [ Análisis ]
        │              │                    │                      │
        ▼              ▼                    ▼                      ▼
  rows_raw,       duplicates,         Gender_enc,             diagnosis_dist,
  size_kb,        missing_critical,   Age_bin,                age_bins,
  columns,        age_outliers,       Symptoms_en,            gender_dist,
  required_ok    dropout_pct          features, count         top_symptoms,
                                                              age_by_dx
```

| Etapa | Responsabilidad | Función |
|---|---|---|
| **Ingesta** | Lectura del CSV (UTF-8/Latin-1), validación de columnas obligatorias (`Age, Gender, Symptoms, Diagnosis`), tamaño, nº de filas | `pipeline.ingest(path)` |
| **Limpieza** | Elimina duplicados, NAs en columnas críticas, edades inválidas/outliers (`<0` o `>120`), normaliza texto y género | `pipeline.clean(df)` |
| **Transformación** | Codifica género, crea bins de edad, traduce síntomas al inglés (vía `translate_symptoms`), genera feature `Symptoms_count` | `pipeline.transform(df, translator)` |
| **Análisis** | EDA: distribución de diagnósticos/género/edad, top síntomas, edad media por diagnóstico | `pipeline.analyze(df)` |

El resultado de cada etapa incluye `elapsed_ms` para medir rendimiento, y la UI
(sección **Dataset**) dibuja una tarjeta por etapa con estado (ok / running / err)
más gráficos Chart.js derivados del análisis.

### 10.2 Dashboards y visualización automática

El frontend incluye **Chart.js v4** (`front-end/js/charts.js`) con wrappers
`bar`, `pie`, `doughnut`, `line` que se alimentan directamente de los endpoints:

- **Dashboard**: 5 gráficos automáticos (diagnósticos top, zonas, riesgos, género, edad).
- **Pipeline**: 4 gráficos (diagnósticos, bins de edad, género, síntomas top).
- Todos los ejes y tooltips se internacionalizan vía `tDx / tZone / tRisk / tGender / tSym`.

### 10.3 Búsqueda incremental de pacientes

- Endpoint `GET /api/patients/search?q=<fragmento>`
  - Coincidencia por `LIKE '%q%'` sobre `patient_name` o igualdad exacta de `id`.
  - Límite configurable (≤ 100).
- Endpoint `GET /api/patients/<id>` devuelve toda la información del paciente,
  enriquecida con `anomaly_score`, recomendaciones de triaje y la asignación
  (zona + médico).
- UI: input tipo `search` con *debounce* de 180 ms. Cada pulsación filtra en
  vivo y al hacer click en un resultado se renderiza un **Informe del paciente**
  con síntomas, diagnóstico, riesgo, zona, médico, confianza y metadatos;
  el botón *Imprimir* abre una ventana lista para `Ctrl+P` → PDF.

### 10.4 Principios Big Data aplicados

La arquitectura respeta las **5 V** del Big Data:

| Dimensión | Cómo se aborda en MedAI Hospital |
|---|---|
| **Volume** | Pipeline por lotes con pandas (soporta >100k filas), SQLite indexado por `diagnosis / zone / created_at`, paginación en listados (`limit` ≤ 1000). El código está preparado para escalar a PySpark (`models-ia/train_spark.py`) sin cambios de interfaz. |
| **Velocity** | Lectura *streaming*-friendly (`csv.DictReader` / `pd.read_csv(chunksize)`), endpoints asíncronos para entrenamiento (`threading.Thread`), búsqueda incremental con debounce (<200 ms), caches en memoria para catálogos de enfermedades. |
| **Variety** | Ingesta multi-codificación (UTF-8/Latin-1), normalización de género (`M/F/Masculino/Femenino → Male/Female`), traducción de síntomas ES ↔ EN ↔ CA en `SYMPTOM_MAP` (280+ entradas), columnas opcionales toleradas. |
| **Veracity** | Stage de *limpieza* elimina duplicados, NAs, outliers; dropout y label-noise en entrenamiento previenen sobreajuste; IsolationForest detecta registros anómalos; métricas con *cross-validation* 3-fold para estimar la variabilidad real. |
| **Value** | Cada registro atraviesa el pipeline → clasificación → asignación → persistencia SQL, produciendo KPIs, gráficos, informes PDF y alertas de anomalía. La capa de servicio expone todo por REST para integraciones externas. |

### 10.5 Capas arquitectónicas

```
      ┌───────────────────────────────────────────────────────────┐
      │  Capa de presentación                                     │
      │  SPA (Chart.js, i18n, buscador live, informe paciente)    │
      └───────────────────────────────────────────────────────────┘
                               ▲
                               │ REST/JSON
      ┌───────────────────────────────────────────────────────────┐
      │  Capa de servicio (Flask API, auth por token, CORS)       │
      └───────────────────────────────────────────────────────────┘
                               ▲
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
      ┌──────────┐       ┌──────────┐       ┌─────────────┐
      │ Batch    │       │ Serving  │       │ Analytics   │
      │ ETL      │       │ ML       │       │ & EDA       │
      │ pipeline │       │ predict. │       │ endpoints   │
      │  .py     │       │  .py     │       │  + SQL      │
      └──────────┘       └──────────┘       └─────────────┘
            ▲                  ▲                  ▲
            └──────────────────┼──────────────────┘
                               ▼
      ┌───────────────────────────────────────────────────────────┐
      │  Capa de datos                                            │
      │  CSV raw · SQLite (patients, users) · bundle .joblib      │
      └───────────────────────────────────────────────────────────┘
```

- **Ingestión / batch**: `pipeline.run_pipeline` (equivalente a un job Spark).
- **Serving**: `ai_predictor.predictor` carga el bundle una vez y responde < 20 ms.
- **Analytics**: `patients_eda`, `analytics_patterns`, `analytics_anomalies`.
- **Almacenamiento**: CSV *raw* (landing zone) + SQLite (trusted zone) + bundle entrenado.

---

## 11. Consideraciones clínicas

> **Este sistema es una herramienta de apoyo, no reemplaza el juicio clínico.**
> Los datos de entrenamiento son sintéticos y los asignamientos de médicos son
> ficticios. En un despliegue real se deben:
>
> - Validar con datos reales supervisados por clínicos.
> - Auditar el sesgo por edad / género / etnia.
> - Cifrar la base de datos y usar control de acceso RBAC real.
> - Registrar trazabilidad de decisiones del modelo (ISO 13485 / IEC 62304).

---

*Generado automáticamente — MedAI Hospital v2.0*
