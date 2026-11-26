"""Shared image decoding, resizing, and MobileNetV2 input preprocessing."""
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

IMAGE_SIZE = (224, 224)  # height, width
IMAGE_INTERPOLATION = Image.Resampling.BILINEAR
CLASS_LABELS = ("pothole", "garbage", "waterlogging", "damaged_infrastructure")


def load_rgb_array(source):
    """Decode a path or Pillow image to explicit RGB, bilinear 224x224 pixels."""
    try:
        if isinstance(source, Image.Image):
            image = source
            return np.asarray(image.convert("RGB").resize(
                (IMAGE_SIZE[1], IMAGE_SIZE[0]), resample=IMAGE_INTERPOLATION), dtype=np.uint8)
        if hasattr(source, "numpy"):
            source = source.numpy()
        if isinstance(source, bytes):
            source = source.decode("utf-8")
        with Image.open(Path(source)) as image:
            image.load()
            return np.asarray(image.convert("RGB").resize(
                (IMAGE_SIZE[1], IMAGE_SIZE[0]), resample=IMAGE_INTERPOLATION), dtype=np.uint8)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Could not decode image: {source}") from exc


def mobilenetv2_preprocess(rgb_pixels):
    """Apply Keras MobileNetV2 preprocessing (RGB uint8/float pixels to [-1, 1])."""
    import tensorflow as tf
    from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

    pixels = rgb_pixels if tf.is_tensor(rgb_pixels) else tf.convert_to_tensor(rgb_pixels)
    return preprocess_input(tf.cast(pixels, tf.float32))


def load_preprocessed_image(source):
    """Return one shared-path image tensor with shape (224, 224, 3)."""
    return mobilenetv2_preprocess(load_rgb_array(source))
