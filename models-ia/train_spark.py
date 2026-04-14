"""
Hospital AI - Entrenamiento de Modelos con PySpark + Sklearn
=============================================================
Este script entrena dos modelos:
  1. Clasificador de Enfermedades  (RandomForest)
  2. Clasificador de Riesgo        (RandomForest - Low / Medium / High)

Flujo:
  PySpark  →  ETL + feature engineering + entrenamiento distribuido
  Sklearn  →  serializa modelos ligeros para servir desde Flask

Uso:
    python train_spark.py
"""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import scipy.sparse as sp
import joblib

# ── sklearn ──────────────────────────────────────────────────────────────────
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

# ── PySpark ──────────────────────────────────────────────────────────────────
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType
from pyspark.ml import Pipeline
from pyspark.ml.feature import (
    StringIndexer,
    RegexTokenizer,
    HashingTF,
    IDF,
    VectorAssembler,
)
from pyspark.ml.classification import RandomForestClassifier as SparkRFC
from pyspark.ml.evaluation import MulticlassClassificationEvaluator

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT_DIR / "healthcare_dataset_100k.csv"
MODELS_DIR = Path(__file__).resolve().parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

SKLEARN_MODEL_PATH = MODELS_DIR / "healthcare_models.joblib"
SPARK_DISEASE_PATH = str(MODELS_DIR / "spark_disease_classifier")
METRICS_PATH = MODELS_DIR / "metrics.json"

# ── Risk mapping ─────────────────────────────────────────────────────────────
HIGH_RISK_DIAGNOSES = {"Cancer", "Heart Disease", "Stroke"}
MEDIUM_RISK_DIAGNOSES = {
    "Diabetes", "Kidney Disease", "Liver Disease", "COVID-19", "Hypertension"
}


def assign_risk(diagnosis: str, age: int, days_stayed: int) -> str:
    if diagnosis in HIGH_RISK_DIAGNOSES or days_stayed > 21 or age >= 75:
        return "High"
    if diagnosis in MEDIUM_RISK_DIAGNOSES or days_stayed > 10 or age >= 60:
        return "Medium"
    return "Low"


# ─────────────────────────────────────────────────────────────────────────────
# PySpark training
# ─────────────────────────────────────────────────────────────────────────────

def create_spark_session() -> SparkSession:
    return (
        SparkSession.builder.appName("HospitalAI")
        .master("local[*]")
        .config("spark.driver.memory", "2g")
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )


