"""
CNN Predictor — Inferencia de Radiografías de Tórax
=====================================================
Carga el modelo MobileNetV2 entrenado y clasifica imágenes en:
  0 → normal    1 → pneumonia    2 → covid
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR       = Path(__file__).resolve().parent.parent
MODELS_DIR     = ROOT_DIR / "models-ia" / "models"
CNN_MODEL_PATH = MODELS_DIR / "cnn_xray_model.keras"
CNN_METRICS    = MODELS_DIR / "cnn_metrics.json"

CLASSES      = ["normal", "pneumonia", "covid"]
CLASS_LABELS = {
    "normal":    "Sana",
    "pneumonia": "Neumonía",
    "covid":     "COVID-19",
}
IMG_SIZE = (224, 224)

# Umbral mínimo de confianza para emitir alerta clínica
ALERT_THRESHOLD = 0.60


class CNNPredictor:
    """Wrapper del modelo CNN. Thread-safe para lectura."""

    def __init__(self) -> None:
        self._model = None
        self.loaded: bool = False
        self.error: str = ""

    def load(self) -> bool:
        if not CNN_MODEL_PATH.exists():
            self.error = (
                "Modelo CNN no encontrado. "
                "Entrena primero: python models-ia/train_cnn.py"
            )
            return False
        try:
            import tensorflow as tf
            self._model = tf.keras.models.load_model(str(CNN_MODEL_PATH))
            self.loaded = True
            self.error = ""
            print(f"[CNN] Modelo cargado desde {CNN_MODEL_PATH}")
            return True
        except Exception as exc:
            self.error = f"Error al cargar modelo CNN: {exc}"
            return False

    def reload(self) -> bool:
        self._model = None
        self.loaded = False
        return self.load()

    def _preprocess(self, image_bytes: bytes) -> np.ndarray:
        """Convierte bytes de imagen a tensor normalizado (1, 224, 224, 3)."""
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = img.resize(IMG_SIZE, Image.LANCZOS)
        arr = np.array(img, dtype=np.float32) / 255.0
        return np.expand_dims(arr, axis=0)

    def predict(self, image_bytes: bytes, filename: str = "imagen") -> dict[str, Any]:
        """
        Clasifica una radiografía y devuelve predicción con métricas clínicas.

        Returns
        -------
        {
          "class": "covid",
          "label": "COVID-19",
          "confidence": 0.923,
          "confidence_pct": 92.3,
          "probabilities": {"normal": 0.02, "pneumonia": 0.06, "covid": 0.92},
          "clinical_alert": True,
          "alert_message": "...",
          "filename": "rx_001.jpg"
        }
        """
        if not self.loaded or self._model is None:
            raise RuntimeError(self.error or "Modelo CNN no cargado.")

        tensor = self._preprocess(image_bytes)
        proba = self._model.predict(tensor, verbose=0)[0]

        pred_idx = int(np.argmax(proba))
        pred_class = CLASSES[pred_idx]
        confidence = float(proba[pred_idx])

        probabilities = {cls: round(float(proba[i]), 4) for i, cls in enumerate(CLASSES)}

        # Alerta clínica para enfermedades contagiosas con confianza suficiente
        clinical_alert = pred_class in ("covid", "pneumonia") and confidence >= ALERT_THRESHOLD
        alert_message = ""
        if pred_class == "covid" and confidence >= ALERT_THRESHOLD:
            alert_message = (
                f"ALERTA: Posible COVID-19 detectado ({confidence*100:.1f}% confianza). "
                "Aislar al paciente y confirmar con PCR. "
                "Un falso negativo en COVID implica riesgo de contagio masivo."
            )
        elif pred_class == "pneumonia" and confidence >= ALERT_THRESHOLD:
            alert_message = (
                f"ALERTA: Posible Neumonía detectada ({confidence*100:.1f}% confianza). "
                "Evaluar tratamiento antibiótico/antiviral urgente. "
                "Un falso negativo puede derivar en sepsis."
            )

        return {
            "class": pred_class,
            "label": CLASS_LABELS[pred_class],
            "confidence": round(confidence, 4),
            "confidence_pct": round(confidence * 100, 1),
            "probabilities": probabilities,
            "clinical_alert": clinical_alert,
            "alert_message": alert_message,
            "filename": filename,
        }

    def get_model_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "loaded": self.loaded,
            "model_path": str(CNN_MODEL_PATH),
            "model_exists": CNN_MODEL_PATH.exists(),
            "classes": CLASSES,
            "class_labels": CLASS_LABELS,
            "input_size": list(IMG_SIZE),
        }
        if not self.loaded:
            info["error"] = self.error
        if CNN_METRICS.exists():
            try:
                with open(CNN_METRICS, encoding="utf-8") as f:
                    info["metrics"] = json.load(f)
            except Exception:
                pass
        return info


cnn_predictor = CNNPredictor()
