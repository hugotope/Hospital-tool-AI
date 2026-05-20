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
            POST /api/radiology/upload (imagenes en MongoDB GridFS)
            GET  /api/radiology/list
            GET  /api/diseases
            POST /api/ai/analyze
            POST /api/ai/predict-disease
            POST /api/ai/classify-risk
            GET  /api/ai/model-info
            POST /api/translate/symptoms
            GET  /api/notifications
            POST /api/notifications/read

  Admin   : GET  /api/users
            POST /api/users
            DELETE /api/us ers/<id>
            POST /api/ai/train
            GET  /api/ai/train-status
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import threading
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request
from flask_cors import CORS
from pymongo.errors import PyMongoError

from logging_config import get_logger, setup_logging

setup_logging()

import database as db
import mongo_radiology as radiology_store
import pipeline
from ai_predictor import predictor
from cnn_predictor import cnn_predictor
from mongodb_client import mongo

# ─────────────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
_csv_mb = int(os.environ.get("HOSPITAL_MAX_UPLOAD_MB", "25"))
_rad_mb = int(os.environ.get("HOSPITAL_MAX_RADIOLOGY_MB", "100"))
app.config["MAX_CONTENT_LENGTH"] = max(_csv_mb, _rad_mb) * 1024 * 1024


def _cors_origins() -> list[str]:
    configured = os.environ.get("HOSPITAL_CORS_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return ["http://127.0.0.1:5500", "http://localhost:5500", "null"]


CORS(app, resources={r"/api/*": {"origins": _cors_origins()}})

ROOT_DIR = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT_DIR / "healthcare_dataset_100k.csv"
TRAIN_SCRIPT = ROOT_DIR / "models-ia" / "train_spark.py"
UPLOAD_DIR = ROOT_DIR / "uploaded_datasets"
UPLOAD_DIR.mkdir(exist_ok=True)
ACTIVE_DATASET_FILE = UPLOAD_DIR / ".active_dataset"

_training_status: dict = {
    "running": False,
    "last_result": None,
    "last_error": None,
    "dataset": None,
}

# ── Init DB and models on startup ────────────────────────────────────────────
db.init_db()
db.ensure_default_doctors()
predictor.load()
cnn_predictor.load()   # intenta cargar el modelo CNN (no falla si no existe)

log_health = get_logger("health")
log_training = get_logger("training")
log_notifications = get_logger("notifications")


# ─────────────────────────────────────────────────────────────────────────────
# Active dataset selection
# ─────────────────────────────────────────────────────────────────────────────

def _read_active_dataset_pointer() -> Path | None:
    try:
        if not ACTIVE_DATASET_FILE.exists():
            return None
        # Tolerante a BOM (utf-8-sig) y CR/LF en el path persistido.
        raw = ACTIVE_DATASET_FILE.read_text(encoding="utf-8-sig").strip()
        raw = raw.lstrip("\ufeff").strip().strip('"').strip("'")
        if not raw:
            return None
        candidate = Path(raw).expanduser().resolve()
        if candidate.exists() and candidate.suffix.lower() == ".csv":
            return candidate
    except Exception:
        return None
    return None


def _write_active_dataset_pointer(path: Path | None) -> None:
    try:
        if path is None:
            ACTIVE_DATASET_FILE.unlink(missing_ok=True)
        else:
            ACTIVE_DATASET_FILE.write_text(str(path.resolve()), encoding="utf-8")
    except Exception:
        pass


def active_dataset_path() -> Path:
    """
    Devuelve el dataset activo con la siguiente prioridad:
      1. El apuntado explicitamente por `.active_dataset` (si existe).
      2. El CSV mas reciente subido en `uploaded_datasets/`.
      3. El dataset principal por defecto.
    """
    pointer = _read_active_dataset_pointer()
    if pointer is not None:
        return pointer
    try:
        candidates = sorted(UPLOAD_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0].resolve()
    except Exception:
        pass
    return DATASET_PATH


def _is_dataset_path_allowed(candidate: Path) -> bool:
    candidate = candidate.resolve()
    return any(
        str(candidate).startswith(str(root.resolve()))
        for root in (ROOT_DIR, UPLOAD_DIR)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auth decorators
# ─────────────────────────────────────────────────────────────────────────────

def _get_token() -> str:
    header = request.headers.get("Authorization", "")
    token = header.replace("Bearer ", "").strip()
    if token:
        return token
    return request.args.get("access_token", "").strip()


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
    dataset_alias = str(data.get("dataset", "")).strip()

    # Prioridad: ruta explícita enviada por frontend
    if dataset_path_raw:
        candidate = Path(dataset_path_raw)
    elif dataset_alias:
        candidate = Path(dataset_alias)
    elif dataset_name:
        if dataset_name == DATASET_PATH.name:
            candidate = DATASET_PATH
        else:
            candidate = UPLOAD_DIR / dataset_name
    else:
        candidate = active_dataset_path()

    candidate = candidate.resolve()
    if not _is_dataset_path_allowed(candidate):
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
    _notify(
        "info",
        "Entrenamiento iniciado",
        f"Reentrenando con {dataset_path.name}.",
        source="training",
    )
    log_training.info("Entrenamiento tabular iniciado | dataset=%s", dataset_path.name)
    try:
        result = subprocess.run(
            [sys.executable, str(TRAIN_SCRIPT), "--dataset", str(dataset_path)],
            capture_output=True, text=True, timeout=900,
            cwd=str(ROOT_DIR),
        )
        if result.returncode == 0:
            predictor.reload()
            _training_status["last_result"] = "ok"
            _invalidate_diseases_cache()
            log_training.info("Entrenamiento tabular completado | dataset=%s", dataset_path.name)
            _notify(
                "success",
                "Entrenamiento completado",
                f"Modelo actualizado con {dataset_path.name}.",
                source="training",
            )
        else:
            error_output = (result.stderr or "").strip()
            if not error_output:
                error_output = (result.stdout or "").strip()
            _training_status["last_error"] = (error_output or "Error desconocido")[-4000:]
            log_training.error(
                "Entrenamiento tabular fallido | code=%s | dataset=%s",
                result.returncode,
                dataset_path.name,
            )
            for line in _training_status["last_error"].splitlines()[-15:]:
                log_training.error("[train] %s", line)
            _notify(
                "error",
                "Fallo en el entrenamiento",
                _training_status["last_error"][-600:],
                source="training",
                meta={"dataset": dataset_path.name, "returncode": result.returncode},
            )
    except subprocess.TimeoutExpired:
        _training_status["last_error"] = "Timeout: el entrenamiento superó 15 minutos."
        log_training.error("Entrenamiento tabular timeout | dataset=%s", dataset_path.name)
        _notify("error", "Entrenamiento detenido por timeout",
                "El entrenamiento superó 15 minutos y fue cancelado.",
                source="training",
                meta={"dataset": dataset_path.name})
    except Exception as exc:
        _training_status["last_error"] = str(exc)
        log_training.exception("Excepcion en entrenamiento tabular")
        _notify("error", "Excepcion durante el entrenamiento",
                str(exc), source="training",
                meta={"dataset": dataset_path.name})
    finally:
        _training_status["running"] = False


def _start_training_async(dataset_path: Path) -> bool:
    """Lanza el entrenamiento en hilo si no hay otro corriendo."""
    if _training_status.get("running"):
        return False
    if not TRAIN_SCRIPT.exists():
        _notify("error", "Script de entrenamiento no encontrado", str(TRAIN_SCRIPT),
                source="training")
        return False
    threading.Thread(target=_run_training, args=(dataset_path,), daemon=True).start()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Diseases cache + assignments
# ─────────────────────────────────────────────────────────────────────────────

_diseases_cache: dict[str, list] = {}

DIAGNOSIS_ASSIGNMENTS: dict[str, dict[str, str]] = {
    # Dataset original
    "Heart Disease":   {"zone": "Cardiologia",       "doctor": "Dr. Andres Morales (Cardiologo)"},
    "Hypertension":    {"zone": "Cardiologia",       "doctor": "Dra. Laura Castillo (Cardiologa)"},
    "Stroke":          {"zone": "Neurologia",        "doctor": "Dr. Javier Rojas (Neurologo)"},
    "Asthma":          {"zone": "Neumologia",        "doctor": "Dra. Sofia Ibanez (Neumologa)"},
    "COVID-19":        {"zone": "Infectologia",      "doctor": "Dr. Miguel Torres (Infectologo)"},
    "Diabetes":        {"zone": "Endocrinologia",    "doctor": "Dra. Daniela Paredes (Endocrina)"},
    "Kidney Disease":  {"zone": "Nefrologia",        "doctor": "Dr. Ricardo Mendez (Nefrologo)"},
    "Liver Disease":   {"zone": "Hepatologia",       "doctor": "Dra. Paula Jimenez (Hepatologa)"},
    "Cancer":          {"zone": "Oncologia",         "doctor": "Dr. Sebastian Vega (Oncologo)"},
    "Depression":      {"zone": "Salud Mental",      "doctor": "Dra. Valeria Nunez (Psiquiatra)"},
    # Dataset extendido v2
    "Pneumonia":       {"zone": "Neumologia",        "doctor": "Dr. Hector Salazar (Neumologo)"},
    "Bronchitis":      {"zone": "Neumologia",        "doctor": "Dra. Sofia Ibanez (Neumologa)"},
    "Migraine":        {"zone": "Neurologia",        "doctor": "Dr. Julio Fernandez (Neurologo)"},
    "Anxiety Disorder":{"zone": "Salud Mental",      "doctor": "Dra. Beatriz Ortega (Psicologa)"},
    "Arthritis":       {"zone": "Reumatologia",      "doctor": "Dra. Carolina Lopez (Reumatologa)"},
    "Osteoporosis":    {"zone": "Traumatologia",     "doctor": "Dr. Alberto Ramos (Traumatologo)"},
    "Dermatitis":      {"zone": "Dermatologia",      "doctor": "Dra. Marta Solis (Dermatologa)"},
    "Gastroenteritis": {"zone": "Gastroenterologia", "doctor": "Dr. Joaquin Pereira (Gastroenterologo)"},
    "Anemia":          {"zone": "Hematologia",       "doctor": "Dra. Elena Cabrera (Hematologa)"},
    "Thyroid Disorder":{"zone": "Endocrinologia",    "doctor": "Dra. Daniela Paredes (Endocrina)"},
}


# Heuristica por palabras clave para enfermedades nuevas no mapeadas
_KEYWORD_ZONES: list[tuple[tuple[str, ...], str]] = [
    (("heart", "cardiac", "hyperten", "tachy", "arrhyth"), "Cardiologia"),
    (("stroke", "migraine", "neuro", "epilep", "alzheimer", "parkinson"), "Neurologia"),
    (("asthma", "pneumon", "bronch", "copd", "lung", "respirat"), "Neumologia"),
    (("covid", "infect", "sepsis", "tuberc", "hepatitis"), "Infectologia"),
    (("diabet", "thyroid", "endocrine", "hormone"), "Endocrinologia"),
    (("kidney", "renal", "nephr"), "Nefrologia"),
    (("liver", "hepat", "cirrhos"), "Hepatologia"),
    (("cancer", "tumor", "neoplas", "leukem", "lymphom", "melanom"), "Oncologia"),
    (("depress", "anxiety", "psych", "bipolar", "schizo", "panic"), "Salud Mental"),
    (("arthrit", "lupus", "reumat"), "Reumatologia"),
    (("osteopor", "fracture", "trauma", "orthoped"), "Traumatologia"),
    (("derma", "skin", "eczema", "psoria", "acne", "rash"), "Dermatologia"),
    (("gastr", "colitis", "ulcer", "ibs", "crohn"), "Gastroenterologia"),
    (("anemia", "leukem", "blood", "thrombo", "hemato"), "Hematologia"),
]


def _zone_from_keywords(diagnosis: str) -> str | None:
    name = (diagnosis or "").strip().lower()
    if not name:
        return None
    for keywords, zone in _KEYWORD_ZONES:
        if any(k in name for k in keywords):
            return zone
    return None


def assign_hospital_resources(diagnosis: str) -> dict[str, str]:
    """
    Resuelve zona y medico para un diagnostico:
      1. Mapeo explicito en DIAGNOSIS_ASSIGNMENTS.
      2. Heuristica por palabras clave en el nombre.
      3. Fallback a Medicina General.
    Si la zona resuelta tiene un doctor activo en BD, lo prioriza.
    """
    if diagnosis in DIAGNOSIS_ASSIGNMENTS:
        assignment = dict(DIAGNOSIS_ASSIGNMENTS[diagnosis])
    else:
        zone = _zone_from_keywords(diagnosis) or "Medicina General"
        assignment = {"zone": zone, "doctor": "Dr. Equipo de Guardia"}

    try:
        doc = db.find_doctor_by_zone(assignment["zone"])
        if doc and doc.get("name"):
            assignment["doctor"] = (
                f"{doc['name']} ({doc.get('specialty') or assignment['zone']})"
            )
    except Exception:
        pass

    return assignment


def _build_diseases_cache(dataset_path: Path | None = None) -> list:
    """
    Construye (o devuelve cacheado) el resumen de enfermedades a partir de
    un CSV concreto. La cache es por path para soportar varios datasets.
    """
    path = (dataset_path or active_dataset_path()).resolve()
    cache_key = str(path)
    cached = _diseases_cache.get(cache_key)
    if cached is not None:
        return cached
    if not path.exists():
        return []

    diseases: dict = {}
    with path.open(encoding="utf-8") as f:
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
    _diseases_cache[cache_key] = result
    return result


def _invalidate_diseases_cache(dataset_path: Path | None = None) -> None:
    if dataset_path is None:
        _diseases_cache.clear()
    else:
        _diseases_cache.pop(str(dataset_path.resolve()), None)


# ─────────────────────────────────────────────────────────────────────────────
# Notifications helpers
# ─────────────────────────────────────────────────────────────────────────────

def _notify(level: str, title: str, message: str = "", source: str = "system",
            meta: dict | None = None) -> None:
    """Registra evento, inserta notificacion en PostgreSQL y expone via /api/notifications."""
    level_norm = (level or "info").strip().lower()
    log_map = {
        "info": log_notifications.info,
        "success": log_notifications.info,
        "warning": log_notifications.warning,
        "error": log_notifications.error,
    }
    log_fn = log_map.get(level_norm, log_notifications.info)
    log_fn("[%s] %s — %s", source, title, message or "(sin detalle)")

    try:
        meta_str = json.dumps(meta, ensure_ascii=False) if meta else ""
        db.add_notification(title=title, message=message, level=level,
                            source=source, meta=meta_str)
    except Exception as exc:
        log_notifications.error("No se pudo persistir notificacion: %s", exc)


def _detect_new_diagnoses(dataset_path: Path) -> list[str]:
    """
    Compara los diagnosticos del dataset con los que el modelo conoce.
    Devuelve los que NO estaban en el modelo entrenado.
    """
    try:
        info = predictor.get_model_info() or {}
        known = {str(x).strip() for x in (info.get("disease_classes") or [])}
        if not dataset_path.exists():
            return []
        seen: set[str] = set()
        with dataset_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d = (row.get("Diagnosis") or "").strip()
                if d:
                    seen.add(d)
        if not known:
            return sorted(seen)
        return sorted(seen - known)
    except Exception:
        return []


def _parse_symptoms(raw_value) -> list[str]:
    if isinstance(raw_value, list):
        raw_parts = [str(x) for x in raw_value]
    else:
        raw_parts = str(raw_value or "").split(",")
    dedup: dict[str, str] = {}
    for item in raw_parts:
        clean = " ".join(item.strip().split())
        norm = clean.lower()
        if clean and norm not in dedup:
            dedup[norm] = clean
    return list(dedup.values())


# ─────────────────────────────────────────────────────────────────────────────
# Public endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    """Estado operativo para Docker healthcheck y monitorizacion."""
    payload: dict = {
        "status": "ok",
        "models_loaded": predictor.loaded,
        "cnn_loaded": cnn_predictor.loaded,
        "postgres": "ok",
        "mongodb": "ok",
    }
    issues: list[str] = []

    if not predictor.loaded:
        issues.append("modelos tabulares no cargados")
        log_health.warning(
            "Modelos tabulares no disponibles: %s",
            predictor.error or "sin detalle",
        )

    if not cnn_predictor.loaded:
        log_health.warning(
            "Modelo CNN no cargado (opcional): %s",
            cnn_predictor.error or "no entrenado",
        )

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as exc:
        payload["postgres"] = "error"
        issues.append(f"postgresql: {exc}")
        log_health.warning("PostgreSQL no disponible: %s", exc)

    if not mongo.is_connected():
        payload["mongodb"] = "degraded"
        issues.append("mongodb no conectado")
        log_health.warning("MongoDB no disponible para radiologia/CNN historial")

    if issues:
        payload["status"] = "degraded"
        payload["issues"] = issues

    return jsonify(payload), 200


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
    target = active_dataset_path()
    if not target.exists():
        return jsonify({"error": "Dataset no encontrado."}), 404
    with target.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        headers = next(reader, [])
        rows = [row for _, row in zip(range(max_rows), reader)]
    return jsonify({
        "dataset": target.name,
        "headers": headers,
        "rows": rows,
        "total_shown": len(rows),
    }), 200


@app.get("/api/dataset/stats")
@require_auth
def dataset_stats():
    target = active_dataset_path()
    if not target.exists():
        return jsonify({"error": "Dataset no encontrado."}), 404
    diagnoses: dict = {}
    genders: dict = {}
    total = 0
    with target.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            total += 1
            d = row.get("Diagnosis", "Unknown")
            g = row.get("Gender", "Unknown")
            diagnoses[d] = diagnoses.get(d, 0) + 1
            genders[g] = genders.get(g, 0) + 1
    return jsonify({
        "dataset": target.name,
        "total": total,
        "diagnoses": diagnoses,
        "genders": genders,
    }), 200


@app.get("/api/dataset/list")
@require_auth
def dataset_list():
    datasets = []
    active = active_dataset_path().resolve()
    seen_paths: set[str] = set()

    def _push(path: Path, kind: str) -> None:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return
        resolved = str(path.resolve())
        if resolved in seen_paths:
            return
        seen_paths.add(resolved)
        datasets.append({
            "name": path.name,
            "path": str(path),
            "size_kb": round(stat.st_size / 1024),
            "type": kind,
            "active": resolved == str(active),
        })

    if DATASET_PATH.exists():
        _push(DATASET_PATH, "main")
    for f in sorted(UPLOAD_DIR.glob("*.csv")):
        _push(f, "uploaded")

    return jsonify({"datasets": datasets, "active": str(active)}), 200


@app.post("/api/dataset/activate")
@require_auth
def dataset_activate():
    data = request.get_json(silent=True) or {}
    try:
        target = _resolve_training_dataset(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    _write_active_dataset_pointer(target)
    _invalidate_diseases_cache()
    new_dx = _detect_new_diagnoses(target)
    if new_dx:
        _notify(
            "warning",
            "Nuevas enfermedades detectadas",
            "El dataset activo contiene diagnosticos no presentes en el modelo: "
            + ", ".join(new_dx[:8])
            + (" (+ mas)" if len(new_dx) > 8 else "")
            + ". Reentrena el modelo para que los reconozca.",
            source="dataset",
            meta={"diagnoses": new_dx, "dataset": target.name},
        )
    return jsonify({
        "message": "Dataset activo actualizado.",
        "active": str(target),
        "new_diagnoses": new_dx,
    }), 200


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

    # Activate dataset and detect new diagnoses
    _write_active_dataset_pointer(filepath)
    _invalidate_diseases_cache()
    new_dx = _detect_new_diagnoses(filepath)

    auto_train_param = (request.args.get("auto_train")
                        or request.form.get("auto_train")
                        or "").strip().lower()
    auto_train = auto_train_param not in ("0", "false", "no", "off")
    training_started = False
    if auto_train:
        training_started = _start_training_async(filepath)

    if new_dx:
        _notify(
            "warning",
            "Nuevas enfermedades detectadas",
            f"{filepath.name} introduce {len(new_dx)} diagnosticos nuevos: "
            + ", ".join(new_dx[:8])
            + (" (+ mas)" if len(new_dx) > 8 else ""),
            source="dataset",
            meta={"diagnoses": new_dx, "dataset": filepath.name,
                  "auto_train": training_started},
        )
    _notify(
        "info",
        "Dataset subido",
        f"{filepath.name} ({row_count} filas) activado como dataset principal.",
        source="dataset",
        meta={"dataset": filepath.name, "rows": row_count},
    )

    return jsonify({
        "message": "Dataset subido y activado.",
        "filename": safe_name,
        "rows": row_count,
        "new_diagnoses": new_dx,
        "active": True,
        "training_started": training_started,
    }), 200


def _parse_radiology_category(raw: str) -> tuple[str | None, str]:
    """
    Normaliza el parametro category del formulario/consulta.
    Devuelve (None, error) si no es valido, o ("general"|"dental", "") si ok.
    """
    v = (raw or "").strip().lower()
    if v in ("dental", "dentist", "odontologia", "diente", "teeth"):
        return "dental", ""
    if v in ("general", "radiology", "radiografia", "rx", "bodily", "hospital"):
        return "general", ""
    if v == "":
        return "general", ""
    return None, "Categoria debe ser general o dental."


@app.post("/api/radiology/upload")
@require_auth
def radiology_upload():
    cat, cat_err = _parse_radiology_category(request.form.get("category", ""))
    if cat is None:
        return jsonify({"error": cat_err}), 400

    uploads = [f for f in (request.files.getlist("files") or []) if f and getattr(f, "filename", None)]
    single = request.files.get("file")
    if not uploads and single and getattr(single, "filename", None):
        uploads = [single]
    if not uploads:
        return jsonify({"error": "No se encontraron archivos (use files[] o file)."}), 400

    notes = str(request.form.get("notes") or "")
    folder_hint = str(request.form.get("folder_hint") or "")
    uploaded_by = str(request.session.get("username") or "user")

    saved: list[dict] = []
    errors: list[dict[str, str]] = []

    try:
        radiology_store.mongo_client().admin.command("ping")
        for uf in uploads:
            if not uf or not uf.filename:
                continue
            if not radiology_store.validate_extension(uf.filename):
                errors.append({
                    "filename": uf.filename,
                    "error": "Extension no permitida.",
                })
                continue
            uf.stream.seek(0)
            try:
                meta = radiology_store.store_upload(
                    cat,
                    stream=uf.stream,
                    filename=uf.filename,
                    content_type=getattr(uf, "mimetype", None) or "",
                    uploaded_by=uploaded_by,
                    folder_hint=folder_hint,
                    notes=notes,
                )
                saved.append(meta)
            except ValueError as ve:
                errors.append({"filename": uf.filename or "", "error": str(ve)})
    except PyMongoError as exc:
        return jsonify({"error": "MongoDB no disponible.", "detail": str(exc)}), 503
    except OSError as exc:
        return jsonify({"error": "Error accediendo a MongoDB.", "detail": str(exc)}), 503

    if not saved and not errors:
        return jsonify({"error": "Ningun archivo valido procesado."}), 400

    if saved:
        db.add_notification(
            "Radiografias subidas",
            f"{len(saved)} archivo(s) en almacen {cat}"
            + (f" (+{len(errors)} omitidos)." if errors else "."),
            level="success",
            source="radiology",
            meta={
                "category": cat,
                "count": len(saved),
                "errors": len(errors),
            },
        )

    return jsonify({
        "category": cat,
        "uploaded": len(saved),
        "skipped": len(errors),
        "files": saved,
        "errors": errors,
    }), 200


@app.get("/api/radiology/list")
@require_auth
def radiology_list():
    cat, cat_err = _parse_radiology_category(request.args.get("category", "general"))
    if cat is None:
        return jsonify({"error": cat_err}), 400
    try:
        limit = int(request.args.get("limit", "40"))
    except ValueError:
        limit = 40
    try:
        items = radiology_store.list_recent(cat, limit=limit)
    except PyMongoError as exc:
        return jsonify({"error": "MongoDB no disponible.", "detail": str(exc)}), 503
    return jsonify({"category": cat, "items": items}), 200


# ─────────────────────────────────────────────────────────────────────────────
# Diseases endpoint
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_diseases_from_datasets() -> list[dict]:
    """
    Combina las enfermedades del dataset principal y del dataset activo
    (uploaded). Asi tras subir un CSV nuevo, las nuevas enfermedades aparecen
    inmediatamente en la pestana 'Enfermedades' aunque el modelo aun no se haya
    reentrenado.
    """
    paths: list[Path] = []
    if DATASET_PATH.exists():
        paths.append(DATASET_PATH)
    active = active_dataset_path()
    if active.exists() and active.resolve() != DATASET_PATH.resolve():
        paths.append(active)

    merged: dict[str, dict] = {}
    for path in paths:
        for item in _build_diseases_cache(path):
            key = item.get("name", "").strip().lower()
            if not key:
                continue
            if key not in merged:
                merged[key] = {
                    "name": item.get("name"),
                    "count": item.get("count", 0),
                    "common_symptoms": list(item.get("common_symptoms") or []),
                    "avg_age": item.get("avg_age", 0),
                    "gender_distribution": dict(item.get("gender_distribution") or {}),
                    "sources": [path.name],
                }
            else:
                current = merged[key]
                current["count"] = (current.get("count") or 0) + (item.get("count") or 0)
                seen = {s.lower(): s for s in current.get("common_symptoms", [])}
                for sym in item.get("common_symptoms") or []:
                    if sym.lower() not in seen:
                        seen[sym.lower()] = sym
                current["common_symptoms"] = list(seen.values())[:12]
                # Edad media ponderada aproximada
                a1 = current.get("avg_age") or 0
                a2 = item.get("avg_age") or 0
                if a1 and a2:
                    current["avg_age"] = round((a1 + a2) / 2)
                else:
                    current["avg_age"] = a1 or a2
                gd = current.setdefault("gender_distribution", {})
                for g, c in (item.get("gender_distribution") or {}).items():
                    gd[g] = gd.get(g, 0) + c
                current.setdefault("sources", []).append(path.name)
    return list(merged.values())


@app.get("/api/diseases")
@require_auth
def get_diseases():
    try:
        dataset_diseases = _aggregate_diseases_from_datasets()
        manual_diseases = db.list_manual_diseases()
        merged: dict[str, dict] = {}

        for item in dataset_diseases:
            key = item.get("name", "").strip().lower()
            if key:
                merged[key] = dict(item)

        for item in manual_diseases:
            key = item.get("name", "").strip().lower()
            if not key:
                continue
            if key in merged:
                current = merged[key]
                all_syms = {s.lower(): s for s in current.get("common_symptoms", [])}
                for sym in item.get("common_symptoms", []):
                    if sym.lower() not in all_syms:
                        all_syms[sym.lower()] = sym
                current["common_symptoms"] = list(all_syms.values())[:12]
                current["manual"] = True
            else:
                manual_item = dict(item)
                manual_item["manual"] = True
                merged[key] = manual_item

        # Marca enfermedades nuevas (no incluidas en el modelo actual)
        try:
            info = predictor.get_model_info() or {}
            known = {str(x).strip().lower() for x in (info.get("disease_classes") or [])}
        except Exception:
            known = set()
        for item in merged.values():
            name = (item.get("name") or "").strip().lower()
            if name and known and name not in known:
                item["new_for_model"] = True

        result = sorted(
            merged.values(),
            key=lambda x: (-(x.get("count") or 0), x.get("name", "")),
        )
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/diseases/symptoms")
@require_auth
def get_symptoms_bank():
    try:
        saved = {s.lower(): s for s in db.list_symptoms()}
        for item in _aggregate_diseases_from_datasets():
            for sym in item.get("common_symptoms", []):
                key = str(sym or "").strip().lower()
                if key and key not in saved:
                    saved[key] = str(sym).strip()
        return jsonify({"symptoms": sorted(saved.values(), key=lambda x: x.lower())}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Notifications endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/notifications")
@require_auth
def list_notifications_endpoint():
    limit = request.args.get("limit", default=30, type=int)
    only_unread = (request.args.get("unread", "").strip().lower()
                   in ("1", "true", "yes"))
    items = db.list_notifications(limit=limit, only_unread=only_unread)
    unread = db.count_unread_notifications()
    return jsonify({"notifications": items, "unread": unread}), 200


@app.post("/api/notifications/read")
@require_auth
def mark_notifications_read_endpoint():
    data = request.get_json(silent=True) or {}
    raw_ids = data.get("ids")
    ids: list[int] = []
    if isinstance(raw_ids, list):
        for x in raw_ids:
            try:
                ids.append(int(x))
            except Exception:
                continue
    affected = db.mark_notifications_read(ids if ids else None)
    return jsonify({"updated": affected, "unread": db.count_unread_notifications()}), 200


@app.delete("/api/notifications")
@require_auth
def clear_notifications_endpoint():
    removed = db.clear_notifications()
    return jsonify({"deleted": removed, "unread": 0}), 200


@app.post("/api/diseases")
@require_auth
def create_or_update_disease():
    data = request.get_json(silent=True) or {}
    disease_name = str(data.get("name", "")).strip()
    symptoms = _parse_symptoms(data.get("symptoms", []))
    if not disease_name:
        return jsonify({"error": "Nombre de enfermedad requerido."}), 400
    if not symptoms:
        return jsonify({"error": "Debes indicar al menos un sintoma."}), 400
    try:
        saved = db.upsert_manual_disease(
            disease_name,
            symptoms,
            created_by=request.session.get("username", ""),
        )
        return jsonify({"message": "Enfermedad guardada correctamente.", "disease": saved}), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
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
                source_dataset=active_dataset_path().name,
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
            max_rows = max(1, int(max_rows))
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
            "imported": result.get("inserted", 0),
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
    target = active_dataset_path()
    if target.exists():
        with target.open(encoding="utf-8") as f:
            dataset_total = sum(1 for _ in f) - 1

    model_info = predictor.get_model_info()

    return jsonify({
        "dataset_total_rows": dataset_total,
        "active_dataset": target.name,
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
    target = active_dataset_path()
    if not target.exists():
        return jsonify({"error": "Dataset no encontrado."}), 404

    symptom_pairs: dict = {}
    age_by_disease: dict = {}
    with target.open(encoding="utf-8") as f:
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
        "active_dataset": target.name,
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
    if anomalies:
        log_health.warning(
            "IsolationForest: %s anomalias en %s pacientes revisados",
            len(anomalies),
            len(patients),
        )
        _notify(
            "warning",
            "Anomalias detectadas",
            f"{len(anomalies)} paciente(s) con perfil clinico atipico.",
            source="analytics",
            meta={"checked": len(patients), "anomalies_count": len(anomalies)},
        )
    else:
        log_health.info("Anomalias: 0 de %s pacientes", len(patients))

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
        if report.get("ok"):
            summary = report.get("summary", {})
            _notify(
                "info",
                "Pipeline ETL completado",
                (
                    f"{dataset_path.name}: {summary.get('rows_raw', 0)} → "
                    f"{summary.get('rows_final', 0)} filas en {summary.get('total_elapsed_ms', 0)} ms"
                ),
                source="pipeline",
                meta={"dataset": dataset_path.name, "summary": summary},
            )
        else:
            failed_stages = [
                s.get("stage") for s in report.get("stages", []) if not s.get("ok")
            ]
            failed_stage = report.get("summary", {}).get("failed_stage") or (
                failed_stages[0] if failed_stages else "desconocido"
            )
            _notify(
                "warning",
                "Pipeline terminado con errores",
                f"{dataset_path.name}: etapa fallida «{failed_stage}»",
                source="pipeline",
                meta={"dataset": dataset_path.name, "failed": failed_stages},
            )
        return jsonify(report), 200
    except Exception as exc:
        get_logger("pipeline").exception("Excepcion en POST /api/dataset/pipeline")
        _notify(
            "error",
            "Excepcion en el pipeline",
            f"{dataset_path.name}: {exc}",
            source="pipeline",
            meta={"dataset": dataset_path.name},
        )
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
    <li><strong>Backend:</strong> Flask (Python 3.13) + PostgreSQL.</li>
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
@require_auth
def report_view():
    model_info = predictor.get_model_info()
    eda = db.patients_eda()
    target = active_dataset_path()
    dataset_rows = 0
    if target.exists():
        with target.open(encoding="utf-8") as f:
            dataset_rows = max(0, sum(1 for _ in f) - 1)

    def pct(x):
        return f"{x * 100:.1f}%" if isinstance(x, (int, float)) else "—"

    html = render_template_string(
        _REPORT_TEMPLATE,
        generated_at=__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        dataset_name=target.name,
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


@app.get("/api/doctors")
@require_auth
def list_doctors():
    try:
        return jsonify({"doctors": db.list_doctors()}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/doctors")
@require_admin
def create_doctor():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    specialty = str(data.get("specialty", "")).strip()
    zone = str(data.get("zone", "")).strip()
    if not name or not specialty or not zone:
        return jsonify({"error": "Campos requeridos: name, specialty, zone"}), 400
    try:
        doctor = db.create_doctor(
            name=name,
            specialty=specialty,
            zone=zone,
            email=str(data.get("email", "")).strip(),
            phone=str(data.get("phone", "")).strip(),
            shift=str(data.get("shift", "")).strip(),
            notes=str(data.get("notes", "")).strip(),
        )
        return jsonify({"message": "Doctor creado.", "doctor": doctor}), 201
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.put("/api/doctors/<int:doctor_id>")
@require_admin
def update_doctor(doctor_id: int):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    specialty = str(data.get("specialty", "")).strip()
    zone = str(data.get("zone", "")).strip()
    if not name or not specialty or not zone:
        return jsonify({"error": "Campos requeridos: name, specialty, zone"}), 400
    try:
        ok = db.update_doctor(
            doctor_id=doctor_id,
            name=name,
            specialty=specialty,
            zone=zone,
            email=str(data.get("email", "")).strip(),
            phone=str(data.get("phone", "")).strip(),
            shift=str(data.get("shift", "")).strip(),
            notes=str(data.get("notes", "")).strip(),
        )
        if not ok:
            return jsonify({"error": "Doctor no encontrado."}), 404
        return jsonify({"message": "Doctor actualizado."}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# CNN — Clasificación de radiografías de tórax
# ─────────────────────────────────────────────────────────────────────────────

_CNN_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
CNN_TRAIN_SCRIPT = ROOT_DIR / "models-ia" / "train_cnn.py"
_cnn_training_status: dict = {"running": False, "last_result": None, "last_error": None}


def _run_cnn_training(epochs: int = 12) -> None:
    global _cnn_training_status
    _cnn_training_status.update({
        "running": True,
        "last_result": None,
        "last_error": None,
        "epochs": epochs,
    })
    _notify(
        "info",
        "Entrenamiento CNN iniciado",
        f"MobileNetV2 — {epochs} épocas (requiere datasets/ en el servidor).",
        source="training",
        meta={"epochs": epochs},
    )
    log_training.info("CNN training iniciado | epochs=%s | cwd=%s", epochs, ROOT_DIR)
    cmd = [
        sys.executable,
        str(CNN_TRAIN_SCRIPT),
        "--epochs",
        str(epochs),
        "--no-mongo",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,
            cwd=str(ROOT_DIR),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        if result.returncode == 0:
            cnn_predictor.reload()
            _cnn_training_status["last_result"] = "ok"
            log_training.info("CNN training completado correctamente")
            _notify(
                "success",
                "Entrenamiento CNN completado",
                "Modelo radiografías actualizado y recargado.",
                source="training",
            )
        else:
            err = (result.stderr or result.stdout or "Error desconocido").strip()
            _cnn_training_status["last_error"] = err[-4000:]
            log_training.error("CNN training fallido | returncode=%s", result.returncode)
            for line in _cnn_training_status["last_error"].splitlines()[-20:]:
                log_training.error("[cnn-train] %s", line)
            _notify(
                "error",
                "Fallo entrenamiento CNN",
                _cnn_training_status["last_error"][-500:],
                source="training",
                meta={"returncode": result.returncode},
            )
    except subprocess.TimeoutExpired:
        _cnn_training_status["last_error"] = "Timeout: entrenamiento CNN superó 2 horas."
        log_training.error("CNN training timeout")
        _notify("error", "CNN timeout", _cnn_training_status["last_error"], source="training")
    except Exception as exc:
        _cnn_training_status["last_error"] = str(exc)
        log_training.exception("Excepcion en entrenamiento CNN")
        _notify("error", "Excepcion CNN", str(exc), source="training")
    finally:
        _cnn_training_status["running"] = False


@app.post("/api/cnn/predict")
@require_auth
def cnn_predict():
    """
    Clasifica una radiografía de tórax.
    Body: multipart/form-data con campo 'image' (archivo de imagen).
    Opcional: campo 'patient_id' (string).
    """
    if "image" not in request.files:
        return jsonify({"error": "Se requiere un archivo en el campo 'image'."}), 400

    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "Nombre de archivo vacío."}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in _CNN_ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Formato no permitido. Usa: {', '.join(_CNN_ALLOWED_EXTENSIONS)}"}), 415

    if not cnn_predictor.loaded:
        return jsonify({
            "error": "Modelo CNN no disponible.",
            "detail": cnn_predictor.error,
            "hint": "Entrena el modelo primero en la sección Radiografías.",
        }), 503

    try:
        image_bytes = file.read()
        patient_id = request.form.get("patient_id", "").strip() or None
        user = request.session.get("username", "")

        result = cnn_predictor.predict(image_bytes, filename=file.filename)

        if result.get("clinical_alert"):
            log_notifications.warning(
                "Alerta clinica CNN | %s | conf=%s%% | archivo=%s",
                result.get("label"),
                result.get("confidence_pct"),
                file.filename,
            )
            _notify(
                "warning",
                "Alerta radiológica",
                result.get("alert_message") or result.get("label", "Patología detectada"),
                source="cnn",
                meta={
                    "class": result.get("class"),
                    "confidence": result.get("confidence"),
                    "filename": file.filename,
                },
            )

        mongo_id = mongo.save_xray_prediction(result, patient_id=patient_id, user=user)
        result["mongo_id"] = mongo_id

        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"error": f"Error en clasificación: {exc}"}), 500


@app.get("/api/cnn/model-info")
@require_auth
def cnn_model_info():
    """Devuelve info del modelo CNN y métricas de entrenamiento."""
    info = cnn_predictor.get_model_info()
    # Complementar con métricas en MongoDB si están disponibles
    if mongo.is_connected():
        mongo_metrics = mongo.get_latest_cnn_metrics()
        if mongo_metrics:
            info["mongo_metrics"] = mongo_metrics
    info["mongodb"] = mongo.connection_info()
    return jsonify(info), 200


@app.get("/api/cnn/history")
@require_auth
def cnn_history():
    """Historial de predicciones CNN almacenadas en MongoDB."""
    limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(limit, 200))
    class_filter = request.args.get("class", "").strip() or None
    predictions = mongo.get_xray_predictions(limit=limit, class_filter=class_filter)
    return jsonify({"count": len(predictions), "predictions": predictions}), 200


@app.get("/api/cnn/stats")
@require_auth
def cnn_stats():
    """Estadísticas agregadas de predicciones CNN desde MongoDB."""
    return jsonify(mongo.get_xray_stats()), 200


@app.post("/api/cnn/train")
@require_admin
def cnn_train():
    """Lanza el entrenamiento del modelo CNN en segundo plano (admin only)."""
    if _cnn_training_status["running"]:
        return jsonify({"status": "already_running", "message": "Entrenamiento CNN ya en curso."}), 409
    if not CNN_TRAIN_SCRIPT.exists():
        log_training.error("Script CNN no encontrado: %s", CNN_TRAIN_SCRIPT)
        return jsonify({"error": f"Script no encontrado: {CNN_TRAIN_SCRIPT}"}), 404
    data = request.get_json(silent=True) or {}
    try:
        epochs = int(data.get("epochs", 12))
    except (TypeError, ValueError):
        epochs = 12
    epochs = max(2, min(epochs, 50))
    threading.Thread(target=_run_cnn_training, args=(epochs,), daemon=True).start()
    log_training.info("Hilo CNN training lanzado | epochs=%s", epochs)
    return jsonify({
        "status": "started",
        "message": "Entrenamiento CNN iniciado en segundo plano.",
        "epochs": epochs,
    }), 202


@app.get("/api/cnn/train-status")
@require_auth
def cnn_train_status():
    return jsonify({
        "running":      _cnn_training_status["running"],
        "last_result":  _cnn_training_status["last_result"],
        "last_error":   _cnn_training_status["last_error"],
        "epochs":       _cnn_training_status.get("epochs"),
        "model_loaded": cnn_predictor.loaded,
        "script_path":  str(CNN_TRAIN_SCRIPT),
        "script_exists": CNN_TRAIN_SCRIPT.exists(),
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOSPITAL_HOST", "127.0.0.1"),
        port=int(os.environ.get("HOSPITAL_PORT", "8000")),
        debug=os.environ.get("HOSPITAL_DEBUG", "0") == "1",
    )