def train_spark_disease_classifier(spark: SparkSession) -> dict:
    """
    Carga el CSV con Spark, construye un pipeline de ML completo y
    entrena un RandomForestClassifier para predecir el diagnóstico.
    Devuelve métricas y guarda el modelo PipelineModel en disco.
    """
    print("\n[SPARK] ══════════════════════════════════════════")
    print("[SPARK] Entrenando Clasificador de Enfermedades...")

    df = spark.read.csv(str(DATASET_PATH), header=True, inferSchema=True)
    print(f"[SPARK] Registros cargados: {df.count():,}")
    df.printSchema()

    # Feature: días hospitalizado
    df = df.withColumn(
        "days_stayed",
        F.datediff(
            F.to_date(F.col("Discharge_Date")),
            F.to_date(F.col("Date_of_Admission")),
        ),
    )

    # Filtrar nulos
    df = df.dropna(subset=["Age", "Gender", "Symptoms", "Diagnosis"])

    print("\n[SPARK] Distribución de diagnósticos:")
    df.groupBy("Diagnosis").count().orderBy("count", ascending=False).show()

    # ── Pipeline stages ──────────────────────────────────────────────────────
    gender_indexer = StringIndexer(
        inputCol="Gender", outputCol="gender_idx", handleInvalid="keep"
    )
    tokenizer = RegexTokenizer(
        inputCol="Symptoms", outputCol="tokens", pattern=r",\s*|\s+"
    )
    hashing_tf = HashingTF(inputCol="tokens", outputCol="tf_features", numFeatures=512)
    idf = IDF(inputCol="tf_features", outputCol="symptom_features", minDocFreq=2)
    assembler = VectorAssembler(
        inputCols=["Age", "gender_idx", "days_stayed", "symptom_features"],
        outputCol="features",
        handleInvalid="keep",
    )
    label_indexer = StringIndexer(
        inputCol="Diagnosis", outputCol="label", handleInvalid="keep"
    )
    rf = SparkRFC(
        featuresCol="features",
        labelCol="label",
        numTrees=100,
        maxDepth=10,
        seed=42,
    )

    pipeline = Pipeline(
        stages=[gender_indexer, tokenizer, hashing_tf, idf, assembler, label_indexer, rf]
    )

    train_df, test_df = df.randomSplit([0.8, 0.2], seed=42)
    print(f"\n[SPARK] Train: {train_df.count():,}  |  Test: {test_df.count():,}")

    print("[SPARK] Ajustando pipeline...")
    model = pipeline.fit(train_df)

    predictions = model.transform(test_df)
    evaluator = MulticlassClassificationEvaluator(
        labelCol="label", predictionCol="prediction", metricName="accuracy"
    )
    accuracy = evaluator.evaluate(predictions)
    print(f"[SPARK] Accuracy del clasificador de enfermedades: {accuracy:.4f}")

    # Guardar modelo Spark
    model.write().overwrite().save(SPARK_DISEASE_PATH)
    print(f"[SPARK] Modelo guardado en: {SPARK_DISEASE_PATH}")

    return {"spark_disease_accuracy": float(accuracy)}


# ─────────────────────────────────────────────────────────────────────────────
# Sklearn training (para servir desde Flask sin Spark overhead)
# ─────────────────────────────────────────────────────────────────────────────

