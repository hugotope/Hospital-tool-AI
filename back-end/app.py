"""
Hospital AI — Flask API
========================
Endpoints:
  Public  : GET  /api/health
            POST /api/auth/login

  Auth    : POST /api/auth/logout
            GET  /api/auth/me
            GET  /api/dataset/preview
            GET  /api/dataset/stats
            GET  /api/dataset/list
            POST /api/dataset/upload
            GET  /api/diseases
            POST /api/ai/analyze
            POST /api/ai/predict-disease
            POST /api/ai/classify-risk
            GET  /api/ai/model-info
            POST /api/translate/symptoms

  Admin   : GET  /api/users
            POST /api/users
            DELETE /api/us ers/<id>
            POST /api/ai/train
            GET  /api/ai/train-status
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
import threading
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request
from flask_cors import CORS

import database as db
import pipeline
from ai_predictor import predictor

# ─────────────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

ROOT_DIR = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT_DIR / "healthcare_dataset_100k.csv"
TRAIN_SCRIPT = ROOT_DIR / "models-ia" / "train_spark.py"
UPLOAD_DIR = ROOT_DIR / "uploaded_datasets"
UPLOAD_DIR.mkdir(exist_ok=True)

_training_status: dict = {
    "running": False,
    "last_result": None,
    "last_error": None,
    "dataset": None,
}

# ── Init DB and models on startup ────────────────────────────────────────────
db.init_db()
predictor.load()


# ─────────────────────────────────────────────────────────────────────────────
# Auth decorators
# ─────────────────────────────────────────────────────────────────────────────

def _get_token() -> str:
    header = request.headers.get("Authorization", "")
    return header.replace("Bearer ", "").strip()


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        session = db.get_session(_get_token())
        if not session:
            return jsonify({"error": "No autorizado. Inicia sesion primero."}), 401
        request.session = session
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        session = db.get_session(_get_token())
        if not session:
            return jsonify({"error": "No autorizado."}), 401
        if session["role"] != "admin":
            return jsonify({"error": "Se requiere rol de administrador."}), 403
        request.session = session
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
# Symptom translation (ES → EN)
# ─────────────────────────────────────────────────────────────────────────────

SYMPTOM_MAP: dict[str, str] = {
    # Dolor / pain
    "dolor de cabeza": "headache",
    "dolor de pecho": "chest pain",
    "dolor pecho": "chest pain",
    "dolor abdominal": "abdominal pain",
    "dolor de estomago": "abdominal pain",
    "dolor estomago": "abdominal pain",
    "dolor de espalda": "back pain",
    "dolor muscular": "muscle pain",
    "dolor articular": "joint pain",
    "dolor de garganta": "sore throat",
    "dolor de huesos": "bone pain",
    # Respiratorio
    "dificultad para respirar": "shortness of breath",
    "dificultad respiratoria": "shortness of breath",
    "falta de aire": "shortness of breath",
    "respiracion corta": "shortness of breath",
    "falta de oxigeno": "shortness of breath",
    # Generales
    "fatiga": "fatigue",
    "cansancio": "fatigue",
    "fiebre": "fever",
    "tos": "cough",
    "mareo": "dizziness",
    "nauseas": "nausea",
    "nausea": "nausea",
    "vomito": "vomiting",
    "vomitos": "vomiting",
    "diarrea": "diarrhea",
    "estreñimiento": "constipation",
    "estrenimiento": "constipation",
    # Específicos
    "ictericia": "jaundice",
    "piel amarilla": "jaundice",
    "perdida de peso": "weight loss",
    "pérdida de peso": "weight loss",
    "miccion frecuente": "frequent urination",
    "orinar frecuente": "frequent urination",
    "micción frecuente": "frequent urination",
    "ganas de orinar": "frequent urination",
    "perdida de apetito": "loss of appetite",
    "falta de apetito": "loss of appetite",
    "sudoracion": "sweating",
    "sudoracion nocturna": "night sweats",
    "vision borrosa": "blurred vision",
    "visión borrosa": "blurred vision",
    "entumecimiento": "numbness",
    "hormigueo": "tingling",
    "debilidad": "weakness",
    "palpitaciones": "palpitations",
    "hinchazon": "swelling",
    "hinchazón": "swelling",
    "erupcion": "rash",
    "erupcion cutanea": "rash",
    "picazon": "itching",
    "picazón": "itching",
    "confusion": "confusion",
    "ansiedad": "anxiety",
    "depresion": "depression",
    "tristeza": "depression",
    "insomnio": "insomnia",
    "escalofrios": "chills",
    "escalofríos": "chills",
    "sed excesiva": "excessive thirst",
    "mucha sed": "excessive thirst",
    "hambre excesiva": "excessive hunger",
    "orina oscura": "dark urine",
    "heces oscuras": "dark stools",
    "sangre en orina": "blood in urine",
    "sangrado": "bleeding",
    "hemorragia": "hemorrhage",
    "convulsiones": "seizures",
    "paralisis": "paralysis",
    "pérdida de memoria": "memory loss",
    "perdida de memoria": "memory loss",
    "caida de cabello": "hair loss",
    "alopecia": "hair loss",
    "acne": "acne",
    "erupciones": "rashes",
    "temperatura alta": "fever",
    "escalofrio": "chills",
    "temblores": "tremors",
    "rigidez": "stiffness",
    "inflamacion": "inflammation",
    "inflamación": "inflammation",
    # ── Catala ────────────────────────────────────────────────────────────
    "febre": "fever",
    "mal de cap": "headache",
    "mal de gola": "sore throat",
    "dolor toracic": "chest pain",
    "dolor toràcic": "chest pain",
    "opressio toracica": "chest tightness",
    "opressió toràcica": "chest tightness",
    "dolor abdominal": "abdominal pain",
    "dolor articular": "joint pain",
    "dificultat per respirar": "shortness of breath",
    "mareig": "dizziness",
    "nausees": "nausea",
    "nàusees": "nausea",
    "inflor": "swelling",
    "perdua de pes": "weight loss",
    "pèrdua de pes": "weight loss",
    "miccio frequent": "frequent urination",
    "micció freqüent": "frequent urination",
    "set excessiva": "excessive thirst",
    "ictericia": "jaundice",
    "icterícia": "jaundice",
    "perdua d'interes": "loss of interest",
    "pèrdua d'interès": "loss of interest",
    "perdua del gust": "loss of taste",
    "pèrdua del gust": "loss of taste",
    "entumiment": "numbness",
    "tristesa": "sadness",
    "dificultat per parlar": "trouble speaking",
    "xiulets al pit": "wheezing",
    "visio borrosa": "blurred vision",
    "visió borrosa": "blurred vision",
    "dolors musculars": "body aches",
    "congestio nasal": "runny nose",
    "congestió nasal": "runny nose",
    "confusio": "confusion",
    "confusió": "confusion",
    "fatiga": "fatigue",
    "tos": "cough",
    # ── Ingles directo (passthrough) ──────────────────────────────────────
    "body aches": "body aches",
    "runny nose": "runny nose",
    "sadness": "sadness",
    "loss of interest": "loss of interest",
    "loss of taste": "loss of taste",
    "chest tightness": "chest tightness",
    "wheezing": "wheezing",
    "trouble speaking": "trouble speaking",
}


def translate_symptoms(text: str) -> str:
    """Translate Spanish symptoms to English (comma-separated)."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    translated = []
    for part in parts:
        lower = part.lower()
        # Longest match first
        match = None
        for es, en in sorted(SYMPTOM_MAP.items(), key=lambda x: len(x[0]), reverse=True):
            if es in lower:
                match = en
                break
        translated.append(match if match else part)
    return ", ".join(translated)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: training thread
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_training_dataset(data: dict) -> Path:
    dataset_name = str(data.get("dataset_name", "")).strip()
    dataset_path_raw = str(data.get("dataset_path", "")).strip()

    # Prioridad: ruta explícita enviada por frontend
    if dataset_path_raw:
        candidate = Path(dataset_path_raw)
    elif dataset_name:
        if dataset_name == DATASET_PATH.name:
            candidate = DATASET_PATH
        else:
            candidate = UPLOAD_DIR / dataset_name
    else:
        candidate = DATASET_PATH

    candidate = candidate.resolve()
    allowed_roots = [ROOT_DIR.resolve(), UPLOAD_DIR.resolve()]
    if not any(str(candidate).startswith(str(root)) for root in allowed_roots):
        raise ValueError("Dataset no permitido.")
    if not candidate.exists() or candidate.suffix.lower() != ".csv":
        raise ValueError("Dataset no encontrado o formato no valido.")
    return candidate


