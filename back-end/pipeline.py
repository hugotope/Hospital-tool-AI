"""
Hospital AI — ETL Pipeline
==========================
Procesa datasets nuevos en 4 etapas tipo Big Data:

    Ingesta ─▶ Limpieza ─▶ Transformacion ─▶ Analisis

Cada etapa produce metadatos estructurados para el frontend.
Si una etapa falla (``ok: false``), el pipeline se detiene.
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from logging_config import get_logger

log = get_logger("pipeline")

REQUIRED_COLUMNS = {"Age", "Gender", "Symptoms", "Diagnosis"}
OPTIONAL_COLUMNS = {"Risk_Level", "Patient_ID", "Name", "Patient_Name", "DaysStayed", "Days_Stayed"}
AGE_MIN, AGE_MAX = 0, 120


def _timed(fn: Callable[..., dict]) -> Callable[..., dict]:
    """Decorator: measure stage runtime and attach ``elapsed_ms``."""

    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        result["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        return result

    return wrapper


def _normalize_symptoms(series: pd.Series) -> tuple[pd.Series, dict[str, int]]:
    """Minúsculas, trim, espacios colapsados y comas normalizadas."""
    before_nonempty = int(series.astype(str).str.strip().ne("").sum())
    s = series.astype(str).str.lower().str.strip()
    s = s.str.replace(r"\s+", " ", regex=True)
    s = s.str.replace(r",\s*", ", ", regex=True)
    s = s.str.strip(" ,")
    after_nonempty = int(s.ne("").sum())
    return s, {
        "rows_with_symptoms": after_nonempty,
        "empty_after_normalize": int((s == "").sum()),
        "normalized_rows": before_nonempty,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: INGESTA
# ─────────────────────────────────────────────────────────────────────────────

@_timed
def ingest(path: Path) -> dict:
    """Lee el CSV y reporta tamaño, columnas y validez estructural."""
    stage = {
        "stage": "ingest",
        "ok": False,
        "file": str(path),
        "rows_raw": 0,
        "columns": [],
        "size_kb": 0,
        "required_ok": False,
        "missing_required": [],
        "warnings": [],
        "quality_checks": {},
    }
    if not path.exists():
        stage["error"] = f"Archivo no encontrado: {path}"
        log.error("Ingesta fallida: %s", stage["error"])
        return stage

    stage["size_kb"] = round(path.stat().st_size / 1024, 1)
    try:
        df = pd.read_csv(path, encoding="utf-8", on_bad_lines="skip", low_memory=False)
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip", low_memory=False)
    except Exception as exc:
        stage["error"] = f"Error leyendo CSV: {exc}"
        log.error("Ingesta fallida leyendo %s: %s", path.name, exc)
        return stage

    stage["rows_raw"] = int(len(df))
    stage["columns"] = list(df.columns)
    missing = REQUIRED_COLUMNS - set(df.columns)
    stage["missing_required"] = sorted(missing)
    stage["required_ok"] = not missing
    stage["quality_checks"] = {
        "required_columns_present": stage["required_ok"],
        "column_count": len(df.columns),
        "empty_file": df.empty,
    }
    if missing:
        stage["warnings"].append(f"Faltan columnas obligatorias: {', '.join(sorted(missing))}")
    if df.empty:
        stage["warnings"].append("Dataset vacio.")
    stage["ok"] = stage["required_ok"] and not df.empty
    stage["_df"] = df
    log.info(
        "Ingesta %s | ok=%s | filas=%s | columnas=%s | elapsed pendiente",
        path.name,
        stage["ok"],
        stage["rows_raw"],
        len(stage["columns"]),
    )
    return stage


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: LIMPIEZA
# ─────────────────────────────────────────────────────────────────────────────

@_timed
def clean(df: pd.DataFrame) -> dict:
    """Elimina duplicados, NAs, outliers de edad y normaliza textos."""
    stage = {"stage": "clean", "ok": False, "rows_before": int(len(df))}
    df = df.copy()

    dup = int(df.duplicated().sum())
    df = df.drop_duplicates()

    na_critical = int(df[["Age", "Gender", "Symptoms", "Diagnosis"]].isna().any(axis=1).sum())
    df = df.dropna(subset=["Age", "Gender", "Symptoms", "Diagnosis"])

    df["Age"] = pd.to_numeric(df["Age"], errors="coerce")
    bad_age = int(df["Age"].isna().sum())
    df = df.dropna(subset=["Age"])
    df["Age"] = df["Age"].astype(int)

    out_age = int(((df["Age"] < AGE_MIN) | (df["Age"] > AGE_MAX)).sum())
    df = df[(df["Age"] >= AGE_MIN) & (df["Age"] <= AGE_MAX)]

    for col in ("Gender", "Diagnosis"):
        df[col] = df[col].astype(str).str.strip()

    df["Symptoms"], sym_stats = _normalize_symptoms(df["Symptoms"])
    empty_symptoms = int((df["Symptoms"] == "").sum())
    df = df[df["Symptoms"] != ""]
    df = df[df["Diagnosis"] != ""]

    df["Gender"] = df["Gender"].str.title().replace({
        "M": "Male", "F": "Female", "Masculino": "Male", "Femenino": "Female", "Otro": "Other",
    })

    stage["rows_after"] = int(len(df))
    stage["removed"] = {
        "duplicates": dup,
        "missing_critical": na_critical,
        "invalid_age": bad_age,
        "age_outliers": out_age,
        "empty_symptoms": empty_symptoms,
        "empty_text": max(
            0,
            stage["rows_before"]
            - stage["rows_after"]
            - dup
            - na_critical
            - bad_age
            - out_age
            - empty_symptoms,
        ),
    }
    stage["symptoms_normalization"] = sym_stats
    stage["quality_checks"] = {
        "duplicates_removed": dup,
        "null_rows_removed": na_critical,
        "invalid_age_removed": bad_age,
        "age_out_of_range_removed": out_age,
        "symptoms_normalized": sym_stats.get("normalized_rows", 0),
    }
    stage["dropout_pct"] = round(
        (stage["rows_before"] - stage["rows_after"]) * 100 / max(1, stage["rows_before"]),
        2,
    )
    stage["ok"] = stage["rows_after"] > 0
    stage["_df"] = df
    log.info(
        "Limpieza | ok=%s | antes=%s despues=%s | dup=%s null=%s edad_fuera=%s",
        stage["ok"],
        stage["rows_before"],
        stage["rows_after"],
        dup,
        na_critical,
        out_age,
    )
    return stage


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3: TRANSFORMACION
# ─────────────────────────────────────────────────────────────────────────────

@_timed
def transform(df: pd.DataFrame, translator: Callable[[str], str] | None = None) -> dict:
    """Normaliza columnas, traduce sintomas y genera features derivadas."""
    stage = {"stage": "transform", "ok": False}
    df = df.copy()

    df["Gender_enc"] = df["Gender"].str.lower().map({"male": 0, "female": 1}).fillna(2).astype(int)

    def _age_bin(a: int) -> str:
        if a < 18:
            return "0-17"
        if a < 35:
            return "18-34"
        if a < 55:
            return "35-54"
        if a < 75:
            return "55-74"
        return "75+"

    df["Age_bin"] = df["Age"].apply(_age_bin)

    if translator is not None:
        df["Symptoms_en"] = df["Symptoms"].astype(str).map(translator)
    else:
        df["Symptoms_en"] = df["Symptoms"].astype(str)

    df["Symptoms_en"] = df["Symptoms_en"].str.lower().str.strip()
    df["Symptoms_en"] = df["Symptoms_en"].str.replace(r"\s+", " ", regex=True)
    df["Symptoms_count"] = df["Symptoms_en"].str.count(",") + 1

    features = ["Age", "Gender_enc", "Age_bin", "Symptoms_en", "Symptoms_count"]
    stage["features"] = features
    stage["rows_transformed"] = int(len(df))
    stage["sample"] = df.head(3).to_dict(orient="records") if len(df) else []
    stage["quality_checks"] = {
        "symptoms_translated": translator is not None,
        "avg_symptoms_per_row": round(float(df["Symptoms_count"].mean()), 2) if len(df) else 0,
    }
    stage["ok"] = stage["rows_transformed"] > 0
    stage["_df"] = df
    log.info("Transformacion | ok=%s | filas=%s", stage["ok"], stage["rows_transformed"])
    return stage


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4: ANALISIS (EDA)
# ─────────────────────────────────────────────────────────────────────────────

@_timed
def analyze(df: pd.DataFrame) -> dict:
    """EDA: distribucion de diagnosticos, edad, sintomas mas frecuentes."""
    stage = {"stage": "analyze", "ok": False}
    if df.empty:
        stage["error"] = "DataFrame vacio."
        log.warning("Analisis fallido: DataFrame vacio")
        return stage

    diag_counts = df["Diagnosis"].value_counts().head(15)
    gender_counts = df["Gender"].value_counts()
    age_bins = df["Age_bin"].value_counts() if "Age_bin" in df.columns else pd.Series(dtype=int)

    sym_series = df["Symptoms_en"].str.lower() if "Symptoms_en" in df.columns else df["Symptoms"].str.lower()
    sym_counter: Counter[str] = Counter()
    for row in sym_series.dropna():
        for s in row.split(","):
            s = s.strip()
            if s:
                sym_counter[s] += 1

    age_by_dx = (
        df.groupby("Diagnosis")["Age"]
        .agg(["mean", "min", "max", "count"])
        .round(1)
        .reset_index()
        .sort_values("count", ascending=False)
        .head(15)
    )

    stage["totals"] = {
        "rows": int(len(df)),
        "distinct_diagnoses": int(df["Diagnosis"].nunique()),
        "distinct_genders": int(df["Gender"].nunique()),
    }
    stage["age_stats"] = {
        "mean": round(float(df["Age"].mean()), 1),
        "median": int(df["Age"].median()),
        "min": int(df["Age"].min()),
        "max": int(df["Age"].max()),
        "std": round(float(df["Age"].std(ddof=0)), 1),
    }
    stage["diagnosis_distribution"] = [
        {"name": str(k), "count": int(v)} for k, v in diag_counts.items()
    ]
    stage["gender_distribution"] = [
        {"name": str(k), "count": int(v)} for k, v in gender_counts.items()
    ]
    stage["age_bins"] = [
        {"name": str(k), "count": int(v)}
        for k, v in age_bins.sort_index().items()
    ]
    stage["top_symptoms"] = [
        {"name": k, "count": v} for k, v in sym_counter.most_common(20)
    ]
    stage["age_by_diagnosis"] = [
        {
            "diagnosis": str(r["Diagnosis"]),
            "avg_age": float(r["mean"]),
            "min_age": int(r["min"]),
            "max_age": int(r["max"]),
            "n": int(r["count"]),
        }
        for _, r in age_by_dx.iterrows()
    ]
    stage["ok"] = True
    log.info(
        "Analisis | ok=%s | filas=%s | diagnosticos=%s",
        stage["ok"],
        stage["totals"]["rows"],
        stage["totals"]["distinct_diagnoses"],
    )
    return stage


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(path: Path, translator: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Corre las 4 etapas secuencialmente y devuelve un reporte estructurado."""
    log.info("Pipeline ETL iniciado | archivo=%s", path.name)
    stages: list[dict] = []

    s1 = ingest(path)
    s1_out = {k: v for k, v in s1.items() if k != "_df"}
    df = s1.pop("_df", None)
    stages.append(s1_out)
    if not s1.get("ok") or df is None:
        log.warning("Pipeline detenido en ingesta | ok=false")
        return {"ok": False, "stages": stages, "summary": {"rows_final": 0, "failed_stage": "ingest"}}

    s2 = clean(df)
    s2_out = {k: v for k, v in s2.items() if k != "_df"}
    df = s2.pop("_df", None)
    stages.append(s2_out)
    if not s2.get("ok") or df is None:
        log.warning("Pipeline detenido en limpieza | ok=false")
        return {"ok": False, "stages": stages, "summary": {"rows_final": 0, "failed_stage": "clean"}}

    s3 = transform(df, translator=translator)
    s3_out = {k: v for k, v in s3.items() if k != "_df"}
    df = s3.pop("_df", None)
    stages.append(s3_out)
    if not s3.get("ok") or df is None:
        log.warning("Pipeline detenido en transformacion | ok=false")
        return {"ok": False, "stages": stages, "summary": {"rows_final": 0, "failed_stage": "transform"}}

    s4 = analyze(df)
    stages.append(s4)
    if not s4.get("ok"):
        log.warning("Pipeline detenido en analisis | ok=false")
        return {"ok": False, "stages": stages, "summary": {"rows_final": s2.get("rows_after", 0), "failed_stage": "analyze"}}

    total_ms = sum(s.get("elapsed_ms", 0) for s in stages)
    report = {
        "ok": all(s.get("ok") for s in stages),
        "stages": stages,
        "summary": {
            "file": str(path),
            "rows_raw": s1.get("rows_raw", 0),
            "rows_final": s2.get("rows_after", 0),
            "distinct_diagnoses": s4.get("totals", {}).get("distinct_diagnoses", 0),
            "total_elapsed_ms": total_ms,
        },
    }
    log.info(
        "Pipeline ETL finalizado | ok=%s | filas_finales=%s | total_ms=%s",
        report["ok"],
        report["summary"]["rows_final"],
        total_ms,
    )
    return report
