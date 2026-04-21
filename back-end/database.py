"""
Hospital AI — SQLite database layer
====================================
Manages users and in-memory sessions.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "hospital.db"

# ── In-memory sessions (token → session dict) ────────────────────────────────
_sessions: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Connection
# ─────────────────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Init
# ─────────────────────────────────────────────────────────────────────────────

def init_db() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                username     TEXT    UNIQUE NOT NULL,
                name         TEXT    NOT NULL,
                email        TEXT    DEFAULT '',
                password_hash TEXT   NOT NULL,
                role         TEXT    DEFAULT 'user',
                created_at   TEXT    DEFAULT (datetime('now')),
                is_active    INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS patients (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_name          TEXT    NOT NULL,
                age                   INTEGER NOT NULL,
                gender                TEXT    NOT NULL,
                symptoms              TEXT    NOT NULL,
                symptoms_translated   TEXT    DEFAULT '',
                diagnosis             TEXT    NOT NULL,
                diagnosis_confidence  REAL    DEFAULT 0,
                risk_level            TEXT    DEFAULT '',
                risk_confidence       REAL    DEFAULT 0,
                hospital_zone         TEXT    NOT NULL,
                specialist_doctor     TEXT    NOT NULL,
                source_dataset        TEXT    DEFAULT '',
                created_by            TEXT    DEFAULT '',
                created_at            TEXT    DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_patients_diagnosis ON patients(diagnosis);
            CREATE INDEX IF NOT EXISTS idx_patients_zone ON patients(hospital_zone);
            CREATE INDEX IF NOT EXISTS idx_patients_created_at ON patients(created_at DESC);
        """)
        # Seed default admin
        if not conn.execute("SELECT id FROM users WHERE username='admin'").fetchone():
            conn.execute(
                "INSERT INTO users (username,name,email,password_hash,role) VALUES (?,?,?,?,?)",
                ("admin", "Administrador", "admin@hospital.com", hash_password("1234"), "admin"),
            )
        conn.commit()


def create_patient(
    patient_name: str,
    age: int,
    gender: str,
    symptoms: str,
    symptoms_translated: str,
    diagnosis: str,
    diagnosis_confidence: float,
    risk_level: str,
    risk_confidence: float,
    hospital_zone: str,
    specialist_doctor: str,
    source_dataset: str = "",
    created_by: str = "",
) -> dict:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO patients (
                patient_name, age, gender, symptoms, symptoms_translated,
                diagnosis, diagnosis_confidence, risk_level, risk_confidence,
                hospital_zone, specialist_doctor, source_dataset, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_name,
                age,
                gender,
                symptoms,
                symptoms_translated,
                diagnosis,
                diagnosis_confidence,
                risk_level,
                risk_confidence,
                hospital_zone,
                specialist_doctor,
                source_dataset,
                created_by,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM patients ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row)


