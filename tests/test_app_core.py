from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
import psycopg2

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "back-end"


@pytest.fixture()
def app_module(monkeypatch):
    if not os.environ.get("DATABASE_URL"):
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql://hospital:hospital@127.0.0.1:5432/hospital",
        )
    sys.path.insert(0, str(BACKEND_DIR))
    try:
        module = importlib.import_module("app")
    except psycopg2.OperationalError:
        sys.modules.pop("app", None)
        sys.modules.pop("database", None)
        pytest.skip("PostgreSQL is not reachable; start it with: docker compose up -d db")

    module.db._sessions.clear()
    module.db.init_db()
    module.app.config.update(TESTING=True)
    return module


@pytest.fixture()
def client(app_module):
    return app_module.app.test_client()


@pytest.fixture()
def admin_headers(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "1234"},
    )
    assert response.status_code == 200
    token = response.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_report_requires_auth(client):
    response = client.get("/api/report/view")
    assert response.status_code == 401


def test_report_accepts_access_token_query(client, app_module, admin_headers, monkeypatch):
    token = admin_headers["Authorization"].replace("Bearer ", "")
    monkeypatch.setattr(app_module.predictor, "get_model_info", lambda: {"loaded": False})
    monkeypatch.setattr(
        app_module.db,
        "patients_eda",
        lambda: {"total_patients": 0, "age_stats": {}, "top_diagnoses": [], "zone_distribution": []},
    )

    response = client.get(f"/api/report/view?access_token={token}")

    assert response.status_code == 200
    assert b"MedAI Hospital" in response.data


def test_create_disease_uses_authenticated_session(client, app_module, admin_headers, monkeypatch):
    captured = {}

    def fake_upsert(name, symptoms, created_by=""):
        captured["created_by"] = created_by
        return {"id": 1, "name": name, "common_symptoms": symptoms}

    monkeypatch.setattr(app_module.db, "upsert_manual_disease", fake_upsert)

    response = client.post(
        "/api/diseases",
        headers=admin_headers,
        json={"name": "Migraine", "symptoms": ["headache", "nausea"]},
    )

    assert response.status_code == 200
    assert captured["created_by"] == "admin"


def test_resolve_training_dataset_accepts_dataset_alias(app_module, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploaded_datasets"
    upload_dir.mkdir()
    dataset = upload_dir / "sample.csv"
    dataset.write_text("Age,Gender,Symptoms,Diagnosis\n40,Male,cough,Asthma\n", encoding="utf-8")

    monkeypatch.setattr(app_module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(app_module, "DATASET_PATH", tmp_path / "healthcare_dataset_100k.csv")

    resolved = app_module._resolve_training_dataset({"dataset": str(dataset)})

    assert resolved == dataset.resolve()


def test_import_patients_response_includes_imported_alias(client, app_module, admin_headers, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploaded_datasets"
    upload_dir.mkdir()
    dataset = upload_dir / "sample.csv"
    dataset.write_text("Age,Gender,Symptoms,Diagnosis\n40,Male,cough,Asthma\n", encoding="utf-8")

    monkeypatch.setattr(app_module, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(app_module, "DATASET_PATH", tmp_path / "healthcare_dataset_100k.csv")
    monkeypatch.setattr(app_module.predictor, "loaded", True)
    monkeypatch.setattr(
        app_module.db,
        "import_patients_from_dataset",
        lambda **kwargs: {"dataset": "sample.csv", "rows_processed": 1, "inserted": 1, "skipped": 0},
    )

    response = client.post(
        "/api/patients/import-dataset",
        headers=admin_headers,
        json={"dataset": str(dataset), "max_rows": 1},
    )

    assert response.status_code == 200
    assert response.get_json()["inserted"] == 1
    assert response.get_json()["imported"] == 1

