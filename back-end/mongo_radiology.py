"""
Radiografías — almacenamiento no estructurado en MongoDB (GridFS).
Dos bases de datos separadas según categoría:
  - radiología general  → MONGO_DB_RADIOLOGY (por defecto medai_radiology)
  - radiología dental    → MONGO_DB_DENTAL   (por defecto medai_dental)
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gridfs import GridFSBucket
from pymongo import DESCENDING, MongoClient

ALLOWED_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".dcm", ".dic"}
)


def mongo_uri() -> str:
    u = os.environ.get("MONGO_URI", "").strip()
    if u:
        return u
    return "mongodb://127.0.0.1:27017/"


def database_name_general() -> str:
    return os.environ.get("MONGO_DB_RADIOLOGY", "medai_radiology")


def database_name_dental() -> str:
    return os.environ.get("MONGO_DB_DENTAL", "medai_dental")


_client: MongoClient | None = None


def mongo_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(mongo_uri(), serverSelectionTimeoutMS=5000)
    return _client


def get_bucket(category: str) -> tuple[Any, GridFSBucket]:
    """
    category: "general" | "dental"
    """
    client = mongo_client()
    name = database_name_dental() if category == "dental" else database_name_general()
    db = client[name]
    return db, GridFSBucket(db)


def leaf_filename(raw: str) -> str:
    if not raw or not raw.strip():
        return ""
    cleaned = Path(str(raw).replace("\\", "/")).name
    return cleaned[:240] if cleaned else ""


def validate_extension(filename: str) -> bool:
    leaf = leaf_filename(filename)
    if not leaf:
        return False
    suf = Path(leaf).suffix.lower()
    return suf in ALLOWED_EXTENSIONS


def store_upload(
    category: str,
    *,
    stream,
    filename: str,
    content_type: str,
    uploaded_by: str,
    folder_hint: str = "",
    notes: str = "",
) -> dict[str, Any]:
    if category not in ("general", "dental"):
        raise ValueError("Categoria invalida.")

    leaf = leaf_filename(filename) or "radiografia.bin"
    if not validate_extension(leaf):
        raise ValueError(f"Extension no permitida: {leaf}")

    store_key = f"{uuid.uuid4().hex}_{leaf}"
    meta: dict[str, Any] = {
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "original_filename": leaf,
        "content_type": (content_type or "application/octet-stream")[:190],
        "category": category,
    }
    if folder_hint:
        meta["source_folder_hint"] = folder_hint[:500]
    if notes.strip():
        meta["notes"] = notes.strip()[:2000]

    db, bucket = get_bucket(category)
    client = mongo_client()
    client.admin.command("ping")
    fid = bucket.upload_from_stream(store_key, stream, metadata=meta)
    return {"id": str(fid), "stored_as": store_key, "filename": leaf}


def list_recent(category: str, limit: int = 40) -> list[dict[str, Any]]:
    if category not in ("general", "dental"):
        raise ValueError("Categoria invalida.")
    db, _ = get_bucket(category)
    limit = max(1, min(int(limit), 100))
    col = db["fs.files"]
    out: list[dict[str, Any]] = []
    for doc in col.find().sort("uploadDate", DESCENDING).limit(limit):
        meta = dict(doc.get("metadata") or {})
        out.append({
            "id": str(doc["_id"]),
            "filename": meta.get("original_filename") or doc.get("filename"),
            "length": doc.get("length"),
            "upload_date": doc["uploadDate"].isoformat()
            if doc.get("uploadDate")
            else None,
            "content_type": meta.get("content_type"),
            "uploaded_by": meta.get("uploaded_by"),
            "stored_as": doc.get("filename"),
            "notes": meta.get("notes") or "",
        })
    return out
