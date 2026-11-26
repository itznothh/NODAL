"""Run one image through the trained civic model; no labels are fabricated."""
import argparse
import json
from pathlib import Path
import sys

import tensorflow as tf

try:
    from .image_utils import load_preprocessed_image
    from .model_artifacts import ArtifactError, load_metadata, validate_model_shape
    from .thresholding import format_predictions
except ImportError:  # direct script execution
    from image_utils import load_preprocessed_image
    from model_artifacts import ArtifactError, load_metadata, validate_model_shape
    from thresholding import format_predictions


def predict_image(image_path, artifacts_dir, top_k=3, model_path=None):
    artifacts = Path(artifacts_dir)
    selected_model = Path(model_path) if model_path else artifacts / "nodal_civic.keras"
    labels, config = load_metadata(artifacts, selected_model)
    try:
        model = tf.keras.models.load_model(selected_model)
    except Exception as exc:
        raise ArtifactError(f"Could not load civic model '{selected_model}': {exc}") from exc
    label_data = json.loads((artifacts / "class_labels.json").read_text(encoding="utf-8"))
    validate_model_shape(model, labels, tuple(label_data["input_size"]))
    batch = load_preprocessed_image(image_path)[None, ...]
    try:
        scores = model.predict(batch, verbose=0)[0]
    except Exception as exc:
        raise ArtifactError(f"Civic model inference failed: {exc}") from exc
    return format_predictions(scores, labels, config, top_k=top_k)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--artifacts", type=Path, default=Path("ml/vision/artifacts"))
    parser.add_argument("--model", type=Path, help="Optional model override; metadata still loads from --artifacts")
    args = parser.parse_args()
    try:
        predictions, review_required = predict_image(args.image, args.artifacts, model_path=args.model)
    except (ArtifactError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"predictions": predictions, "review_required": review_required}, indent=2))


if __name__ == "__main__":
    main()