def train_sklearn_models(df: pd.DataFrame) -> dict:
    """
    Entrena con sklearn sobre el mismo dataset (ya en Pandas).
    Guarda un único archivo .joblib con ambos modelos y metadatos.
    """
    print("\n[SKLEARN] ════════════════════════════════════════")
    print("[SKLEARN] Preparando features...")

    df = df.copy()
    df["days_stayed"] = (
        pd.to_datetime(df["Discharge_Date"]) - pd.to_datetime(df["Date_of_Admission"])
    ).dt.days.fillna(0).astype(int)

    df["risk_level"] = df.apply(
        lambda r: assign_risk(r["Diagnosis"], int(r["Age"]), int(r["days_stayed"])),
        axis=1,
    )

    gender_map = {"Male": 1, "Female": 0, "Other": 2}
    df["gender_enc"] = df["Gender"].map(gender_map).fillna(2).astype(int)
    df["symptoms_clean"] = df["Symptoms"].fillna("").str.lower().str.strip()

    # ── 1. Clasificador de enfermedades ──────────────────────────────────────
    print("\n[SKLEARN] Entrenando Clasificador de Enfermedades...")

    tfidf_d = TfidfVectorizer(max_features=300, ngram_range=(1, 2), sublinear_tf=True)
    sym_feat = tfidf_d.fit_transform(df["symptoms_clean"])
    num_feat = sp.csr_matrix(df[["Age", "gender_enc", "days_stayed"]].values)
    X_disease = sp.hstack([sym_feat, num_feat])

    le_disease = LabelEncoder()
    y_disease = le_disease.fit_transform(df["Diagnosis"])

    Xd_tr, Xd_te, yd_tr, yd_te = train_test_split(
        X_disease, y_disease, test_size=0.2, random_state=42, stratify=y_disease
    )
    rf_disease = RandomForestClassifier(
        n_estimators=150, max_depth=12, random_state=42, n_jobs=-1, class_weight="balanced"
    )
    rf_disease.fit(Xd_tr, yd_tr)
    yd_pred = rf_disease.predict(Xd_te)
    acc_disease = float(accuracy_score(yd_te, yd_pred))
    print(f"[SKLEARN] Accuracy enfermedades : {acc_disease:.4f}")
    print(classification_report(yd_te, yd_pred, target_names=le_disease.classes_))

    # ── 2. Clasificador de riesgo ────────────────────────────────────────────
    print("\n[SKLEARN] Entrenando Clasificador de Riesgo...")

    tfidf_r = TfidfVectorizer(max_features=300, ngram_range=(1, 2), sublinear_tf=True)
    sym_feat_r = tfidf_r.fit_transform(df["symptoms_clean"])
    X_risk = sp.hstack([sym_feat_r, num_feat])

    le_risk = LabelEncoder()
    y_risk = le_risk.fit_transform(df["risk_level"])

    Xr_tr, Xr_te, yr_tr, yr_te = train_test_split(
        X_risk, y_risk, test_size=0.2, random_state=42, stratify=y_risk
    )
    rf_risk = RandomForestClassifier(
        n_estimators=150, max_depth=12, random_state=42, n_jobs=-1, class_weight="balanced"
    )
    rf_risk.fit(Xr_tr, yr_tr)
    yr_pred = rf_risk.predict(Xr_te)
    acc_risk = float(accuracy_score(yr_te, yr_pred))
    print(f"[SKLEARN] Accuracy riesgo       : {acc_risk:.4f}")
    print(classification_report(yr_te, yr_pred, target_names=le_risk.classes_))

    # ── Métricas finales ─────────────────────────────────────────────────────
    risk_dist = df["risk_level"].value_counts().to_dict()
    disease_dist = df["Diagnosis"].value_counts().to_dict()

    metrics = {
        "disease_accuracy": acc_disease,
        "risk_accuracy": acc_risk,
        "n_samples": len(df),
        "disease_classes": list(le_disease.classes_),
        "risk_classes": list(le_risk.classes_),
        "risk_distribution": risk_dist,
        "disease_distribution": disease_dist,
        "trained_at": datetime.now().isoformat(),
    }

    # ── Serializar ───────────────────────────────────────────────────────────
    bundle = {
        "disease_model": rf_disease,
        "risk_model": rf_risk,
        "tfidf_disease": tfidf_d,
        "tfidf_risk": tfidf_r,
        "le_disease": le_disease,
        "le_risk": le_risk,
        "metrics": metrics,
    }
    joblib.dump(bundle, SKLEARN_MODEL_PATH, compress=3)
    print(f"\n[SKLEARN] Bundle guardado en: {SKLEARN_MODEL_PATH}")

    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"[SKLEARN] Métricas guardadas en: {METRICS_PATH}")

    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  Hospital AI — Entrenamiento de Modelos")
    print("=" * 60)

    # ── 1. Spark ─────────────────────────────────────────────────────────────
    print("\n[SPARK] Inicializando sesión de Spark...")
    spark = create_spark_session()
    spark.sparkContext.setLogLevel("ERROR")

    spark_metrics = train_spark_disease_classifier(spark)

    # ── 2. Pandas (para sklearn) ─────────────────────────────────────────────
    print("\n[INFO] Convirtiendo a Pandas para entrenamiento sklearn...")
    df_spark = spark.read.csv(str(DATASET_PATH), header=True, inferSchema=True)
    df_pandas = df_spark.toPandas()
    print(f"[INFO] Registros: {len(df_pandas):,}")

    spark.stop()
    print("[SPARK] Sesión finalizada.")

    # ── 3. Sklearn ───────────────────────────────────────────────────────────
    sklearn_metrics = train_sklearn_models(df_pandas)

    # ── Resumen ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  ENTRENAMIENTO COMPLETADO")
    print("=" * 60)
    print(f"  [Spark]   Disease Accuracy : {spark_metrics['spark_disease_accuracy']:.4f}")
    print(f"  [Sklearn] Disease Accuracy : {sklearn_metrics['disease_accuracy']:.4f}")
    print(f"  [Sklearn] Risk Accuracy    : {sklearn_metrics['risk_accuracy']:.4f}")
    print(f"  Modelos guardados en       : {MODELS_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
