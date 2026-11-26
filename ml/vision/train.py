"""Train a MobileNetV2 transfer-learning classifier from split class folders."""
import argparse
import json
import random
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

try:
    from .image_utils import CLASS_LABELS, IMAGE_SIZE, mobilenetv2_preprocess, load_rgb_array
    from .thresholding import select_review_threshold
except ImportError:  # direct script execution
    from image_utils import CLASS_LABELS, IMAGE_SIZE, mobilenetv2_preprocess, load_rgb_array
    from thresholding import select_review_threshold

CLASSES = list(CLASS_LABELS)
SEED = 42
SIZE = IMAGE_SIZE


def load_split(root, split, training=False, batch_size=32):
    paths, labels = [], []
    for label_id, label in enumerate(CLASSES):
        folder = Path(root) / split / label
        if not folder.is_dir():
            raise ValueError(f"Missing class folder for {split}: {folder}")
        class_paths = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
        if not class_paths:
            raise ValueError(f"No images for class '{label}' in {split} split ({folder}).")
        paths.extend(str(p) for p in class_paths)
        labels.extend([label_id] * len(class_paths))
    ds = tf.data.Dataset.from_tensor_slices((paths, labels))
    if training:
        ds = ds.shuffle(len(paths), seed=SEED, reshuffle_each_iteration=True)

    def decode(path, label):
        image = tf.py_function(lambda p: load_rgb_array(p), [path], Tout=tf.uint8)
        image.set_shape((*SIZE, 3))
        return tf.cast(image, tf.float32), label

    ds = ds.map(decode, num_parallel_calls=tf.data.AUTOTUNE)
    ds = ds.batch(batch_size)
    augment = keras.Sequential([
        layers.RandomFlip("horizontal"), layers.RandomRotation(.05),
        layers.RandomZoom(.1), layers.RandomContrast(.1),
    ], name="training_augmentation")
    def prep(x, y):
        if training:
            x = augment(x, training=True)
        return mobilenetv2_preprocess(x), y
    return ds.map(prep, num_parallel_calls=tf.data.AUTOTUNE).prefetch(tf.data.AUTOTUNE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("datasets/vision/split"))
    parser.add_argument("--artifacts", type=Path, default=Path("ml/vision/artifacts"))
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--fine-tune", action="store_true", help="Optionally unfreeze last 30 backbone layers after head training")
    args = parser.parse_args()
    random.seed(SEED); np.random.seed(SEED); tf.random.set_seed(SEED)
    train = load_split(args.data, "train", True)
    val = load_split(args.data, "validation")
    backbone = keras.applications.MobileNetV2(input_shape=(*SIZE, 3), include_top=False, weights="imagenet")
    backbone.trainable = False
    inputs = keras.Input((*SIZE, 3))
    x = backbone(inputs, training=False)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(.25)(x)
    outputs = layers.Dense(len(CLASSES), activation="softmax")(x)
    model = keras.Model(inputs, outputs, name="nodal_mobilenetv2_civic")
    model.compile(optimizer=keras.optimizers.Adam(1e-3), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    args.artifacts.mkdir(parents=True, exist_ok=True)
    checkpoint = args.artifacts / "nodal_civic.keras"
    callbacks = [keras.callbacks.EarlyStopping(monitor="val_loss", patience=4, restore_best_weights=True),
                 keras.callbacks.ModelCheckpoint(checkpoint, monitor="val_loss", save_best_only=True)]
    history = model.fit(train, validation_data=val, epochs=args.epochs, callbacks=callbacks)
    if args.fine_tune:
        baseline_val_loss = float(keras.models.load_model(checkpoint).evaluate(val, verbose=0)[0])
        backbone.trainable = True
        for layer in backbone.layers[:-30]:
            layer.trainable = False
        model.compile(optimizer=keras.optimizers.Adam(1e-5), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
        history2 = model.fit(train, validation_data=val, epochs=min(args.epochs, 10), callbacks=[
            keras.callbacks.EarlyStopping(monitor="val_loss", patience=3, restore_best_weights=True)])
        if float(model.evaluate(val, verbose=0)[0]) < baseline_val_loss:
            model.save(checkpoint)
        history.history = {k: history.history.get(k, []) + history2.history.get(k, []) for k in set(history.history) | set(history2.history)}
    model = keras.models.load_model(checkpoint)
    # Validation is the only data used to select the human-review threshold.
    vy = np.concatenate([y.numpy() for _, y in val]); vp = np.concatenate([model.predict(x, verbose=0) for x, _ in val])
    threshold_config = select_review_threshold(vy, vp, len(CLASSES))
    report = {**threshold_config, "seed": SEED, "fine_tuned": bool(args.fine_tune),
              "training_history": history.history}
    (args.artifacts / "training_history.json").write_text(json.dumps(history.history, indent=2), encoding="utf-8")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for metric, ax in zip(("accuracy", "loss"), axes):
        ax.plot(history.history.get(metric, []), label="training")
        ax.plot(history.history.get("val_" + metric, []), label="validation")
        ax.set_title(metric.capitalize()); ax.set_xlabel("Epoch"); ax.legend()
    fig.tight_layout(); fig.savefig(args.artifacts / "training_curves.png", dpi=160); plt.close(fig)
    (args.artifacts / "class_labels.json").write_text(json.dumps({"classes": CLASSES, "input_size": list(SIZE)}, indent=2), encoding="utf-8")
    (args.artifacts / "inference_config.json").write_text(json.dumps(threshold_config, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "training_history"}, indent=2))
    print(f"Model size: {(args.artifacts / 'nodal_civic.keras').stat().st_size / 1024 / 1024:.1f} MiB")


if __name__ == "__main__":
    main()
