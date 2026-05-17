"""
CNN Training — Clasificación de Radiografías de Tórax
=======================================================
Arquitectura: MobileNetV2 con Transfer Learning (ImageNet)
Clases: normal (Sana) | pneumonia (Neumonía) | covid (COVID-19)

Datasets (carpeta `datasets/` en la raíz del proyecto):
  - covid19/dataset_3_classes  → covid / normal / pneumonia_bac
  - covid19/dataset_4_classes → añade pneumonia_vir (se fusiona en pneumonia)
  - pneumonia/chest_xray      → NORMAL / PNEUMONIA (train, test, val)

Uso:
  python models-ia/train_cnn.py [--epochs 20] [--batch 32] [--no-mongo]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
DATASETS = ROOT_DIR / "datasets"
MODELS_DIR = ROOT_DIR / "models-ia" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

CNN_MODEL_PATH = MODELS_DIR / "cnn_xray_model.keras"
CNN_METRICS = MODELS_DIR / "cnn_metrics.json"

IMG_SIZE = (224, 224)
CLASSES = ["normal", "pneumonia", "covid"]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _first_existing(*paths: Path) -> Path | None:
    for p in paths:
        if p.is_dir():
            return p
    return None


def resolve_dataset_paths() -> tuple[Path | None, Path | None, Path | None]:
    """Localiza datasets bajo `datasets/` con rutas alternativas legacy."""
    covid_ds = _first_existing(
        DATASETS / "covid19" / "dataset_3_classes",
        DATASETS / "archive (6)" / "dataset_3_classes",
    )
    chest_ds = _first_existing(
        DATASETS / "pneumonia" / "chest_xray",
        DATASETS / "pneumonia" / "chest_xray" / "chest_xray",
        DATASETS / "archive (7)" / "chest_xray",
    )
    covid4_ds = _first_existing(
        DATASETS / "covid19" / "dataset_4_classes",
        DATASETS / "archive (6)" / "dataset_4_classes",
    )
    return covid_ds, chest_ds, covid4_ds


def _copy_images(src: Path, dst: Path, label: str, prefix: str) -> int:
    out = dst / label
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    if not src.is_dir():
        return 0
    for img in src.iterdir():
        if img.suffix.lower() not in IMAGE_EXTS:
            continue
        dest_name = f"{prefix}_{label}_{img.name}"
        shutil.copy2(img, out / dest_name)
        count += 1
    return count


def build_unified_dataset(tmp_root: Path) -> dict[str, dict[str, int]]:
    """Combina covid19 + chest_xray en tmp_root/{train,test,val}/<class>/."""
    covid_ds, chest_ds, covid4_ds = resolve_dataset_paths()

    if covid_ds is None and chest_ds is None:
        sys.exit(
            "[ERROR] No se encontraron datasets en 'datasets/'.\n"
            "  Esperado:\n"
            "    datasets/covid19/dataset_3_classes/{train,test}/...\n"
            "    datasets/pneumonia/chest_xray/{train,test}/NORMAL|PNEUMONIA\n"
        )

    counts: dict[str, dict[str, int]] = {"train": {}, "test": {}, "val": {}}
    sources: list[str] = []

    def add(
        src: Path,
        label: str,
        split: str,
        prefix: str,
        *,
        oversample: int = 1,
    ) -> None:
        """oversample>1 duplica imágenes (p. ej. COVID con pocas muestras)."""
        n = 0
        reps = max(1, oversample) if split == "train" else 1
        for rep in range(reps):
            n += _copy_images(src, tmp_root / split, label, f"{prefix}_r{rep}")
        counts[split][label] = counts[split].get(label, 0) + n
        if n:
            extra = f" (x{reps} oversample)" if reps > 1 else ""
            print(f"  [{split:5s}] {label:10s} <- {src} : {n} imgs{extra}")

    # COVID tiene ~60 imgs vs miles de pneumonia → oversample en train
    COVID_TRAIN_OVERSAMPLE = 40

    print("Combinando datasets en directorio temporal…")

    if covid_ds:
        sources.append(str(covid_ds.relative_to(ROOT_DIR)))
        for split in ("train", "test"):
            add(
                covid_ds / split / "covid",
                "covid",
                split,
                f"c3_{split}",
                oversample=COVID_TRAIN_OVERSAMPLE if split == "train" else 1,
            )
            add(covid_ds / split / "normal", "normal", split, f"c3_{split}")
            add(covid_ds / split / "pneumonia_bac", "pneumonia", split, f"c3_{split}")

    if covid4_ds:
        sources.append(str(covid4_ds.relative_to(ROOT_DIR)))
        for split in ("train", "test"):
            add(covid4_ds / split / "pneumonia_vir", "pneumonia", split, f"c4_{split}")

    if chest_ds:
        sources.append(str(chest_ds.relative_to(ROOT_DIR)))
        for split, sub in (("train", "tr"), ("test", "te"), ("val", "va")):
            add(chest_ds / split / "NORMAL", "normal", split if split != "val" else "train", f"cx_{sub}")
            add(chest_ds / split / "PNEUMONIA", "pneumonia", split if split != "val" else "train", f"cx_{sub}")
        # val solo refuerza entrenamiento (más datos para pneumonia/normal)

    total_train = sum(counts["train"].values())
    total_test = sum(counts["test"].values())
    if total_train < 30 or total_test < 10:
        sys.exit(
            f"[ERROR] Muy pocas imágenes (train={total_train}, test={total_test}). "
            "Revisa la carpeta datasets/."
        )

    counts["_sources"] = sources  # type: ignore[assignment]
    return counts


def train(epochs: int = 20, batch_size: int = 32, use_mongo: bool = True) -> dict[str, Any]:
    try:
        import tensorflow as tf
        from tensorflow import keras
        from tensorflow.keras import layers
        from tensorflow.keras.applications import MobileNetV2
        from tensorflow.keras.preprocessing.image import ImageDataGenerator
        from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
        from sklearn.utils.class_weight import compute_class_weight
    except ImportError as e:
        sys.exit(
            f"[ERROR] Dependencia faltante: {e}\n"
            "Instala: pip install tensorflow scikit-learn pillow"
        )

    print("\n=== CNN Training — Radiografías de Tórax ===")
    print(f"TensorFlow {tf.__version__} | epochs={epochs} | batch={batch_size}\n")

    tmp = tempfile.mkdtemp(prefix="xray_unified_")
    tmp_path = Path(tmp)
    try:
        counts = build_unified_dataset(tmp_path)
        sources = counts.pop("_sources", [])  # type: ignore[arg-type]
        print(f"\nImágenes de entrenamiento por clase: {counts.get('train', {})}")
        print(f"Imágenes de prueba por clase:        {counts.get('test', {})}\n")

        train_gen = ImageDataGenerator(
            rescale=1.0 / 255,
            rotation_range=20,
            width_shift_range=0.15,
            height_shift_range=0.15,
            shear_range=0.1,
            zoom_range=0.2,
            horizontal_flip=True,
            brightness_range=[0.8, 1.2],
            fill_mode="nearest",
            validation_split=0.15,
        )
        val_gen = ImageDataGenerator(rescale=1.0 / 255, validation_split=0.15)
        test_gen = ImageDataGenerator(rescale=1.0 / 255)

        common = dict(
            target_size=IMG_SIZE,
            batch_size=batch_size,
            class_mode="categorical",
            classes=CLASSES,
            shuffle=True,
            seed=42,
        )

        train_ds = train_gen.flow_from_directory(
            str(tmp_path / "train"), subset="training", **common
        )
        val_ds = val_gen.flow_from_directory(
            str(tmp_path / "train"), subset="validation", **common
        )
        test_ds = test_gen.flow_from_directory(
            str(tmp_path / "test"),
            batch_size=batch_size,
            class_mode="categorical",
            classes=CLASSES,
            shuffle=False,
            target_size=IMG_SIZE,
        )

        labels_flat = train_ds.classes
        class_weights_arr = compute_class_weight(
            "balanced", classes=np.unique(labels_flat), y=labels_flat
        )
        class_weight_dict = dict(enumerate(class_weights_arr))
        print(f"Class weights: {class_weight_dict}\n")

        base = MobileNetV2(
            input_shape=(*IMG_SIZE, 3),
            include_top=False,
            weights="imagenet",
        )
        base.trainable = False

        inputs = keras.Input(shape=(*IMG_SIZE, 3))
        x = base(inputs, training=False)
        x = layers.GlobalAveragePooling2D()(x)
        x = layers.BatchNormalization()(x)
        x = layers.Dense(256, activation="relu")(x)
        x = layers.Dropout(0.4)(x)
        x = layers.Dense(128, activation="relu")(x)
        x = layers.Dropout(0.3)(x)
        outputs = layers.Dense(len(CLASSES), activation="softmax")(x)
        model = keras.Model(inputs, outputs)

        model.compile(
            optimizer=keras.optimizers.Adam(1e-3),
            loss="categorical_crossentropy",
            metrics=["accuracy"],
        )

        callbacks = [
            keras.callbacks.EarlyStopping(
                patience=5, restore_best_weights=True, monitor="val_accuracy"
            ),
            keras.callbacks.ReduceLROnPlateau(factor=0.5, patience=3, monitor="val_loss"),
            keras.callbacks.ModelCheckpoint(
                str(CNN_MODEL_PATH),
                monitor="val_accuracy",
                save_best_only=True,
                verbose=1,
            ),
        ]

        phase1_epochs = max(1, epochs // 2)
        print(f"\n--- Fase 1: cabeza ({phase1_epochs} épocas) ---")
        history1 = model.fit(
            train_ds,
            epochs=phase1_epochs,
            validation_data=val_ds,
            class_weight=class_weight_dict,
            callbacks=callbacks,
        )

        base.trainable = True
        fine_tune_at = max(0, len(base.layers) - 30)
        for layer in base.layers[:fine_tune_at]:
            layer.trainable = False

        model.compile(
            optimizer=keras.optimizers.Adam(1e-4),
            loss="categorical_crossentropy",
            metrics=["accuracy"],
        )

        phase2_epochs = max(1, epochs - phase1_epochs)
        print(f"\n--- Fase 2: fine-tuning ({phase2_epochs} épocas) ---")
        history2 = model.fit(
            train_ds,
            epochs=phase2_epochs,
            validation_data=val_ds,
            class_weight=class_weight_dict,
            callbacks=callbacks,
        )

        print("\n--- Evaluación en test ---")
        test_ds.reset()
        y_pred_proba = model.predict(test_ds, verbose=1)
        y_pred = np.argmax(y_pred_proba, axis=1)
        y_true = test_ds.classes

        acc = float(accuracy_score(y_true, y_pred))
        cm = confusion_matrix(y_true, y_pred).tolist()
        report = classification_report(
            y_true, y_pred, target_names=CLASSES, output_dict=True
        )

        print(f"\nAccuracy en test: {acc:.4f}")
        print(classification_report(y_true, y_pred, target_names=CLASSES))

        model.save(str(CNN_MODEL_PATH))
        print(f"\nModelo guardado: {CNN_MODEL_PATH}")

        def _combine_hist(h1, h2, key):
            return h1.history.get(key, []) + h2.history.get(key, [])

        metrics = {
            "model": "MobileNetV2 + Transfer Learning",
            "architecture": {
                "base": "MobileNetV2 (ImageNet)",
                "input_size": list(IMG_SIZE),
                "classes": CLASSES,
                "class_labels_es": {"normal": "Sana", "pneumonia": "Neumonía", "covid": "COVID-19"},
                "fine_tune_layers": 30,
            },
            "training": {
                "epochs_phase1": phase1_epochs,
                "epochs_phase2": phase2_epochs,
                "batch_size": batch_size,
                "class_weights": {
                    CLASSES[k]: round(v, 4) for k, v in class_weight_dict.items()
                },
            },
            "dataset": {
                "train_counts": counts.get("train", {}),
                "test_counts": counts.get("test", {}),
                "sources": sources,
            },
            "evaluation": {
                "accuracy": round(acc, 4),
                "confusion_matrix": cm,
                "class_labels": CLASSES,
                "classification_report": {
                    k: {
                        mk: round(mv, 4) if isinstance(mv, float) else mv
                        for mk, mv in v.items()
                    }
                    if isinstance(v, dict)
                    else round(v, 4)
                    for k, v in report.items()
                },
            },
            "history": {
                "train_acc": [
                    round(v, 4) for v in _combine_hist(history1, history2, "accuracy")
                ],
                "val_acc": [
                    round(v, 4) for v in _combine_hist(history1, history2, "val_accuracy")
                ],
            },
            "clinical_analysis": {
                "critical_note": (
                    "Clasificación triple: Sana / Neumonía / COVID-19. "
                    "Falsos negativos en COVID-19 o Neumonía son críticos clínicamente."
                ),
            },
        }

        with open(CNN_METRICS, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        print(f"Métricas guardadas: {CNN_METRICS}")

        if use_mongo:
            try:
                sys.path.insert(0, str(ROOT_DIR / "back-end"))
                from mongodb_client import mongo

                if mongo.is_connected():
                    mongo.save_cnn_training_metrics(metrics)
                    print("Métricas guardadas en MongoDB.")
            except Exception as e:
                print(f"MongoDB omitido ({e}).")

        print("\n[OK] Entrenamiento completado.\n")
        return metrics
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Entrenar CNN de radiografías")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--no-mongo", action="store_true")
    args = parser.parse_args()

    train(epochs=args.epochs, batch_size=args.batch, use_mongo=not args.no_mongo)
