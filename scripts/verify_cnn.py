#!/usr/bin/env python3
"""Verifica carga del modelo CNN y predicción en imágenes de test."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "back-end"))

from cnn_predictor import cnn_predictor, CNN_MODEL_PATH

SAMPLES = [
    ("covid", ROOT / "datasets/covid19/dataset_3_classes/test/covid/nejmoa2001191_f3-PA.jpeg"),
    ("normal", ROOT / "datasets/pneumonia/chest_xray/test/NORMAL/IM-0001-0001.jpeg"),
    ("pneumonia", ROOT / "datasets/pneumonia/chest_xray/test/PNEUMONIA/person100_bacteria_475.jpeg"),
]


def main() -> int:
    if not CNN_MODEL_PATH.exists():
        print(f"[FAIL] Modelo no encontrado: {CNN_MODEL_PATH}")
        print("  Entrena con: python models-ia/train_cnn.py --epochs 12 --no-mongo")
        return 1

    if not cnn_predictor.load():
        print(f"[FAIL] No se pudo cargar: {cnn_predictor.error}")
        return 1

    ok_count = 0
    for expected, path in SAMPLES:
        if not path.is_file():
            print(f"[SKIP] {expected}: no existe {path}")
            continue
        result = cnn_predictor.predict(path.read_bytes(), path.name)
        got = result["class"]
        status = "OK" if got == expected else "MISS"
        if got == expected:
            ok_count += 1
        print(
            f"[{status}] esperado={expected} predicho={got} "
            f"({result['label']} {result['confidence_pct']}%)"
        )

    print(f"\n{ok_count}/{len(SAMPLES)} aciertos en muestras de test.")
    return 0 if ok_count >= 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
