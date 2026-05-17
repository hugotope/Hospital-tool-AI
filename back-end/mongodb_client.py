"""
MongoDB Client — Hospital AI
=============================
Gestiona la conexión a MongoDB y las colecciones:
  - xray_predictions : resultados de clasificación de radiografías
  - cnn_training_logs: métricas de entrenamiento del modelo CNN

Configuración via variables de entorno (o valores por defecto locales):
  MONGO_URI  → mongodb://localhost:27017  (por defecto)
  MONGO_DB   → hospital_ai               (por defecto)

Si MongoDB no está disponible el cliente opera en modo "sin conexión"
y las operaciones simplemente se omiten (el resto del sistema funciona).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb://hospital:hospital@localhost:27017/?authSource=admin",
)
MONGO_DB = os.environ.get("MONGO_DB", "hospital_ai")


class MongoClient:
    """Wrapper ligero de pymongo con manejo seguro de errores."""

    def __init__(self) -> None:
        self._client = None
        self._db     = None
        self._connected: bool = False
        self._error: str = ""
        self._connect()

    def _connect(self) -> None:
        try:
            import pymongo
            client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            # Forzar handshake para detectar si MongoDB está activo
            client.admin.command("ping")
            self._client = client
            self._db     = client[MONGO_DB]
            self._connected = True
            self._ensure_indexes()
            print(f"[MongoDB] Conectado a {MONGO_URI} / {MONGO_DB}")
        except Exception as exc:
            self._connected = False
            self._error = str(exc)
            print(f"[MongoDB] No disponible ({exc}). Funcionando sin MongoDB.")

    def is_connected(self) -> bool:
        return self._connected

    def connection_info(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "uri": MONGO_URI,
            "database": MONGO_DB,
            "error": self._error if not self._connected else None,
        }

    # ── Índices ───────────────────────────────────────────────────────────────

    def _ensure_indexes(self) -> None:
        if not self._connected or self._db is None:
            return
        try:
            self._db["xray_predictions"].create_index(
                [("timestamp", -1)], background=True)
            self._db["xray_predictions"].create_index(
                [("predicted_class", 1)], background=True)
            self._db["cnn_training_logs"].create_index(
                [("trained_at", -1)], background=True)
        except Exception:
            pass

    # ── Predicciones de radiografías ─────────────────────────────────────────

    def save_xray_prediction(self, prediction: dict[str, Any],
                              patient_id: str | None = None,
                              user: str | None = None) -> str | None:
        """Guarda el resultado de una predicción CNN en MongoDB."""
        if not self._connected or self._db is None:
            return None
        try:
            doc = {
                "timestamp":       datetime.now(tz=timezone.utc),
                "filename":        prediction.get("filename", ""),
                "predicted_class": prediction.get("class", ""),
                "predicted_label": prediction.get("label", ""),
                "confidence":      prediction.get("confidence", 0.0),
                "probabilities":   prediction.get("probabilities", {}),
                "clinical_alert":  prediction.get("clinical_alert", False),
                "alert_message":   prediction.get("alert_message", ""),
                "patient_id":      patient_id,
                "reviewed_by":     user,
            }
            result = self._db["xray_predictions"].insert_one(doc)
            return str(result.inserted_id)
        except Exception as exc:
            print(f"[MongoDB] Error al guardar predicción: {exc}")
            return None

    def get_xray_predictions(self, limit: int = 50,
                              class_filter: str | None = None) -> list[dict]:
        """Recupera predicciones recientes de radiografías."""
        if not self._connected or self._db is None:
            return []
        try:
            query: dict = {}
            if class_filter:
                query["predicted_class"] = class_filter
            cursor = (self._db["xray_predictions"]
                      .find(query, {"_id": 0})
                      .sort("timestamp", -1)
                      .limit(limit))
            docs = list(cursor)
            # Serializar datetime a ISO string
            for doc in docs:
                if isinstance(doc.get("timestamp"), datetime):
                    doc["timestamp"] = doc["timestamp"].isoformat()
            return docs
        except Exception as exc:
            print(f"[MongoDB] Error al consultar predicciones: {exc}")
            return []

    def get_xray_stats(self) -> dict[str, Any]:
        """Estadísticas agregadas de predicciones almacenadas."""
        if not self._connected or self._db is None:
            return {"available": False}
        try:
            col = self._db["xray_predictions"]
            total = col.count_documents({})

            pipeline = [
                {"$group": {
                    "_id": "$predicted_class",
                    "count": {"$sum": 1},
                    "avg_confidence": {"$avg": "$confidence"},
                }},
                {"$sort": {"count": -1}},
            ]
            by_class = list(col.aggregate(pipeline))
            alerts = col.count_documents({"clinical_alert": True})

            return {
                "available":   True,
                "total":       total,
                "alerts":      alerts,
                "by_class":    [
                    {
                        "class":          d["_id"],
                        "count":          d["count"],
                        "avg_confidence": round(d["avg_confidence"], 4),
                    }
                    for d in by_class
                ],
            }
        except Exception as exc:
            print(f"[MongoDB] Error en stats: {exc}")
            return {"available": False, "error": str(exc)}

    # ── Métricas de entrenamiento CNN ─────────────────────────────────────────

    def save_cnn_training_metrics(self, metrics: dict[str, Any]) -> str | None:
        """Persiste métricas de entrenamiento del modelo CNN."""
        if not self._connected or self._db is None:
            return None
        try:
            doc = {"trained_at": datetime.now(tz=timezone.utc), **metrics}
            result = self._db["cnn_training_logs"].insert_one(doc)
            return str(result.inserted_id)
        except Exception as exc:
            print(f"[MongoDB] Error al guardar métricas CNN: {exc}")
            return None

    def get_latest_cnn_metrics(self) -> dict[str, Any] | None:
        """Recupera las métricas del último entrenamiento CNN."""
        if not self._connected or self._db is None:
            return None
        try:
            doc = (self._db["cnn_training_logs"]
                   .find_one({}, {"_id": 0}, sort=[("trained_at", -1)]))
            if doc and isinstance(doc.get("trained_at"), datetime):
                doc["trained_at"] = doc["trained_at"].isoformat()
            return doc
        except Exception:
            return None


# Instancia singleton
mongo = MongoClient()
