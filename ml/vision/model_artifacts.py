"""Load and validate civic model metadata and tensor dimensions."""
import json
from pathlib import Path

try:
    from .image_utils import CLASS_LABELS, IMAGE_SIZE
except ImportError:  # direct script/backend path loading
    from image_utils import CLASS_LABELS, IMAGE_SIZE

REQUIRED_ARTIFACTS = ("nodal_civic.keras", "class_labels.json", "inference_config.json")


class ArtifactError(ValueError):
    pass


def load_metadata(artifacts_dir, model_path=None):
    root = Path(artifacts_dir)
    selected_model = Path(model_path) if model_path else root / REQUIRED_ARTIFACTS[0]
    absent = [name for name in REQUIRED_ARTIFACTS[1:] if not (root / name).is_file()]
    if not selected_model.is_file():
        absent.insert(0, str(selected_model))
    if absent:
        raise ArtifactError("Missing civic model artifact(s): " + ", ".join(absent))
    try:
        labels_data = json.loads((root / "class_labels.json").read_text(encoding="utf-8"))
        config = json.loads((root / "inference_config.json").read_text(encoding="utf-8"))
        labels = labels_data["classes"]
        input_size = tuple(labels_data["input_size"])
        threshold = float(config["confidence_threshold"])
        force_review = bool(config.get("force_review", False))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ArtifactError(f"Invalid civic model metadata: {exc}") from exc
    if not isinstance(labels, list) or tuple(labels) != CLASS_LABELS:
        raise ArtifactError(f"Class labels must match canonical ordered classes: {list(CLASS_LABELS)}")
    if len(set(labels)) != len(labels):
        raise ArtifactError("Class labels must be unique.")
    if input_size != IMAGE_SIZE:
        raise ArtifactError(f"Configured input_size must be {list(IMAGE_SIZE)}.")
    if not 0.0 <= threshold <= 1.0:
        raise ArtifactError("confidence_threshold must be between 0 and 1 inclusive.")
    if not isinstance(config.get("force_review", False), bool):
        raise ArtifactError("force_review must be a boolean.")
    return labels, config


def validate_model_shape(model, labels, input_size):
    """Reject loaded models whose input/output shapes disagree with metadata."""
    try:
        input_shape = tuple(model.input_shape)
        output_shape = tuple(model.output_shape)
    except (AttributeError, TypeError) as exc:
        raise ArtifactError("Civic model must expose one input and one output tensor.") from exc
    expected_input = (None, input_size[0], input_size[1], 3)
    if input_shape != expected_input:
        raise ArtifactError(f"Model input shape {input_shape} does not match expected {expected_input}.")
    if len(output_shape) != 2 or output_shape[-1] != len(labels):
        raise ArtifactError(f"Model output shape {output_shape} does not match {len(labels)} class labels.")