def _run_training(dataset_path: Path) -> None:
    global _training_status
    _training_status.update({
        "running": True,
        "last_result": None,
        "last_error": None,
        "dataset": str(dataset_path),
    })
    try:
        result = subprocess.run(
            [sys.executable, str(TRAIN_SCRIPT), "--dataset", str(dataset_path)],
            capture_output=True, text=True, timeout=900,
        )
        if result.returncode == 0:
            predictor.reload()
            _training_status["last_result"] = "ok"
        else:
            error_output = (result.stderr or "").strip()
            if not error_output:
                # Algunas fallas de Spark/Python salen por stdout.
                error_output = (result.stdout or "").strip()
            _training_status["last_error"] = (error_output or "Error desconocido")[-4000:]
    except subprocess.TimeoutExpired:
        _training_status["last_error"] = "Timeout: el entrenamiento superó 15 minutos."
    except Exception as exc:
        _training_status["last_error"] = str(exc)
    finally:
        _training_status["running"] = False


# ─────────────────────────────────────────────────────────────────────────────
# Diseases cache
# ─────────────────────────────────────────────────────────────────────────────

_diseases_cache: list | None = None

DIAGNOSIS_ASSIGNMENTS: dict[str, dict[str, str]] = {
    "Heart Disease": {"zone": "Cardiologia", "doctor": "Dr. Andres Morales (Cardiologo)"},
    "Hypertension": {"zone": "Cardiologia", "doctor": "Dra. Laura Castillo (Cardiologa)"},
    "Stroke": {"zone": "Neurologia", "doctor": "Dr. Javier Rojas (Neurologo)"},
    "Asthma": {"zone": "Neumologia", "doctor": "Dra. Sofia Ibanez (Neumologa)"},
    "COVID-19": {"zone": "Infectologia", "doctor": "Dr. Miguel Torres (Infectologo)"},
    "Diabetes": {"zone": "Endocrinologia", "doctor": "Dra. Daniela Paredes (Endocrina)"},
    "Kidney Disease": {"zone": "Nefrologia", "doctor": "Dr. Ricardo Mendez (Nefrologo)"},
    "Liver Disease": {"zone": "Hepatologia", "doctor": "Dra. Paula Jimenez (Hepatologa)"},
    "Cancer": {"zone": "Oncologia", "doctor": "Dr. Sebastian Vega (Oncologo)"},
    "Depression": {"zone": "Salud Mental", "doctor": "Dra. Valeria Nunez (Psiquiatra)"},
}


