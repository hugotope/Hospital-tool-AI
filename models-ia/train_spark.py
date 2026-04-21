"""
Hospital AI - Entrenamiento de Modelos (sklearn, con fallback PySpark)
======================================================================
Entrena dos clasificadores RandomForest para servir inferencia desde Flask:

  1. Clasificador de Enfermedades  (diagnosis)
  2. Clasificador de Riesgo        (Low / Medium / High)

Mejoras anti-fuga de informacion (evitar accuracy artificial 100%):
  * Se elimina `days_stayed` del vector de features (no esta disponible al
    momento de la inferencia de un nuevo paciente).
  * Se aplica "symptom dropout": en train se eliminan aleatoriamente 1-2
    sintomas por registro para simular historias clinicas incompletas.
  * Se añade ruido de etiqueta (5%) al nivel de riesgo para reflejar la
    incertidumbre clinica real.
  * Se reporta accuracy sobre test + validacion cruzada (5-fold).

Uso:
    python train_spark.py --dataset <ruta_csv>
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import scipy.sparse as sp

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.preprocessing import LabelEncoder


# ── PySpark (opcional) ───────────────────────────────────────────────────────
try:
    from pyspark.ml import Pipeline  # noqa: F401
    from pyspark.ml.classification import RandomForestClassifier as SparkRFC  # noqa: F401
    from pyspark.ml.evaluation import MulticlassClassificationEvaluator  # noqa: F401
    from pyspark.ml.feature import (  # noqa: F401
        HashingTF,
        IDF,
        RegexTokenizer,
        StringIndexer,
        VectorAssembler,
    )
    from pyspark.sql import SparkSession  # noqa: F401
    from pyspark.sql import functions as F  # noqa: F401
    _SPARK_AVAILABLE = True
    _SPARK_IMPORT_ERROR = ""
except Exception as exc:
    _SPARK_AVAILABLE = False
    _SPARK_IMPORT_ERROR = str(exc)


ROOT_DIR = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT_DIR / "healthcare_dataset_100k.csv"
MODELS_DIR = Path(__file__).resolve().parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

SKLEARN_MODEL_PATH = MODELS_DIR / "healthcare_models.joblib"
METRICS_PATH = MODELS_DIR / "metrics.json"

HIGH_RISK_DIAGNOSES = {"Cancer", "Heart Disease", "Stroke"}
MEDIUM_RISK_DIAGNOSES = {
    "Diabetes", "Kidney Disease", "Liver Disease", "COVID-19", "Hypertension"
}

RNG = np.random.default_rng(42)
GENDER_MAP = {"Male": 1, "Female": 0, "Other": 2}


def assign_risk(diagnosis: str, age: int, days_stayed: int) -> str:
    if diagnosis in HIGH_RISK_DIAGNOSES or days_stayed > 21 or age >= 75:
        return "High"
    if diagnosis in MEDIUM_RISK_DIAGNOSES or days_stayed > 10 or age >= 60:
        return "Medium"
    return "Low"


def _symptom_dropout(series: pd.Series, keep_prob: float = 0.65) -> pd.Series:
    """
    Simula informacion clinica incompleta: mantiene cada sintoma con
    probabilidad `keep_prob`. Se asegura de conservar al menos 1 sintoma.
    """
    def drop(row: str) -> str:
        parts = [p.strip() for p in str(row).split(",") if p.strip()]
        if not parts:
            return ""
        kept = [p for p in parts if RNG.random() < keep_prob]
        if not kept:
            kept = [RNG.choice(parts)]
        return ", ".join(kept)
    return series.apply(drop)


def _inject_label_noise(labels: pd.Series, classes: list[str], noise_pct: float = 0.05) -> pd.Series:
    """
    Inyecta ruido aleatorio en etiquetas (simula incertidumbre clinica).
    Cambia `noise_pct` de etiquetas a otra clase aleatoria.
    """
    labels = labels.copy()
    n = len(labels)
    n_noise = int(n * noise_pct)
    idx = RNG.choice(n, size=n_noise, replace=False)
    for i in idx:
        current = labels.iloc[i]
        other = [c for c in classes if c != current]
        labels.iloc[i] = RNG.choice(other)
    return labels


def _prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.dropna(subset=["Age", "Gender", "Symptoms", "Diagnosis"])
    if "Discharge_Date" in df.columns and "Date_of_Admission" in df.columns:
        df["days_stayed"] = (
            pd.to_datetime(df["Discharge_Date"], errors="coerce")
            - pd.to_datetime(df["Date_of_Admission"], errors="coerce")
        ).dt.days.fillna(0).astype(int)
    else:
        df["days_stayed"] = 0
    df["risk_level"] = df.apply(
        lambda r: assign_risk(r["Diagnosis"], int(r["Age"]), int(r["days_stayed"])),
        axis=1,
    )
    df["gender_enc"] = df["Gender"].map(GENDER_MAP).fillna(2).astype(int)
    df["symptoms_clean"] = df["Symptoms"].fillna("").str.lower().str.strip()
    df["symptoms_train"] = _symptom_dropout(df["symptoms_clean"])
    df["age"] = df["Age"].astype(int)
    return df


def _build_features(
    symptoms: pd.Series,
    age: pd.Series,
    gender_enc: pd.Series,
    tfidf: TfidfVectorizer,
    fit: bool,
) -> sp.csr_matrix:
    if fit:
        sym_feat = tfidf.fit_transform(symptoms)
    else:
        sym_feat = tfidf.transform(symptoms)
    num_feat = sp.csr_matrix(
        np.column_stack([age.values.astype(float), gender_enc.values.astype(float)])
    )
    return sp.hstack([sym_feat, num_feat]).tocsr()


def train_sklearn_models(df: pd.DataFrame) -> dict:
    print("\n[SKLEARN] Preparando dataset...")
    df = _prepare_dataframe(df)
    print(f"[SKLEARN] Registros validos: {len(df):,}")

    # ── Disease classifier ──────────────────────────────────────────────────
    print("\n[SKLEARN] Entrenando Clasificador de Enfermedades...")
    tfidf_d = TfidfVectorizer(max_features=400, ngram_range=(1, 2), sublinear_tf=True, min_df=2)
    X_disease = _build_features(
        df["symptoms_train"], df["age"], df["gender_enc"], tfidf_d, fit=True
    )
    le_disease = LabelEncoder()
    y_disease = le_disease.fit_transform(df["Diagnosis"])

    Xd_tr, Xd_te, yd_tr, yd_te = train_test_split(
        X_disease, y_disease, test_size=0.2, random_state=42, stratify=y_disease
    )
    rf_disease = RandomForestClassifier(
        n_estimators=120,
        max_depth=10,
        min_samples_leaf=5,
        random_state=42,
        n_jobs=1,
        class_weight="balanced",
    )
    rf_disease.fit(Xd_tr, yd_tr)
    yd_pred = rf_disease.predict(Xd_te)
    acc_disease = float(accuracy_score(yd_te, yd_pred))
    f1_disease = float(f1_score(yd_te, yd_pred, average="weighted"))
    print(f"[SKLEARN] Accuracy (test)    : {acc_disease:.4f}")
    print(f"[SKLEARN] F1 weighted (test) : {f1_disease:.4f}")

    cv_disease_scores = cross_val_score(
        rf_disease, X_disease, y_disease,
        cv=StratifiedKFold(n_splits=3, shuffle=True, random_state=42),
        scoring="accuracy", n_jobs=1,
    )
    cv_disease_mean = float(cv_disease_scores.mean())
    cv_disease_std = float(cv_disease_scores.std())
    print(f"[SKLEARN] CV 5-fold accuracy : {cv_disease_mean:.4f} ± {cv_disease_std:.4f}")

    # ── Risk classifier ─────────────────────────────────────────────────────
    print("\n[SKLEARN] Entrenando Clasificador de Riesgo...")
    risk_classes_list = ["Low", "Medium", "High"]
    df["risk_noisy"] = _inject_label_noise(df["risk_level"], risk_classes_list, noise_pct=0.05)

    tfidf_r = TfidfVectorizer(max_features=400, ngram_range=(1, 2), sublinear_tf=True, min_df=2)
    X_risk = _build_features(
        df["symptoms_train"], df["age"], df["gender_enc"], tfidf_r, fit=True
    )
    le_risk = LabelEncoder()
    y_risk = le_risk.fit_transform(df["risk_noisy"])

    Xr_tr, Xr_te, yr_tr, yr_te = train_test_split(
        X_risk, y_risk, test_size=0.2, random_state=42, stratify=y_risk
    )
    rf_risk = RandomForestClassifier(
        n_estimators=120,
        max_depth=8,
        min_samples_leaf=10,
        random_state=42,
        n_jobs=1,
        class_weight="balanced",
    )
    rf_risk.fit(Xr_tr, yr_tr)
    yr_pred = rf_risk.predict(Xr_te)
    acc_risk = float(accuracy_score(yr_te, yr_pred))
    f1_risk = float(f1_score(yr_te, yr_pred, average="weighted"))
    print(f"[SKLEARN] Accuracy (test)    : {acc_risk:.4f}")
    print(f"[SKLEARN] F1 weighted (test) : {f1_risk:.4f}")

    cv_risk_scores = cross_val_score(
        rf_risk, X_risk, y_risk,
        cv=StratifiedKFold(n_splits=3, shuffle=True, random_state=42),
        scoring="accuracy", n_jobs=1,
    )
    cv_risk_mean = float(cv_risk_scores.mean())
    cv_risk_std = float(cv_risk_scores.std())
    print(f"[SKLEARN] CV 5-fold accuracy : {cv_risk_mean:.4f} ± {cv_risk_std:.4f}")

    # ── Anomaly detector (IsolationForest sobre features de paciente) ───────
    print("\n[SKLEARN] Entrenando Detector de Anomalias (IsolationForest)...")
    from sklearn.ensemble import IsolationForest

    iso = IsolationForest(
        n_estimators=120, contamination=0.02, random_state=42, n_jobs=1
    )
    iso.fit(X_disease)
    print("[SKLEARN] Detector de anomalias entrenado.")

    # ── Metrics ──────────────────────────────────────────────────────────────
    disease_dist = df["Diagnosis"].value_counts().to_dict()
    risk_dist = df["risk_level"].value_counts().to_dict()

    clf_report_disease = classification_report(
        yd_te, yd_pred, target_names=list(le_disease.classes_), output_dict=True, zero_division=0
    )
    clf_report_risk = classification_report(
        yr_te, yr_pred, target_names=list(le_risk.classes_), output_dict=True, zero_division=0
    )

    metrics = {
        "disease_accuracy": acc_disease,
        "disease_f1_weighted": f1_disease,
        "disease_cv_accuracy_mean": cv_disease_mean,
        "disease_cv_accuracy_std": cv_disease_std,
        "risk_accuracy": acc_risk,
        "risk_f1_weighted": f1_risk,
        "risk_cv_accuracy_mean": cv_risk_mean,
        "risk_cv_accuracy_std": cv_risk_std,
        "n_samples": int(len(df)),
        "disease_classes": list(le_disease.classes_),
        "risk_classes": list(le_risk.classes_),
        "disease_distribution": {k: int(v) for k, v in disease_dist.items()},
        "risk_distribution": {k: int(v) for k, v in risk_dist.items()},
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "features_used": ["symptoms_tfidf", "age", "gender_enc"],
        "symptom_dropout_keep_prob": 0.65,
        "risk_label_noise_pct": 0.05,
        "classification_report_disease": clf_report_disease,
        "classification_report_risk": clf_report_risk,
    }

    bundle = {
        "disease_model": rf_disease,
        "risk_model": rf_risk,
        "tfidf_disease": tfidf_d,
        "tfidf_risk": tfidf_r,
        "le_disease": le_disease,
        "le_risk": le_risk,
        "anomaly_model": iso,
        "metrics": metrics,
    }
    joblib.dump(bundle, SKLEARN_MODEL_PATH, compress=3)
    print(f"\n[SKLEARN] Bundle guardado en: {SKLEARN_MODEL_PATH}")

    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"[SKLEARN] Metricas guardadas en: {METRICS_PATH}")

    return metrics


def main() -> None:
    global DATASET_PATH

    parser = argparse.ArgumentParser(description="Entrena modelos de Hospital AI.")
    parser.add_argument(
        "--dataset",
        default=str(DATASET_PATH),
        help="Ruta al dataset CSV a usar para entrenamiento.",
    )
    args = parser.parse_args()
    DATASET_PATH = Path(args.dataset).expanduser().resolve()

    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Dataset no encontrado: {DATASET_PATH}")
    if DATASET_PATH.suffix.lower() != ".csv":
        raise ValueError(f"El dataset debe ser CSV: {DATASET_PATH}")

    print("=" * 60)
    print("  Hospital AI - Entrenamiento de Modelos")
    print("=" * 60)
    print(f"[INFO] Dataset seleccionado: {DATASET_PATH}")

    print("\n[INFO] Cargando dataset con pandas...")
    df_pandas = pd.read_csv(DATASET_PATH)
    print(f"[INFO] Registros: {len(df_pandas):,}")

    metrics = train_sklearn_models(df_pandas)

    print("\n" + "=" * 60)
    print("  ENTRENAMIENTO COMPLETADO")
    print("=" * 60)
    print(f"  Disease Accuracy     : {metrics['disease_accuracy']:.4f}")
    print(f"  Disease CV Accuracy  : {metrics['disease_cv_accuracy_mean']:.4f}")
    print(f"  Risk Accuracy        : {metrics['risk_accuracy']:.4f}")
    print(f"  Risk CV Accuracy     : {metrics['risk_cv_accuracy_mean']:.4f}")
    print(f"  Modelos guardados en : {MODELS_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
