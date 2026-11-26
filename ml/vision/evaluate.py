"""Evaluate a saved civic model once on the held-out test split."""
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import (accuracy_score, confusion_matrix, ConfusionMatrixDisplay,
                             precision_recall_fscore_support)
import tensorflow as tf

try:
    from .train import CLASSES, SIZE, load_split
except ImportError:  # direct script execution
    from train import CLASSES, SIZE, load_split


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("datasets/vision/split"))
    parser.add_argument("--model", type=Path, default=Path("ml/vision/artifacts/nodal_civic.keras"))
    parser.add_argument("--output", type=Path, default=Path("ml/vision/artifacts"))
    args = parser.parse_args()
    model = tf.keras.models.load_model(args.model)
    ds = load_split(args.data, "test")
    y = np.concatenate([labels.numpy() for _, labels in ds])
    probs = np.concatenate([model.predict(images, verbose=0) for images, _ in ds])
    pred = probs.argmax(1)
    p, r, f, n = precision_recall_fscore_support(y, pred, labels=range(len(CLASSES)), zero_division=0)
    cm = confusion_matrix(y, pred, labels=range(len(CLASSES)))
    report = {"test_accuracy": float(accuracy_score(y, pred)), "classes": {
        name: {"precision": float(p[i]), "recall": float(r[i]), "f1": float(f[i]), "support": int(n[i])}
        for i, name in enumerate(CLASSES)}, "confusion_matrix": cm.tolist(), "test_images": int(len(y))}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    disp = ConfusionMatrixDisplay(cm, display_labels=CLASSES)
    disp.plot(xticks_rotation=35, cmap="Blues", values_format="d")
    plt.tight_layout(); plt.savefig(args.output / "confusion_matrix.png", dpi=160); plt.close()
    print(json.dumps(report, indent=2))
    print(f"Model size: {args.model.stat().st_size / 1024 / 1024:.1f} MiB")


if __name__ == "__main__":
    main()