def assign_hospital_resources(diagnosis: str) -> dict[str, str]:
    return DIAGNOSIS_ASSIGNMENTS.get(
        diagnosis,
        {"zone": "Medicina General", "doctor": "Dr. Equipo de Guardia"},
    )


def _build_diseases_cache() -> list:
    global _diseases_cache
    if _diseases_cache is not None:
        return _diseases_cache
    diseases: dict = {}
    with DATASET_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("Diagnosis", "").strip()
            if not d:
                continue
            if d not in diseases:
                diseases[d] = {"name": d, "count": 0, "symptoms": {}, "ages": [], "genders": {}}
            diseases[d]["count"] += 1
            for sym in row.get("Symptoms", "").split(","):
                sym = sym.strip().lower()
                if sym:
                    diseases[d]["symptoms"][sym] = diseases[d]["symptoms"].get(sym, 0) + 1
            try:
                diseases[d]["ages"].append(int(row.get("Age", 0)))
            except ValueError:
                pass
            g = row.get("Gender", "Other")
            diseases[d]["genders"][g] = diseases[d]["genders"].get(g, 0) + 1

    result = []
    for name, data in diseases.items():
        top_syms = sorted(data["symptoms"].items(), key=lambda x: x[1], reverse=True)[:8]
        ages = data["ages"]
        result.append({
            "name": name,
            "count": data["count"],
            "common_symptoms": [s[0] for s in top_syms],
            "avg_age": round(sum(ages) / len(ages)) if ages else 0,
            "gender_distribution": data["genders"],
        })
    result.sort(key=lambda x: x["count"], reverse=True)
    _diseases_cache = result
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Public endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "models_loaded": predictor.loaded}), 200


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Usuario y contraseña requeridos."}), 400

    user = db.get_user_by_username(username)
    if not user or not db.verify_password(password, user["password_hash"]):
        return jsonify({"error": "Credenciales incorrectas."}), 401

    token = db.create_session(user["id"], user["username"], user["role"])
    return jsonify({
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
        },
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# Auth endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/auth/logout")
@require_auth
def logout():
    db.delete_session(_get_token())
    return jsonify({"message": "Sesion cerrada."}), 200


@app.get("/api/auth/me")
@require_auth
def me():
    return jsonify(request.session), 200


# ─────────────────────────────────────────────────────────────────────────────
# Dataset endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/dataset/preview")
@require_auth
def dataset_preview():
    max_rows = request.args.get("rows", default=15, type=int)
    max_rows = max(1, min(max_rows, 100))
    if not DATASET_PATH.exists():
        return jsonify({"error": "Dataset no encontrado."}), 404
    with DATASET_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        headers = next(reader, [])
        rows = [row for _, row in zip(range(max_rows), reader)]
    return jsonify({"headers": headers, "rows": rows, "total_shown": len(rows)}), 200


@app.get("/api/dataset/stats")
@require_auth
def dataset_stats():
    if not DATASET_PATH.exists():
        return jsonify({"error": "Dataset no encontrado."}), 404
    diagnoses: dict = {}
    genders: dict = {}
    total = 0
    with DATASET_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            total += 1
            d = row.get("Diagnosis", "Unknown")
            g = row.get("Gender", "Unknown")
            diagnoses[d] = diagnoses.get(d, 0) + 1
            genders[g] = genders.get(g, 0) + 1
    return jsonify({"total": total, "diagnoses": diagnoses, "genders": genders}), 200


@app.get("/api/dataset/list")
@require_auth
def dataset_list():
    datasets = []
    # Main dataset
    if DATASET_PATH.exists():
        stat = DATASET_PATH.stat()
        datasets.append({
            "name": DATASET_PATH.name,
            "path": str(DATASET_PATH),
            "size_kb": round(stat.st_size / 1024),
            "type": "main",
        })
    # Uploaded datasets
    for f in sorted(UPLOAD_DIR.glob("*.csv")):
        stat = f.stat()
        datasets.append({
            "name": f.name,
            "path": str(f),
            "size_kb": round(stat.st_size / 1024),
            "type": "uploaded",
        })
    return jsonify({"datasets": datasets}), 200


@app.post("/api/dataset/upload")
@require_auth
def dataset_upload():
    if "file" not in request.files:
        return jsonify({"error": "No se encontro archivo en la solicitud."}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No se selecciono archivo."}), 400
    if not file.filename.lower().endswith(".csv"):
        return jsonify({"error": "Solo se permiten archivos CSV."}), 400

    # Safe filename
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in file.filename)
    filepath = UPLOAD_DIR / safe_name
    file.save(str(filepath))

    # Validate columns
    try:
        with filepath.open(encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = [h.strip() for h in (next(reader, []))]
            required = {"Age", "Gender", "Symptoms", "Diagnosis"}
            missing = required - set(headers)
            if missing:
                filepath.unlink(missing_ok=True)
                return jsonify({"error": f"Columnas faltantes: {', '.join(missing)}"}), 400
            row_count = sum(1 for _ in reader)
    except Exception as exc:
        filepath.unlink(missing_ok=True)
        return jsonify({"error": f"Error al leer el archivo: {exc}"}), 400

    return jsonify({
        "message": "Dataset subido exitosamente.",
        "filename": safe_name,
        "rows": row_count,
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# Diseases endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/diseases")
@require_auth
def get_diseases():
    if not DATASET_PATH.exists():
        return jsonify({"error": "Dataset no encontrado."}), 404
    try:
        return jsonify(_build_diseases_cache()), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Translation endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/translate/symptoms")
@require_auth
def translate_endpoint():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    translated = translate_symptoms(text)
    return jsonify({"original": text, "translated": translated}), 200


# ─────────────────────────────────────────────────────────────────────────────
# AI endpoints
# ─────────────────────────────────────────────────────────────────────────────

def _check_models():
    if not predictor.loaded:
        return jsonify({"error": predictor.error or "Modelos no cargados. Ejecuta el entrenamiento primero."}), 503
    return None


def _parse_patient(data: dict):
    age = data.get("age")
    gender = data.get("gender", "")
    symptoms_raw = data.get("symptoms", "")
    if age is None or not gender or not symptoms_raw:
        return None, None, None, jsonify({"error": "Campos requeridos: age, gender, symptoms"}), 400
    # Auto-translate
    symptoms_en = translate_symptoms(str(symptoms_raw))
    return int(age), str(gender), symptoms_en, None, None


@app.post("/api/ai/analyze")
@require_auth
def analyze():
    err = _check_models()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    age, gender, symptoms, err_resp, err_code = _parse_patient(data)
    if err_resp:
        return err_resp, err_code
    try:
        disease = predictor.predict_disease(age, gender, symptoms)
        risk = predictor.classify_risk(age, gender, symptoms)
        anomaly = predictor.anomaly_score(age, gender, symptoms)
        predicted_diagnosis = disease.get("predicted_disease", "Unknown")
        assignment = assign_hospital_resources(predicted_diagnosis)
        save_flag = bool(data.get("save", True))
        patient_id = None
        if save_flag:
            patient_name = str(data.get("patient_name", "")).strip() or "Paciente sin nombre"
            patient = db.create_patient(
                patient_name=patient_name,
                age=age,
                gender=gender,
                symptoms=str(data.get("symptoms", "")).strip(),
                symptoms_translated=symptoms,
                diagnosis=predicted_diagnosis,
                diagnosis_confidence=float(disease.get("confidence", 0)),
                risk_level=str(risk.get("risk_level", "")),
                risk_confidence=float(risk.get("confidence", 0)),
                hospital_zone=assignment["zone"],
                specialist_doctor=assignment["doctor"],
                source_dataset=DATASET_PATH.name,
                created_by=request.session.get("username", ""),
            )
            patient_id = patient["id"]
        return jsonify({
            "disease": disease,
            "risk": risk,
            "anomaly": anomaly,
            "symptoms_translated": symptoms,
            "assignment": assignment,
            "patient_id": patient_id,
        }), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/ai/predict-disease")
@require_auth
def predict_disease():
    err = _check_models()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    age, gender, symptoms, err_resp, err_code = _parse_patient(data)
    if err_resp:
        return err_resp, err_code
    try:
        return jsonify(predictor.predict_disease(age, gender, symptoms)), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/ai/classify-risk")
@require_auth
def classify_risk():
    err = _check_models()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    age, gender, symptoms, err_resp, err_code = _parse_patient(data)
    if err_resp:
        return err_resp, err_code
    try:
        return jsonify(predictor.classify_risk(age, gender, symptoms)), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/ai/model-info")
@require_auth
def model_info():
    return jsonify(predictor.get_model_info()), 200


@app.post("/api/ai/train")
@require_admin
def train_models():
    data = request.get_json(silent=True) or {}
    if _training_status["running"]:
        return jsonify({"status": "already_running", "message": "El entrenamiento ya esta en curso."}), 409
    if not TRAIN_SCRIPT.exists():
        return jsonify({"error": f"Script no encontrado: {TRAIN_SCRIPT}"}), 404
    try:
        selected_dataset = _resolve_training_dataset(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    threading.Thread(target=_run_training, args=(selected_dataset,), daemon=True).start()
    return jsonify({
        "status": "started",
        "message": "Entrenamiento iniciado en segundo plano.",
        "dataset": str(selected_dataset),
    }), 202


@app.get("/api/ai/train-status")
@require_auth
def train_status():
    return jsonify({
        "running": _training_status["running"],
        "last_result": _training_status["last_result"],
        "last_error": _training_status["last_error"],
        "dataset": _training_status.get("dataset"),
        "models_loaded": predictor.loaded,
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# Patients endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/patients")
@require_auth
def list_patients():
    limit = request.args.get("limit", default=200, type=int)
    limit = max(1, min(limit, 1000))
    return jsonify({"patients": db.list_patients(limit)}), 200


@app.get("/api/patients/eda")
@require_auth
def patients_eda():
    return jsonify(db.patients_eda()), 200


@app.post("/api/patients/import-dataset")
@require_admin
def import_patients_dataset():
    err = _check_models()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        dataset_path = _resolve_training_dataset(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    max_rows = data.get("max_rows")
    if max_rows is not None:
        try:
            max_rows = max(1, min(int(max_rows), 100000))
        except Exception:
            return jsonify({"error": "max_rows debe ser un numero entero."}), 400

    try:
        result = db.import_patients_from_dataset(
            dataset_path=dataset_path,
            classifier=predictor,
            username=request.session.get("username", ""),
            assigner=assign_hospital_resources,
            max_rows=max_rows,
        )
        return jsonify({
            "message": "Importacion de pacientes completada.",
            **result,
        }), 200
    except Exception as exc:
        return jsonify({"error": f"Error importando dataset: {exc}"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Analytics / Decision support endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/analytics/overview")
@require_auth
def analytics_overview():
    """
    Panel de decision: combina dataset + pacientes + modelo.
    """
    try:
        eda = db.patients_eda()
    except Exception:
        eda = {}

    dataset_total = 0
    if DATASET_PATH.exists():
        with DATASET_PATH.open(encoding="utf-8") as f:
            dataset_total = sum(1 for _ in f) - 1

    model_info = predictor.get_model_info()

    return jsonify({
        "dataset_total_rows": dataset_total,
        "patients_db": eda,
        "model": {
            "loaded": model_info.get("loaded", False),
            "disease_accuracy": model_info.get("disease_accuracy"),
            "disease_cv_accuracy_mean": model_info.get("disease_cv_accuracy_mean"),
            "risk_accuracy": model_info.get("risk_accuracy"),
            "risk_cv_accuracy_mean": model_info.get("risk_cv_accuracy_mean"),
            "trained_at": model_info.get("trained_at"),
        },
        "zones_catalog": [
            {"diagnosis": k, **v} for k, v in DIAGNOSIS_ASSIGNMENTS.items()
        ],
    }), 200


@app.get("/api/analytics/patterns")
@require_auth
def analytics_patterns():
    """
    Analisis de patrones: co-ocurrencia de sintomas, edad media por
    enfermedad, distribucion por genero.
    """
    if not DATASET_PATH.exists():
        return jsonify({"error": "Dataset no encontrado."}), 404

    symptom_pairs: dict = {}
    age_by_disease: dict = {}
    with DATASET_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            syms = sorted({s.strip().lower() for s in row.get("Symptoms", "").split(",") if s.strip()})
            for i in range(len(syms)):
                for j in range(i + 1, len(syms)):
                    pair = f"{syms[i]} + {syms[j]}"
                    symptom_pairs[pair] = symptom_pairs.get(pair, 0) + 1
            d = row.get("Diagnosis", "").strip()
            try:
                age = int(row.get("Age", 0))
            except ValueError:
                continue
            if d:
                age_by_disease.setdefault(d, []).append(age)

    top_pairs = sorted(symptom_pairs.items(), key=lambda x: x[1], reverse=True)[:10]
    age_stats = [
        {
            "diagnosis": d,
            "avg_age": round(sum(ages) / len(ages), 1),
            "min_age": min(ages),
            "max_age": max(ages),
            "n": len(ages),
        }
        for d, ages in age_by_disease.items()
    ]
    age_stats.sort(key=lambda x: x["avg_age"])

    return jsonify({
        "top_symptom_pairs": [{"pair": p, "count": c} for p, c in top_pairs],
        "age_stats_by_diagnosis": age_stats,
    }), 200


@app.get("/api/analytics/anomalies")
@require_auth
def analytics_anomalies():
    """
    Detecta anomalias en pacientes guardados usando IsolationForest.
    """
    err = _check_models()
    if err:
        return err
    limit = request.args.get("limit", default=200, type=int)
    limit = max(1, min(limit, 1000))
    patients = db.list_patients(limit)
    anomalies = []
    for p in patients:
        try:
            res = predictor.anomaly_score(
                p.get("age", 0),
                p.get("gender", "Other"),
                p.get("symptoms", ""),
            )
            if res.get("is_anomaly"):
                anomalies.append({
                    "id": p.get("id"),
                    "patient_name": p.get("patient_name"),
                    "age": p.get("age"),
                    "gender": p.get("gender"),
                    "diagnosis": p.get("diagnosis"),
                    "symptoms": p.get("symptoms"),
                    "score": res.get("score"),
                })
        except Exception:
            continue
    return jsonify({
        "checked": len(patients),
        "anomalies_count": len(anomalies),
        "anomalies": anomalies,
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline ETL (Ingesta -> Limpieza -> Transformacion -> Analisis)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/dataset/pipeline")
@require_auth
def dataset_pipeline():
    """Corre el pipeline ETL sobre un dataset existente y devuelve el informe."""
    data = request.get_json(silent=True) or {}
    try:
        dataset_path = _resolve_training_dataset(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        report = pipeline.run_pipeline(dataset_path, translator=translate_symptoms)
        return jsonify(report), 200
    except Exception as exc:
        return jsonify({"error": f"Error en pipeline: {exc}"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Busqueda incremental de pacientes + informe individual
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/patients/search")
@require_auth
def patients_search():
    q = request.args.get("q", "").strip()
    limit = request.args.get("limit", default=20, type=int)
    limit = max(1, min(limit, 100))
    results = db.search_patients_by_name(q, limit=limit) if q else []
    return jsonify({"query": q, "count": len(results), "results": results}), 200


@app.get("/api/patients/<int:patient_id>")
@require_auth
def patient_detail(patient_id: int):
    patient = db.get_patient_by_id(patient_id)
    if not patient:
        return jsonify({"error": "Paciente no encontrado."}), 404

    # Enriquecemos con anomalia y recomendaciones si el modelo esta cargado
    anomaly = None
    recommendations: list[str] = []
    if predictor.loaded:
        try:
            anomaly = predictor.anomaly_score(
                patient.get("age", 0),
                patient.get("gender", "Other"),
                patient.get("symptoms_translated") or patient.get("symptoms", ""),
            )
        except Exception:
            anomaly = None
        try:
            risk = predictor.classify_risk(
                patient.get("age", 0),
                patient.get("gender", "Other"),
                patient.get("symptoms_translated") or patient.get("symptoms", ""),
            )
            recommendations = risk.get("recommendations", [])
        except Exception:
            recommendations = []

    assignment = assign_hospital_resources(patient.get("diagnosis", "Unknown"))
    return jsonify({
        "patient": patient,
        "anomaly": anomaly,
        "recommendations": recommendations,
        "assignment": assignment,
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# Reporte (HTML imprimible a PDF)
# ─────────────────────────────────────────────────────────────────────────────

_REPORT_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>MedAI Hospital - Informe del sistema</title>
<style>
  @page { size: A4; margin: 1.6cm; }
  body { font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
         color: #0f172a; line-height: 1.55; max-width: 860px; margin: 0 auto; padding: 30px; }
  h1 { font-size: 28px; margin: 0 0 4px; color: #0f172a; }
  h2 { font-size: 20px; margin-top: 28px; border-bottom: 2px solid #0ea5e9; padding-bottom: 6px; color: #0f172a; }
  h3 { font-size: 15px; margin-top: 18px; color: #334155; }
  .subtitle { color: #475569; margin: 0 0 22px; }
  .meta { background: #f1f5f9; border-left: 4px solid #0ea5e9; padding: 10px 14px; border-radius: 4px; font-size: 13px; margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; margin: 10px 0 18px; font-size: 13px; }
  th, td { border: 1px solid #e2e8f0; padding: 6px 10px; text-align: left; }
  th { background: #f8fafc; }
  .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 12px 0 22px; }
  .kpi { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; text-align: center; }
  .kpi-value { font-size: 22px; font-weight: 700; color: #0ea5e9; }
  .kpi-label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .5px; }
  ul { padding-left: 20px; }
  code { background: #f1f5f9; padding: 2px 6px; border-radius: 3px; font-size: 12px; }
  .footer { margin-top: 30px; padding-top: 12px; border-top: 1px solid #e2e8f0; font-size: 11px; color: #64748b; text-align: center; }
  @media print { body { padding: 0; } .no-print { display: none; } }
  .print-btn { position: fixed; top: 16px; right: 16px; background: #0ea5e9; color: white; padding: 10px 18px; border: 0; border-radius: 6px; font-weight: 600; cursor: pointer; }
</style>
</head>
<body>
  <button class="print-btn no-print" onclick="window.print()">Imprimir / Guardar PDF</button>
  <h1>MedAI Hospital — Informe tecnico</h1>
  <p class="subtitle">Sistema inteligente de clasificacion y prediccion clinica</p>
  <div class="meta">
    <strong>Generado:</strong> {{ generated_at }}<br>
    <strong>Dataset:</strong> {{ dataset_name }} ({{ dataset_rows }} registros)<br>
    <strong>Modelos:</strong> {{ "cargados" if model_loaded else "no cargados" }} — Ultimo entrenamiento: {{ trained_at }}
  </div>

  <h2>1. Resumen ejecutivo</h2>
  <p>MedAI Hospital es una plataforma que asiste al personal clinico en cuatro tareas principales:</p>
  <ul>
    <li><strong>Analisis</strong> de datos clinicos a partir de datasets CSV.</li>
    <li><strong>Prediccion de enfermedades</strong> con RandomForest entrenado sobre sintomas.</li>
    <li><strong>Clasificacion de pacientes</strong> por nivel de riesgo (Low/Medium/High) con asignacion automatica de zona hospitalaria y medico especialista.</li>
    <li><strong>Deteccion de anomalias</strong> mediante IsolationForest para alertar sobre casos atipicos.</li>
  </ul>

  <h2>2. Metricas del modelo</h2>
  <div class="kpi-grid">
    <div class="kpi"><div class="kpi-value">{{ acc_disease }}</div><div class="kpi-label">Disease Accuracy</div></div>
    <div class="kpi"><div class="kpi-value">{{ cv_disease }}</div><div class="kpi-label">CV 3-fold</div></div>
    <div class="kpi"><div class="kpi-value">{{ acc_risk }}</div><div class="kpi-label">Risk Accuracy</div></div>
    <div class="kpi"><div class="kpi-value">{{ cv_risk }}</div><div class="kpi-label">CV 3-fold</div></div>
  </div>
  <h3>Metodologia de evaluacion honesta</h3>
  <p>El dataset sintetico tiene un mapeo sintomas→diagnostico casi deterministico. Para evitar accuracy artificial del 100% aplicamos:</p>
  <ul>
    <li>Eliminacion de <code>days_stayed</code> (no disponible en inferencia).</li>
    <li><strong>Symptom dropout</strong>: se eliminan aleatoriamente 1-2 sintomas en train (simula historias incompletas).</li>
    <li><strong>Label noise 5%</strong> en riesgo (incertidumbre clinica).</li>
    <li><strong>Validacion cruzada estratificada 3-fold</strong> ademas de split 80/20.</li>
  </ul>

  <h2>3. Arquitectura</h2>
  <ul>
    <li><strong>Backend:</strong> Flask (Python 3.13) + SQLite.</li>
    <li><strong>ML:</strong> scikit-learn RandomForest + TF-IDF + IsolationForest. Soporte opcional para PySpark.</li>
    <li><strong>Persistencia:</strong> tabla <code>patients</code> con diagnostico, riesgo, zona y medico.</li>
    <li><strong>Frontend:</strong> SPA vanilla JavaScript con i18n (ES/EN/CA), diseño corporativo responsive.</li>
  </ul>

  <h2>4. Clasificacion de pacientes</h2>
  <p>Cada paciente es asignado automaticamente a una zona hospitalaria y un medico especialista en funcion del diagnostico predicho.</p>
  <table>
    <thead><tr><th>Diagnostico</th><th>Zona</th><th>Medico</th></tr></thead>
    <tbody>
      {% for item in zones %}
        <tr><td>{{ item.diagnosis }}</td><td>{{ item.zone }}</td><td>{{ item.doctor }}</td></tr>
      {% endfor %}
    </tbody>
  </table>

  <h2>5. Base de datos de pacientes</h2>
  <div class="kpi-grid">
    <div class="kpi"><div class="kpi-value">{{ patients_total }}</div><div class="kpi-label">Pacientes</div></div>
    <div class="kpi"><div class="kpi-value">{{ patients_avg_age }}</div><div class="kpi-label">Edad media</div></div>
    <div class="kpi"><div class="kpi-value">{{ top_diagnosis }}</div><div class="kpi-label">Dx mas frecuente</div></div>
    <div class="kpi"><div class="kpi-value">{{ top_zone }}</div><div class="kpi-label">Zona mas activa</div></div>
  </div>

  <h2>6. Endpoints principales</h2>
  <table>
    <thead><tr><th>Metodo</th><th>Ruta</th><th>Descripcion</th></tr></thead>
    <tbody>
      <tr><td>POST</td><td>/api/auth/login</td><td>Inicio de sesion</td></tr>
      <tr><td>POST</td><td>/api/ai/analyze</td><td>Diagnostico + riesgo + anomalia + persistencia</td></tr>
      <tr><td>POST</td><td>/api/ai/predict-disease</td><td>Solo prediccion de enfermedad</td></tr>
      <tr><td>POST</td><td>/api/ai/classify-risk</td><td>Solo clasificacion de riesgo</td></tr>
      <tr><td>POST</td><td>/api/ai/train</td><td>Reentrenar modelos con dataset seleccionado</td></tr>
      <tr><td>GET</td><td>/api/patients</td><td>Listar pacientes</td></tr>
      <tr><td>GET</td><td>/api/patients/eda</td><td>EDA de pacientes guardados</td></tr>
      <tr><td>POST</td><td>/api/patients/import-dataset</td><td>Importacion masiva a SQL</td></tr>
      <tr><td>GET</td><td>/api/analytics/overview</td><td>Panel de decision</td></tr>
      <tr><td>GET</td><td>/api/analytics/patterns</td><td>Patrones y correlaciones</td></tr>
      <tr><td>GET</td><td>/api/analytics/anomalies</td><td>Deteccion de anomalias</td></tr>
      <tr><td>GET</td><td>/api/report/view</td><td>Este informe</td></tr>
    </tbody>
  </table>

  <h2>7. Automatizacion y toma de decisiones</h2>
  <ul>
    <li>Diagnostico automatico al introducir sintomas (traduccion ES→EN integrada).</li>
    <li>Persistencia automatica del paciente con zona/medico.</li>
    <li>Alerta automatica por anomalia (paciente atipico).</li>
    <li>KPIs para decision ejecutiva (accuracy, zonas saturadas, edad media).</li>
    <li>Reentrenamiento on-demand con datasets nuevos desde la UI.</li>
  </ul>

  <div class="footer">MedAI Hospital — Informe generado automaticamente por el sistema.</div>
</body>
</html>"""


@app.get("/api/report/view")
def report_view():
    model_info = predictor.get_model_info()
    eda = db.patients_eda()
    dataset_rows = 0
    if DATASET_PATH.exists():
        with DATASET_PATH.open(encoding="utf-8") as f:
            dataset_rows = max(0, sum(1 for _ in f) - 1)

    def pct(x):
        return f"{x * 100:.1f}%" if isinstance(x, (int, float)) else "—"

    html = render_template_string(
        _REPORT_TEMPLATE,
        generated_at=__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        dataset_name=DATASET_PATH.name,
        dataset_rows=f"{dataset_rows:,}",
        model_loaded=model_info.get("loaded", False),
        trained_at=model_info.get("trained_at", "—"),
        acc_disease=pct(model_info.get("disease_accuracy")),
        cv_disease=pct(model_info.get("disease_cv_accuracy_mean")),
        acc_risk=pct(model_info.get("risk_accuracy")),
        cv_risk=pct(model_info.get("risk_cv_accuracy_mean")),
        zones=[{"diagnosis": k, **v} for k, v in DIAGNOSIS_ASSIGNMENTS.items()],
        patients_total=eda.get("total_patients", 0),
        patients_avg_age=eda.get("age_stats", {}).get("avg_age") or "—",
        top_diagnosis=(eda.get("top_diagnoses") or [{"name": "—"}])[0]["name"],
        top_zone=(eda.get("zone_distribution") or [{"name": "—"}])[0]["name"],
    )
    return Response(html, mimetype="text/html; charset=utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# User management (admin only)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/users")
@require_admin
def list_users():
    return jsonify({"users": db.get_all_users()}), 200


@app.post("/api/users")
@require_admin
def create_user():
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")

    if not username or not name or not password:
        return jsonify({"error": "Campos requeridos: username, name, password"}), 400
    if role not in ("admin", "user"):
        return jsonify({"error": "Rol invalido. Usa 'admin' o 'user'."}), 400
    try:
        user = db.create_user(username, name, email, password, role)
        return jsonify({"message": "Usuario creado.", "user": user}), 201
    except Exception as exc:
        if "UNIQUE" in str(exc):
            return jsonify({"error": f"El usuario '{username}' ya existe."}), 409
        return jsonify({"error": str(exc)}), 500


@app.delete("/api/users/<int:user_id>")
@require_admin
def delete_user(user_id: int):
    if db.deactivate_user(user_id):
        return jsonify({"message": "Usuario eliminado."}), 200
    return jsonify({"error": "Usuario no encontrado o no se puede eliminar."}), 404


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
