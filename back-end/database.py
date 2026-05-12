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

            CREATE TABLE IF NOT EXISTS diseases (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    UNIQUE NOT NULL,
                created_by    TEXT    DEFAULT '',
                created_at    TEXT    DEFAULT (datetime('now')),
                updated_at    TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS symptoms (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    UNIQUE NOT NULL,
                normalized    TEXT    UNIQUE NOT NULL,
                created_at    TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS disease_symptoms (
                disease_id    INTEGER NOT NULL,
                symptom_id    INTEGER NOT NULL,
                PRIMARY KEY (disease_id, symptom_id),
                FOREIGN KEY (disease_id) REFERENCES diseases(id) ON DELETE CASCADE,
                FOREIGN KEY (symptom_id) REFERENCES symptoms(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS doctors (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                specialty     TEXT    NOT NULL,
                zone          TEXT    NOT NULL,
                email         TEXT    DEFAULT '',
                phone         TEXT    DEFAULT '',
                shift         TEXT    DEFAULT '',
                notes         TEXT    DEFAULT '',
                is_active     INTEGER DEFAULT 1,
                created_at    TEXT    DEFAULT (datetime('now')),
                updated_at    TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                level        TEXT    NOT NULL DEFAULT 'info',
                source       TEXT    NOT NULL DEFAULT 'system',
                title        TEXT    NOT NULL,
                message      TEXT    DEFAULT '',
                meta         TEXT    DEFAULT '',
                is_read      INTEGER DEFAULT 0,
                created_at   TEXT    DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_created
                ON notifications(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_notifications_unread
                ON notifications(is_read, created_at DESC);
        """)
        # Seed default admin
        if not conn.execute("SELECT id FROM users WHERE username='admin'").fetchone():
            conn.execute(
                "INSERT INTO users (username,name,email,password_hash,role) VALUES (?,?,?,?,?)",
                ("admin", "Administrador", "admin@hospital.com", hash_password("1234"), "admin"),
            )
        _seed_default_doctors(conn)
        conn.commit()


# ── Doctores por defecto (cubriendo las 10 enfermedades del dataset original
#    + las 10 enfermedades del dataset extendido) ─────────────────────────────

DEFAULT_DOCTOR_ROSTER: list[tuple[str, str, str, str, str, str]] = [
    # name, specialty, zone, email, phone, shift
    ("Dr. Andres Morales",     "Cardiologia",       "Cardiologia",       "andres.morales@hospital.com",   "+34 600 100 100", "Manana"),
    ("Dra. Laura Castillo",    "Cardiologia",       "Cardiologia",       "laura.castillo@hospital.com",   "+34 600 100 101", "Tarde"),
    ("Dr. Javier Rojas",       "Neurologia",        "Neurologia",        "javier.rojas@hospital.com",     "+34 600 100 102", "Noche"),
    ("Dra. Sofia Ibanez",      "Neumologia",        "Neumologia",        "sofia.ibanez@hospital.com",     "+34 600 100 103", "Manana"),
    ("Dr. Miguel Torres",      "Infectologia",      "Infectologia",      "miguel.torres@hospital.com",    "+34 600 100 104", "Tarde"),
    ("Dra. Daniela Paredes",   "Endocrinologia",    "Endocrinologia",    "daniela.paredes@hospital.com",  "+34 600 100 105", "Manana"),
    ("Dr. Ricardo Mendez",     "Nefrologia",        "Nefrologia",        "ricardo.mendez@hospital.com",   "+34 600 100 106", "Tarde"),
    ("Dra. Paula Jimenez",     "Hepatologia",       "Hepatologia",       "paula.jimenez@hospital.com",    "+34 600 100 107", "Manana"),
    ("Dr. Sebastian Vega",     "Oncologia",         "Oncologia",         "sebastian.vega@hospital.com",   "+34 600 100 108", "Tarde"),
    ("Dra. Valeria Nunez",     "Salud Mental",      "Salud Mental",      "valeria.nunez@hospital.com",    "+34 600 100 109", "Manana"),
    ("Dr. Hector Salazar",     "Neumologia",        "Neumologia",        "hector.salazar@hospital.com",   "+34 600 100 110", "Noche"),
    ("Dra. Carolina Lopez",    "Reumatologia",      "Reumatologia",      "carolina.lopez@hospital.com",   "+34 600 100 111", "Manana"),
    ("Dr. Alberto Ramos",      "Traumatologia",     "Traumatologia",     "alberto.ramos@hospital.com",    "+34 600 100 112", "Tarde"),
    ("Dra. Marta Solis",       "Dermatologia",      "Dermatologia",      "marta.solis@hospital.com",      "+34 600 100 113", "Manana"),
    ("Dr. Joaquin Pereira",    "Gastroenterologia", "Gastroenterologia", "joaquin.pereira@hospital.com",  "+34 600 100 114", "Tarde"),
    ("Dra. Elena Cabrera",     "Hematologia",       "Hematologia",       "elena.cabrera@hospital.com",    "+34 600 100 115", "Manana"),
    ("Dra. Beatriz Ortega",    "Salud Mental",      "Salud Mental",      "beatriz.ortega@hospital.com",   "+34 600 100 116", "Tarde"),
    ("Dr. Julio Fernandez",    "Neurologia",        "Neurologia",        "julio.fernandez@hospital.com",  "+34 600 100 117", "Manana"),
]


def _seed_default_doctors(conn: sqlite3.Connection) -> None:
    """Asegura que existan los doctores base sin duplicar entradas previas."""
    existing = {
        (row["name"].strip().lower(), row["specialty"].strip().lower())
        for row in conn.execute("SELECT name, specialty FROM doctors").fetchall()
    }
    pending = [
        (name, specialty, zone, email, phone, shift, "")
        for (name, specialty, zone, email, phone, shift) in DEFAULT_DOCTOR_ROSTER
        if (name.lower(), specialty.lower()) not in existing
    ]
    if not pending:
        return
    conn.executemany(
        """
        INSERT INTO doctors (name, specialty, zone, email, phone, shift, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        pending,
    )


def ensure_default_doctors() -> int:
    """Re-aplica el seed de doctores; devuelve cuantos se insertaron."""
    with get_connection() as conn:
        before = conn.execute("SELECT COUNT(*) AS c FROM doctors").fetchone()["c"]
        _seed_default_doctors(conn)
        conn.commit()
        after = conn.execute("SELECT COUNT(*) AS c FROM doctors").fetchone()["c"]
        return max(0, after - before)


def find_doctor_by_zone(zone: str) -> Optional[dict]:
    """Busca un doctor activo cuya zona coincide (case-insensitive)."""
    z = (zone or "").strip().lower()
    if not z:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM doctors
            WHERE is_active = 1 AND lower(zone) = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (z,),
        ).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Notifications (eventos del sistema visibles en la campana)
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_NOTIF_LEVELS = {"info", "success", "warning", "error"}


def add_notification(
    title: str,
    message: str = "",
    level: str = "info",
    source: str = "system",
    meta: str = "",
) -> dict:
    if level not in ALLOWED_NOTIF_LEVELS:
        level = "info"
    title = (title or "").strip()[:240] or "Notificacion"
    message = (message or "").strip()[:4000]
    source = (source or "system").strip()[:80] or "system"
    meta = (meta or "").strip()[:2000]
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO notifications (level, source, title, message, meta)
            VALUES (?, ?, ?, ?, ?)
            """,
            (level, source, title, message, meta),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM notifications ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else {}


def list_notifications(limit: int = 30, only_unread: bool = False) -> list[dict]:
    limit = max(1, min(int(limit or 30), 200))
    with get_connection() as conn:
        if only_unread:
            rows = conn.execute(
                """
                SELECT * FROM notifications
                WHERE is_read = 0
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM notifications
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def count_unread_notifications() -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE is_read = 0"
        ).fetchone()
        return int(row["c"]) if row else 0


def mark_notifications_read(ids: list[int] | None = None) -> int:
    """Si ids es None, marca todas como leidas. Devuelve filas afectadas."""
    with get_connection() as conn:
        if not ids:
            cur = conn.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0")
        else:
            placeholders = ",".join("?" for _ in ids)
            cur = conn.execute(
                f"UPDATE notifications SET is_read = 1 WHERE id IN ({placeholders})",
                tuple(int(x) for x in ids),
            )
        conn.commit()
        return cur.rowcount or 0


def clear_notifications() -> int:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM notifications")
        conn.commit()
        return cur.rowcount or 0


def _normalize_term(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _ensure_symptom(conn: sqlite3.Connection, symptom_name: str) -> int | None:
    normalized = _normalize_term(symptom_name)
    if not normalized:
        return None
    row = conn.execute("SELECT id FROM symptoms WHERE normalized=?", (normalized,)).fetchone()
    if row:
        return int(row["id"])
    display_name = " ".join((symptom_name or "").strip().split())
    conn.execute(
        "INSERT INTO symptoms (name, normalized) VALUES (?, ?)",
        (display_name, normalized),
    )
    row = conn.execute("SELECT id FROM symptoms WHERE normalized=?", (normalized,)).fetchone()
    return int(row["id"]) if row else None


def list_symptoms() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT name FROM symptoms ORDER BY name COLLATE NOCASE").fetchall()
        return [r["name"] for r in rows]


def list_manual_diseases() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.name, d.created_by, d.created_at, d.updated_at,
                   COUNT(ds.symptom_id) AS symptoms_count
            FROM diseases d
            LEFT JOIN disease_symptoms ds ON ds.disease_id = d.id
            GROUP BY d.id
            ORDER BY d.name COLLATE NOCASE
            """
        ).fetchall()
        result = []
        for row in rows:
            symptoms = conn.execute(
                """
                SELECT s.name
                FROM symptoms s
                JOIN disease_symptoms ds ON ds.symptom_id = s.id
                WHERE ds.disease_id = ?
                ORDER BY s.name COLLATE NOCASE
                """,
                (row["id"],),
            ).fetchall()
            result.append({
                "id": row["id"],
                "name": row["name"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "common_symptoms": [s["name"] for s in symptoms],
                "count": 0,
                "avg_age": 0,
            })
        return result


def upsert_manual_disease(name: str, symptoms: list[str], created_by: str = "") -> dict:
    clean_name = " ".join((name or "").strip().split())
    if not clean_name:
        raise ValueError("Nombre de enfermedad requerido.")
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM diseases WHERE lower(name)=lower(?)", (clean_name,)).fetchone()
        if row:
            disease_id = int(row["id"])
            conn.execute(
                "UPDATE diseases SET name=?, updated_at=datetime('now') WHERE id=?",
                (clean_name, disease_id),
            )
            conn.execute("DELETE FROM disease_symptoms WHERE disease_id=?", (disease_id,))
        else:
            conn.execute(
                "INSERT INTO diseases (name, created_by) VALUES (?, ?)",
                (clean_name, created_by),
            )
            disease_id = int(conn.execute("SELECT id FROM diseases WHERE lower(name)=lower(?)", (clean_name,)).fetchone()["id"])

        seen: set[int] = set()
        for symptom in symptoms or []:
            symptom_id = _ensure_symptom(conn, symptom)
            if symptom_id and symptom_id not in seen:
                seen.add(symptom_id)
                conn.execute(
                    "INSERT OR IGNORE INTO disease_symptoms (disease_id, symptom_id) VALUES (?, ?)",
                    (disease_id, symptom_id),
                )
        conn.commit()

        out = conn.execute(
            "SELECT id, name, created_by, created_at, updated_at FROM diseases WHERE id=?",
            (disease_id,),
        ).fetchone()
        syms = conn.execute(
            """
            SELECT s.name
            FROM symptoms s
            JOIN disease_symptoms ds ON ds.symptom_id = s.id
            WHERE ds.disease_id = ?
            ORDER BY s.name COLLATE NOCASE
            """,
            (disease_id,),
        ).fetchall()
        return {
            "id": out["id"],
            "name": out["name"],
            "created_by": out["created_by"],
            "created_at": out["created_at"],
            "updated_at": out["updated_at"],
            "common_symptoms": [s["name"] for s in syms],
            "count": 0,
            "avg_age": 0,
        }


def list_doctors() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, specialty, zone, email, phone, shift, notes, is_active, created_at, updated_at
            FROM doctors
            WHERE is_active = 1
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
        return [dict(r) for r in rows]


def create_doctor(name: str, specialty: str, zone: str, email: str = "", phone: str = "", shift: str = "", notes: str = "") -> dict:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO doctors (name, specialty, zone, email, phone, shift, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (name or "").strip(),
                (specialty or "").strip(),
                (zone or "").strip(),
                (email or "").strip(),
                (phone or "").strip(),
                (shift or "").strip(),
                (notes or "").strip(),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM doctors ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else {}


def update_doctor(doctor_id: int, name: str, specialty: str, zone: str, email: str = "", phone: str = "", shift: str = "", notes: str = "") -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE doctors
            SET name=?, specialty=?, zone=?, email=?, phone=?, shift=?, notes=?, updated_at=datetime('now')
            WHERE id=? AND is_active=1
            """,
            (
                (name or "").strip(),
                (specialty or "").strip(),
                (zone or "").strip(),
                (email or "").strip(),
                (phone or "").strip(),
                (shift or "").strip(),
                (notes or "").strip(),
                doctor_id,
            ),
        )
        conn.commit()
        return cur.rowcount > 0


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
