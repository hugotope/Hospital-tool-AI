from __future__ import annotations

import csv
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT_DIR / "healthcare_dataset_100k.csv"


@app.get("/api/health")
def health() -> tuple[dict[str, str], int]:
    return {"status": "ok"}, 200


@app.get("/api/dataset/preview")
def dataset_preview():
    max_rows = request.args.get("rows", default=12, type=int)
    max_rows = max(1, min(max_rows, 100))

    if not DATASET_PATH.exists():
        return jsonify({"error": "Dataset no encontrado"}), 404

    with DATASET_PATH.open(mode="r", encoding="utf-8", newline="") as csvfile:
        reader = csv.reader(csvfile)
        headers = next(reader, [])
        rows = []
        for _, row in zip(range(max_rows), reader):
            rows.append(row)

    return jsonify({"headers": headers, "rows": rows}), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