def list_patients(limit: int = 200) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM patients
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def search_patients_by_name(query: str, limit: int = 25) -> list[dict]:
    """Busqueda incremental (tipo autocomplete) por nombre o ID."""
    q = (query or "").strip()
    if not q:
        return []
    with get_connection() as conn:
        if q.isdigit():
            rows = conn.execute(
                """
                SELECT id, patient_name, age, gender, diagnosis, risk_level,
                       hospital_zone, specialist_doctor, created_at
                FROM patients
                WHERE patient_name LIKE ? OR id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (f"%{q}%", int(q), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, patient_name, age, gender, diagnosis, risk_level,
                       hospital_zone, specialist_doctor, created_at
                FROM patients
                WHERE patient_name LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (f"%{q}%", limit),
            ).fetchall()
        return [dict(r) for r in rows]


def get_patient_by_id(patient_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        return dict(row) if row else None


def patients_eda() -> dict:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM patients").fetchone()["c"]
        by_diagnosis = [
            dict(r) for r in conn.execute(
                """
                SELECT diagnosis AS name, COUNT(*) AS count
                FROM patients
                GROUP BY diagnosis
                ORDER BY count DESC
                LIMIT 10
                """
            ).fetchall()
        ]
        by_zone = [
            dict(r) for r in conn.execute(
                """
                SELECT hospital_zone AS name, COUNT(*) AS count
                FROM patients
                GROUP BY hospital_zone
                ORDER BY count DESC
                """
            ).fetchall()
        ]
        by_risk = [
            dict(r) for r in conn.execute(
                """
                SELECT risk_level AS name, COUNT(*) AS count
                FROM patients
                GROUP BY risk_level
                ORDER BY count DESC
                """
            ).fetchall()
        ]
        age_row = conn.execute(
            "SELECT ROUND(AVG(age), 1) AS avg_age, MIN(age) AS min_age, MAX(age) AS max_age FROM patients"
        ).fetchone()
        return {
            "total_patients": total,
            "top_diagnoses": by_diagnosis,
            "zone_distribution": by_zone,
            "risk_distribution": by_risk,
            "age_stats": dict(age_row) if age_row else {"avg_age": None, "min_age": None, "max_age": None},
        }


def import_patients_from_dataset(
    dataset_path: Path,
    classifier,
    username: str,
    assigner,
    max_rows: int | None = None,
) -> dict:
    inserted = 0
    skipped = 0
    rows_processed = 0
    dataset_name = dataset_path.name
    with dataset_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            if max_rows is not None and i > max_rows:
                break
            rows_processed += 1
            try:
                age = int(row.get("Age", "0"))
                gender = (row.get("Gender", "") or "Other").strip() or "Other"
                symptoms = (row.get("Symptoms", "") or "").strip()
                diagnosis = (row.get("Diagnosis", "") or "").strip()
                if not symptoms or not diagnosis:
                    skipped += 1
                    continue
                risk = classifier.classify_risk(age, gender, symptoms)
                assignment = assigner(diagnosis)
                create_patient(
                    patient_name=f"Paciente DS-{i}",
                    age=age,
                    gender=gender,
                    symptoms=symptoms,
                    symptoms_translated=symptoms,
                    diagnosis=diagnosis,
                    diagnosis_confidence=1.0,
                    risk_level=risk.get("risk_level", ""),
                    risk_confidence=float(risk.get("confidence", 0)),
                    hospital_zone=assignment["zone"],
                    specialist_doctor=assignment["doctor"],
                    source_dataset=dataset_name,
                    created_by=username,
                )
                inserted += 1
            except Exception:
                skipped += 1
    return {
        "dataset": dataset_name,
        "rows_processed": rows_processed,
        "inserted": inserted,
        "skipped": skipped,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Password hashing
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    return hash_password(password) == stored_hash


# ─────────────────────────────────────────────────────────────────────────────
# User CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_user_by_username(username: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_all_users() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id,username,name,email,role,created_at,is_active FROM users ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def create_user(username: str, name: str, email: str, password: str, role: str = "user") -> dict:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (username,name,email,password_hash,role) VALUES (?,?,?,?,?)",
            (username, name, email, hash_password(password), role),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id,username,name,email,role,created_at FROM users WHERE username=?",
            (username,),
        ).fetchone()
        return dict(row)


def deactivate_user(user_id: int) -> bool:
    """Soft-delete: sets is_active=0. Admin cannot be deactivated."""
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE users SET is_active=0 WHERE id=? AND username!='admin'", (user_id,)
        )
        conn.commit()
        return cur.rowcount > 0


def update_password(user_id: int, new_password: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (hash_password(new_password), user_id),
        )
        conn.commit()
        return cur.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# Session management
# ─────────────────────────────────────────────────────────────────────────────

def create_session(user_id: int, username: str, role: str) -> str:
    token = str(uuid.uuid4())
    _sessions[token] = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "expires": datetime.now() + timedelta(hours=8),
    }
    return token


def get_session(token: str) -> Optional[dict]:
    session = _sessions.get(token)
    if session and session["expires"] > datetime.now():
        return session
    _sessions.pop(token, None)
    return None


def delete_session(token: str) -> None:
    _sessions.pop(token, None)
