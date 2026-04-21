"""
Hospital AI - Modulo de inferencia
===================================
Carga el bundle .joblib generado por train_spark.py y expone metodos de:

  * Prediccion de enfermedad (clasificacion multiclase)
  * Clasificacion de riesgo (Low / Medium / High)
  * Deteccion de anomalias (IsolationForest)

La inferencia usa exactamente las mismas features que el entrenamiento
(sintomas TF-IDF + edad + genero codificado). No se usa `days_stayed`
porque no esta disponible en la fase de admision del paciente.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import scipy.sparse as sp

ROOT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT_DIR / "models-ia" / "models"
MODEL_BUNDLE_PATH = MODELS_DIR / "healthcare_models.joblib"
METRICS_PATH = MODELS_DIR / "metrics.json"

try:
    import joblib
    _JOBLIB_AVAILABLE = True
except ImportError:
    _JOBLIB_AVAILABLE = False


GENDER_MAP = {"male": 1, "female": 0, "other": 2}


class HealthcarePredictor:
    """Wrapper de los modelos entrenados. Thread-safe para lectura."""

    def __init__(self) -> None:
        self._bundle: dict[str, Any] | None = None
        self.loaded: bool = False
        self.error: str = ""

    def load(self) -> bool:
        if not _JOBLIB_AVAILABLE:
            self.error = "joblib no esta instalado. Ejecuta: pip install joblib"
            return False
        if not MODEL_BUNDLE_PATH.exists():
            self.error = (
                "Modelos no encontrados. "
                "Ejecuta primero: python models-ia/train_spark.py"
            )
            return False
        try:
            self._bundle = joblib.load(MODEL_BUNDLE_PATH)
            self.loaded = True
            self.error = ""
            return True
        except Exception as exc:
            self.error = f"Error al cargar modelos: {exc}"
            return False

    def reload(self) -> bool:
        self._bundle = None
        self.loaded = False
        return self.load()

    def _encode(self, symptoms: str, age: int, gender: str, tfidf) -> sp.csr_matrix:
        gender_enc = GENDER_MAP.get(str(gender).lower().strip(), 2)
        sym_feat = tfidf.transform([str(symptoms).lower().strip()])
        num_feat = sp.csr_matrix([[float(age), float(gender_enc)]])
        return sp.hstack([sym_feat, num_feat]).tocsr()

    def _assert_loaded(self) -> None:
        if not self.loaded or self._bundle is None:
            raise RuntimeError(
                self.error or "Modelos no cargados. Llama a .load() primero."
            )

    def predict_disease(self, age: int, gender: str, symptoms: str) -> dict[str, Any]:
        self._assert_loaded()
        b = self._bundle
        X = self._encode(symptoms, age, gender, b["tfidf_disease"])
        rf = b["disease_model"]
        le = b["le_disease"]

        probas = rf.predict_proba(X)[0]
        pred_idx = int(np.argmax(probas))

        top_idx = np.argsort(probas)[::-1][:5]
        top = [
            {
                "disease": le.inverse_transform([i])[0],
                "probability": round(float(probas[i]), 4),
                "percentage": round(float(probas[i]) * 100, 1),
            }
            for i in top_idx
            if probas[i] > 0.005
        ]
        return {
            "predicted_disease": le.inverse_transform([pred_idx])[0],
            "confidence": round(float(probas[pred_idx]), 4),
            "confidence_pct": round(float(probas[pred_idx]) * 100, 1),
            "top_predictions": top,
        }

    def classify_risk(self, age: int, gender: str, symptoms: str) -> dict[str, Any]:
        self._assert_loaded()
        b = self._bundle
        X = self._encode(symptoms, age, gender, b["tfidf_risk"])
        rf = b["risk_model"]
        le = b["le_risk"]

        probas = rf.predict_proba(X)[0]
        pred_idx = int(np.argmax(probas))
        level = le.inverse_transform([pred_idx])[0]

        risk_probas = {
            cls: round(float(probas[i]), 4)
            for i, cls in enumerate(le.classes_)
        }

        recommendations = {
            "Low": [
                "Monitoreo rutinario cada 6 meses.",
                "Mantener habitos saludables y actividad fisica.",
                "Revision anual de signos vitales.",
            ],
            "Medium": [
                "Seguimiento medico cada 2-3 meses.",
                "Analisis de laboratorio completo.",
                "Evaluar ajustes de medicacion.",
                "Dieta y ejercicio supervisados.",
            ],
            "High": [
                "Atencion medica urgente.",
                "Hospitalizacion o monitoreo intensivo.",
                "Consulta con especialista.",
                "Revision diaria de signos vitales.",
            ],
        }
        return {
            "risk_level": level,
            "confidence": round(float(probas[pred_idx]), 4),
            "confidence_pct": round(float(probas[pred_idx]) * 100, 1),
            "risk_probabilities": risk_probas,
            "recommendations": recommendations.get(level, []),
        }

    def anomaly_score(self, age: int, gender: str, symptoms: str) -> dict[str, Any]:
        self._assert_loaded()
        b = self._bundle
        iso = b.get("anomaly_model")
        if iso is None:
            return {"available": False, "reason": "anomaly_model no entrenado"}
        X = self._encode(symptoms, age, gender, b["tfidf_disease"])
        score = float(iso.decision_function(X)[0])
        is_anomaly = bool(iso.predict(X)[0] == -1)
        return {
            "available": True,
            "is_anomaly": is_anomaly,
            "score": round(score, 4),
        }

    def get_model_info(self) -> dict[str, Any]:
        if not self.loaded or self._bundle is None:
            if METRICS_PATH.exists():
                with open(METRICS_PATH, encoding="utf-8") as f:
                    metrics = json.load(f)
                return {"loaded": False, "metrics_available": True, **metrics}
            return {"loaded": False, "error": self.error}
        metrics = self._bundle.get("metrics", {})
        return {"loaded": True, **metrics}


predictor = HealthcarePredictor()
