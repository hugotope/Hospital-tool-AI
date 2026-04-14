"""
Hospital AI — Módulo de predicción
====================================
Carga el bundle .joblib generado por train_spark.py y expone
métodos de inferencia para Flask.
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

# Importación diferida para no bloquear Flask si joblib no está instalado
try:
    import joblib
    _JOBLIB_AVAILABLE = True
except ImportError:
    _JOBLIB_AVAILABLE = False


class HealthcarePredictor:
    """Wrapper de los modelos entrenados.  Thread-safe para lectura."""

    def __init__(self) -> None:
        self._bundle: dict[str, Any] | None = None
        self.loaded: bool = False
        self.error: str = ""

    # ── Carga ──────────────────────────────────────────────────────────────

    def load(self) -> bool:
        """
        Intenta cargar el bundle de modelos.
        Devuelve True si tuvo éxito, False en caso contrario.
        """
        if not _JOBLIB_AVAILABLE:
            self.error = "joblib no está instalado. Ejecuta: pip install joblib"
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
        """Fuerza recarga (útil tras re-entrenamiento)."""
        self._bundle = None
        self.loaded = False
        return self.load()

    # ── Helpers ────────────────────────────────────────────────────────────

    def _encode_input(
        self,
        symptoms: str,
        age: int,
        gender: str,
        tfidf,
    ) -> sp.csr_matrix:
        gender_map = {"male": 1, "female": 0, "other": 2}
        gender_enc = gender_map.get(gender.lower().strip(), 2)
        sym_feat = tfidf.transform([symptoms.lower().strip()])
        num_feat = sp.csr_matrix([[age, gender_enc, 0]])  # days_stayed=0 en inference
        return sp.hstack([sym_feat, num_feat])

    def _assert_loaded(self) -> None:
        if not self.loaded or self._bundle is None:
            raise RuntimeError(
                self.error or "Modelos no cargados. Llama a .load() primero."
            )

    # ── Predicción de enfermedad ───────────────────────────────────────────

    def predict_disease(
        self, age: int, gender: str, symptoms: str
    ) -> dict[str, Any]:
        """
        Predice la enfermedad más probable y devuelve las 5 principales
        con sus probabilidades.
        """
        self._assert_loaded()

        b = self._bundle
        X = self._encode_input(symptoms, age, gender, b["tfidf_disease"])
        rf = b["disease_model"]
        le = b["le_disease"]

        pred_idx = rf.predict(X)[0]
        probas = rf.predict_proba(X)[0]

        top5_idx = np.argsort(probas)[::-1][:5]
        top5 = [
            {
                "disease": le.inverse_transform([i])[0],
                "probability": round(float(probas[i]), 4),
                "percentage": round(float(probas[i]) * 100, 1),
            }
            for i in top5_idx
            if probas[i] > 0.005
        ]

        return {
            "predicted_disease": le.inverse_transform([pred_idx])[0],
            "confidence": round(float(probas[pred_idx]), 4),
            "confidence_pct": round(float(probas[pred_idx]) * 100, 1),
            "top_predictions": top5,
        }

    # ── Clasificación de riesgo ────────────────────────────────────────────

    def classify_risk(
        self, age: int, gender: str, symptoms: str
    ) -> dict[str, Any]:
        """
        Clasifica el nivel de riesgo del paciente: Low / Medium / High.
        """
        self._assert_loaded()

        b = self._bundle
        X = self._encode_input(symptoms, age, gender, b["tfidf_risk"])
        rf = b["risk_model"]
        le = b["le_risk"]

        pred_idx = rf.predict(X)[0]
        probas = rf.predict_proba(X)[0]

        risk_level = le.inverse_transform([pred_idx])[0]
        risk_probas = {
            cls: round(float(probas[i]), 4)
            for i, cls in enumerate(le.classes_)
        }

        # Recomendaciones según nivel
        recommendations = {
            "Low": [
                "Monitoreo rutinario cada 6 meses.",
                "Mantener hábitos saludables y actividad física.",
                "Revisión de signos vitales en consulta anual.",
            ],
            "Medium": [
                "Seguimiento médico cada 2-3 meses.",
                "Análisis de laboratorio completo.",
                "Evaluar posibles cambios en medicación.",
                "Dieta y ejercicio supervisados.",
            ],
            "High": [
                "Atención médica inmediata o urgente.",
                "Hospitalización o monitoreo intensivo recomendado.",
                "Consulta con especialista urgente.",
                "Revisión diaria de signos vitales.",
                "Consideración de intervención quirúrgica si aplica.",
            ],
        }

        return {
            "risk_level": risk_level,
            "confidence": round(float(probas[pred_idx]), 4),
            "confidence_pct": round(float(probas[pred_idx]) * 100, 1),
            "risk_probabilities": risk_probas,
            "recommendations": recommendations.get(risk_level, []),
        }

    # ── Info del modelo ────────────────────────────────────────────────────

    def get_model_info(self) -> dict[str, Any]:
        """Devuelve métricas y metadatos del modelo cargado."""
        if not self.loaded or self._bundle is None:
            # Intentar leer solo el JSON de métricas
            if METRICS_PATH.exists():
                with open(METRICS_PATH, encoding="utf-8") as f:
                    metrics = json.load(f)
                return {"loaded": False, "metrics_available": True, **metrics}
            return {"loaded": False, "error": self.error}

        metrics = self._bundle.get("metrics", {})
        return {
            "loaded": True,
            **metrics,
        }


# Singleton global para Flask
predictor = HealthcarePredictor()
