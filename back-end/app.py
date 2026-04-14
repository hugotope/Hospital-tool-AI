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
            DELETE /api/users/<id>
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

from flask import Flask, jsonify, request
from flask_cors import CORS

import database as db
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

_training_status: dict = {"running": False, "last_result": None, "last_error": None}

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

def _run_training() -> None:
    global _training_status
    _training_status.update({"running": True, "last_result": None, "last_error": None})
    try:
        result = subprocess.run(
            [sys.executable, str(TRAIN_SCRIPT)],
            capture_output=True, text=True, timeout=900,
        )
        if result.returncode == 0:
            predictor.reload()
            _training_status["last_result"] = "ok"
        else:
            _training_status["last_error"] = (result.stderr or "Error desconocido")[-2000:]
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
        return jsonify({"disease": disease, "risk": risk, "symptoms_translated": symptoms}), 200
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
    if _training_status["running"]:
        return jsonify({"status": "already_running", "message": "El entrenamiento ya esta en curso."}), 409
    if not TRAIN_SCRIPT.exists():
        return jsonify({"error": f"Script no encontrado: {TRAIN_SCRIPT}"}), 404
    threading.Thread(target=_run_training, daemon=True).start()
    return jsonify({"status": "started", "message": "Entrenamiento iniciado en segundo plano."}), 202


@app.get("/api/ai/train-status")
@require_auth
def train_status():
    return jsonify({
        "running": _training_status["running"],
        "last_result": _training_status["last_result"],
        "last_error": _training_status["last_error"],
        "models_loaded": predictor.loaded,
    }), 200


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
