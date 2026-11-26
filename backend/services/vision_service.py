"""NODAL Vision inference with environment-selected demo or civic model."""
import io
import os
import sys
import threading
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

MODEL_NAME = "MobileNetV2 ImageNet pretrained"
CIVIC_MODEL_NAME = "NODAL MobileNetV2 Civic Classifier"
MAX_BYTES = 5 * 1024 * 1024          # 5 MB upload limit
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
INPUT_SIZE = (224, 224)
ROOT = Path(__file__).resolve().parents[2]
VISION_DIR = ROOT / "ml" / "vision"
if str(VISION_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_DIR))

from image_utils import IMAGE_SIZE, load_rgb_array, mobilenetv2_preprocess
from model_artifacts import ArtifactError, load_metadata, validate_model_shape
from thresholding import format_predictions

_state = {"model": None, "preprocess": None, "decode": None}
_civic_state = {"model": None, "classes": None, "threshold": None}
_lock = threading.Lock()


class VisionError(Exception):
    """An error that is safe to show to the user."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _load_model():
    """Load MobileNetV2 once and reuse it across requests."""
    if _state["model"] is not None:
        return _state
    with _lock:
        if _state["model"] is not None:
            return _state
        try:
            from keras.applications.mobilenet_v2 import (
                MobileNetV2,
                decode_predictions,
                preprocess_input,
            )
        except ImportError:
            raise VisionError(
                "TensorFlow/Keras is not installed in this environment. "
                "Run: pip install tensorflow pillow",
                503,
            )
        try:
            # First run downloads the ImageNet weights (needs internet once).
            model = MobileNetV2(weights="imagenet")
        except Exception:
            raise VisionError(
                "Could not load the MobileNetV2 ImageNet weights. "
                "The first run downloads them, so check your internet connection.",
                503,
            )
        _state.update(model=model, preprocess=preprocess_input, decode=decode_predictions)
    return _state


def _read_image(data):
    """Validate the bytes as a supported image and return a 224x224 RGB image."""
    if not data:
        raise VisionError("The uploaded file is empty.")
    if len(data) > MAX_BYTES:
        raise VisionError("Image is too large. Maximum size is 5 MB.", 413)
    try:
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        img.load()  # forces a full decode so corrupt files fail here
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise VisionError("The file is not a valid image.")
    if fmt not in ALLOWED_FORMATS:
        raise VisionError(f"Unsupported image format ({fmt}). Use JPEG, PNG or WebP.", 415)
    return img.convert("RGB")


def predict(data, top_k=3):
    """Return predictions in the configured demo or civic mode."""
    img = _read_image(data)          # validate before the (slow) model load
    mode = os.getenv("NODAL_VISION_MODE", "demo").strip().lower()
    if mode == "civic":
        return _predict_civic(img)
    if mode != "demo":
        raise VisionError("NODAL_VISION_MODE must be 'demo' or 'civic'.", 503)
    # Keep the original demo resize and ImageNet preprocessing behavior.
    img = img.resize(INPUT_SIZE)
    state = _load_model()
    try:
        batch = np.expand_dims(np.asarray(img, dtype="float32"), axis=0)
        batch = state["preprocess"](batch)  # MobileNetV2 scaling to [-1, 1]
        scores = state["model"].predict(batch, verbose=0)
        decoded = state["decode"](scores, top=top_k)[0]
    except Exception:
        raise VisionError("The model failed while analysing this image.", 500)
    return [
        {"label": label.replace("_", " "), "confidence": round(float(score), 4)}
        for _, label, score in decoded
    ]


def _load_civic_model():
    if _civic_state["model"] is not None:
        return _civic_state
    with _lock:
        if _civic_state["model"] is not None:
            return _civic_state
        artifacts = Path(os.getenv("NODAL_VISION_ARTIFACTS", ROOT / "ml" / "vision" / "artifacts"))
        try:
            labels, config = load_metadata(artifacts)
            import keras
            model = keras.models.load_model(artifacts / "nodal_civic.keras")
            validate_model_shape(model, labels, IMAGE_SIZE)
        except ArtifactError as exc:
            raise VisionError(f"Invalid civic model artifacts: {exc}", 503)
        except Exception as exc:
            raise VisionError(f"Could not load civic model artifacts: {exc}", 503)
        _civic_state.update(model=model, classes=labels, config=config)
    return _civic_state


def _predict_civic(img):
    state = _load_civic_model()
    try:
        batch = np.expand_dims(load_rgb_array(img), axis=0)
        scores = state["model"].predict(mobilenetv2_preprocess(batch), verbose=0)[0]
        return format_predictions(scores, state["classes"], state["config"], top_k=3)
    except ValueError as exc:
        raise VisionError(f"Civic model output is incompatible with its class metadata: {exc}", 503)
    except Exception as exc:
        raise VisionError(f"Civic inference failed: {exc}", 500)
