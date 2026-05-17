# Modelos de IA

## CNN — Radiografías de tórax (3 clases)

Clasificación **Sana · Neumonía · COVID-19** con MobileNetV2 (`train_cnn.py`).

**Datasets** (carpeta `datasets/` en la raíz):

- `datasets/covid19/dataset_3_classes` — covid / normal / pneumonia_bac
- `datasets/covid19/dataset_4_classes` — añade pneumonia_vir (fusionada en neumonía)
- `datasets/pneumonia/chest_xray` — NORMAL / PNEUMONIA

**Entrenar:**

```bash
pip install tensorflow pillow scikit-learn
python models-ia/train_cnn.py --epochs 12 --no-mongo
```

Salida: `models-ia/models/cnn_xray_model.keras` y `cnn_metrics.json`.

**Verificar:**

```bash
python scripts/verify_cnn.py
```

En el portal: menú **Radiografías CNN** → subir JPG/PNG → **Analizar Radiografía**.

## Otros modelos

- `train_spark.py` — clasificadores tabulares (`.joblib`)
- `healthcare_models.joblib` — síntomas / riesgo / enfermedad
