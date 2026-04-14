from __future__ import annotations

import csv
import subprocess
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

from ai_predictor import predictor

app = Flask(__name__)
CORS(app)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT_DIR / "healthcare_dataset_100k.csv"
TRAIN_SCRIPT = ROOT_DIR / "models-ia" / "train_spark.py"

# Estado del entrenamiento en background
_training_status: dict = {"running": False, "last_result": None, "last_error": None}

# Cargar modelos al arrancar (si ya existen)
predictor.load()


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────

def _run_training() -> None:
    """Ejecuta el script de entrenamiento en un hilo separado."""
    global _training_status
    _training_status["running"] = True
    _training_status["last_result"] = None
    _training_status["last_error"] = None
    try:
        result = subprocess.run(
            [sys.executable, str(TRAIN_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=900,  # 15 min máximo
        )
        if result.returncode == 0:
            predictor.reload()
            _training_status["last_result"] = "ok"
        else:
            _training_status["last_error"] = result.stderr[-2000:] if result.stderr else "Error desconocido"
    except subprocess.TimeoutExpired:
        _training_status["last_error"] = "Timeout: el entrenamiento superó 15 minutos."
    except Exception as exc:
        _training_status["last_error"] = str(exc)
    finally:
        _training_status["running"] = False


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "models_loaded": predictor.loaded}, 200


# ─────────────────────────────────────────────────────────────────────────────
# Dataset
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/dataset/preview")
def dataset_preview():
    max_rows = request.args.get("rows", default=12, type=int)
    max_rows = max(1, min(max_rows, 100))

    if not DATASET_PATH.exists():
        return jsonify({"error": "Dataset no encontrado"}), 404

    with DATASET_PATH.open(mode="r", encoding="utf-8", newline="") as csvfile:
        reader = csv.reader(csvfile)
        headers = next(reader, [])
        rows = [row for _, row in zip(range(max_rows), reader)]

    return jsonify({"headers": headers, "rows": rows}), 200


@app.get("/api/dataset/stats")
def dataset_stats():
    """Devuelve estadísticas básicas del dataset."""
    if not DATASET_PATH.exists():
        return jsonify({"error": "Dataset no encontrado"}), 404

    diagnoses: dict = {}
    genders: dict = {}
    total = 0

    with DATASET_PATH.open(mode="r", encoding="utf-8", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            total += 1
            d = row.get("Diagnosis", "Unknown")
            g = row.get("Gender", "Unknown")
            diagnoses[d] = diagnoses.get(d, 0) + 1
            genders[g] = genders.get(g, 0) + 1

    return jsonify({"total": total, "diagnoses": diagnoses, "genders": genders}), 200


# ─────────────────────────────────────────────────────────────────────────────
# AI — Predicción de enfermedad
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/ai/predict-disease")
def predict_disease():
    """
    Body JSON: { "age": int, "gender": str, "symptoms": str }
    """
    data = request.get_json(silent=True) or {}
    age = data.get("age")
    gender = data.get("gender", "")
    symptoms = data.get("symptoms", "")

    if age is None or not gender or not symptoms:
        return jsonify({"error": "Campos requeridos: age, gender, symptoms"}), 400

    if not predictor.loaded:
        return jsonify({"error": predictor.error or "Modelos no cargados"}), 503

    try:
        result = predictor.predict_disease(int(age), str(gender), str(symptoms))
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# AI — Clasificación de riesgo
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/ai/classify-risk")
def classify_risk():
    """
    Body JSON: { "age": int, "gender": str, "symptoms": str }
    """
    data = request.get_json(silent=True) or {}
    age = data.get("age")
    gender = data.get("gender", "")
    symptoms = data.get("symptoms", "")

    if age is None or not gender or not symptoms:
        return jsonify({"error": "Campos requeridos: age, gender, symptoms"}), 400

    if not predictor.loaded:
        return jsonify({"error": predictor.error or "Modelos no cargados"}), 503

    try:
        result = predictor.classify_risk(int(age), str(gender), str(symptoms))
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# AI — Análisis completo (predicción + riesgo en una sola llamada)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/ai/analyze")
def analyze_patient():
    """
    Predicción de enfermedad + clasificación de riesgo en una sola llamada.
    Body JSON: { "age": int, "gender": str, "symptoms": str }
    """
    data = request.get_json(silent=True) or {}
    age = data.get("age")
    gender = data.get("gender", "")
    symptoms = data.get("symptoms", "")

    if age is None or not gender or not symptoms:
        return jsonify({"error": "Campos requeridos: age, gender, symptoms"}), 400

    if not predictor.loaded:
        return jsonify({"error": predictor.error or "Modelos no cargados"}), 503

    try:
        disease_result = predictor.predict_disease(int(age), str(gender), str(symptoms))
        risk_result = predictor.classify_risk(int(age), str(gender), str(symptoms))
        return jsonify({"disease": disease_result, "risk": risk_result}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# AI — Info del modelo
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/ai/model-info")
def model_info():
    return jsonify(predictor.get_model_info()), 200


# ─────────────────────────────────────────────────────────────────────────────
# AI — Entrenamiento
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/ai/train")
def train_models():
    """
    Lanza el entrenamiento en background.
    Devuelve inmediatamente con status 'started'.
    Sondear /api/ai/train-status para ver el resultado.
    """
    if _training_status["running"]:
        return jsonify({"status": "already_running", "message": "El entrenamiento ya está en curso."}), 409

    if not TRAIN_SCRIPT.exists():
        return jsonify({"error": f"Script de entrenamiento no encontrado: {TRAIN_SCRIPT}"}), 404

    thread = threading.Thread(target=_run_training, daemon=True)
    thread.start()

    return jsonify({"status": "started", "message": "Entrenamiento iniciado en segundo plano."}), 202


@app.get("/api/ai/train-status")
def train_status():
    return jsonify({
        "running": _training_status["running"],
        "last_result": _training_status["last_result"],
        "last_error": _training_status["last_error"],
        "models_loaded": predictor.loaded,
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
