import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
VISION = ROOT / "ml" / "vision"
BACKEND = ROOT / "backend"
for path in (ROOT, VISION, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import image_utils
import model_artifacts
import predict
import prepare_dataset
import thresholding
import train
import services.vision_service as vision_service
from api.vision import vision_bp


def make_image(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path, format="PNG")


class DatasetPreparationTests(unittest.TestCase):
    def test_rerun_replaces_old_split_and_preserves_raw_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw, output = root / "raw", root / "split"
            for class_index, label in enumerate(image_utils.CLASS_LABELS):
                for i in range(6):
                    make_image(raw / label / f"{i}.png", (class_index * 40, i * 20, i + 1))
            raw_count = len(list(raw.rglob("*.png")))
            first = prepare_dataset.prepare_dataset(raw, output)
            self.assertEqual(first["total_images"], 24)
            stale = output / "train" / image_utils.CLASS_LABELS[0] / "stale.png"
            make_image(stale, (255, 0, 0))
            for label in image_utils.CLASS_LABELS:
                (raw / label / "5.png").unlink()
            second = prepare_dataset.prepare_dataset(raw, output)
            self.assertEqual(second["total_images"], 20)
            self.assertFalse(stale.exists())
            self.assertEqual(len(list(raw.rglob("*.png"))), raw_count - 4)
            self.assertEqual(sum(sum(v.values()) for v in second["split_counts"].values()), 20)

    def test_validation_failure_leaves_existing_split_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = root / "raw"; output = root / "split"
            for label in image_utils.CLASS_LABELS:
                for i in range(3):
                    make_image(raw / label / f"{i}.png", (i, len(label), 10))
            output.mkdir(); marker = output / "previous-generation.txt"; marker.write_text("keep", encoding="utf-8")
            (raw / image_utils.CLASS_LABELS[0] / "corrupt.png").write_bytes(b"broken")
            with self.assertRaisesRegex(prepare_dataset.DatasetError, "Corrupt"):
                prepare_dataset.prepare_dataset(raw, output)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_reports_corrupt_files_unknown_labels_and_missing_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad.png"
            bad.write_bytes(b"not an image")
            with self.assertRaisesRegex(prepare_dataset.DatasetError, "Corrupt"):
                prepare_dataset.validate_records([{"path": bad, "label": image_utils.CLASS_LABELS[0], "group": "x"}])
            manifest = root / "manifest.csv"
            manifest.write_text("filepath,label,group_id\nmissing.png,other,g1\n", encoding="utf-8")
            rows, _ = prepare_dataset.records_from_manifest(manifest)
            with self.assertRaisesRegex(prepare_dataset.DatasetError, "(?s)Unsupported manifest label.*Missing image path"):
                prepare_dataset.validate_records(rows)

    def test_duplicate_bytes_are_reported_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = root / "a.png", root / "b.png"
            make_image(a, (1, 2, 3)); b.write_bytes(a.read_bytes())
            rows = [{"path": p, "label": image_utils.CLASS_LABELS[0], "group": str(i)} for i, p in enumerate((a, b))]
            valid, duplicates = prepare_dataset.validate_records(rows)
            self.assertEqual(len(valid), 1)
            self.assertEqual(len(duplicates), 1)


class PreprocessingTests(unittest.TestCase):
    def test_training_validation_flask_and_cli_share_exact_preprocessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sample.png"
            make_image(source, (91, 127, 203))
            expected = image_utils.load_preprocessed_image(source)
            np.testing.assert_array_equal(expected, image_utils.mobilenetv2_preprocess(image_utils.load_rgb_array(source)))
            # Same source color is identical under every class folder and thus
            # the raw tensor delivered by each evaluation split is equal.
            for split in ("train", "validation", "test"):
                for label in image_utils.CLASS_LABELS:
                    make_image(root / split / label / "image.png", (91, 127, 203))
                xb, _ = next(iter(train.load_split(root, split, training=False)))
                np.testing.assert_allclose(xb[0].numpy(), expected, rtol=0, atol=1e-6)
            img = Image.open(source).convert("RGB")
            # Flask's civic code calls these same utilities after image validation.
            np.testing.assert_array_equal(image_utils.mobilenetv2_preprocess(image_utils.load_rgb_array(img)), expected)
            self.assertEqual(tuple(xb.shape[1:]), (*image_utils.IMAGE_SIZE, 3))


class ThresholdTests(unittest.TestCase):
    def test_lowest_qualifying_threshold_maximizes_coverage(self):
        # 40 perfectly classified examples with increasing confidence.
        y = np.tile(np.arange(4), 10)
        conf = np.linspace(.5, .99, 40)
        probs = np.zeros((40, 4), dtype=float)
        probs[np.arange(40), y] = conf
        for i in range(40):
            probs[i, (y[i] + 1) % 4] = 1 - conf[i]
        selected = thresholding.select_review_threshold(y, probs, 4)
        self.assertFalse(selected["force_review"])
        self.assertEqual(selected["validation_sample_count"], 40)
        self.assertEqual(selected["selected_validation_count"], 40)
        self.assertEqual(selected["confidence_threshold"], .5)

    def test_source_groups_never_cross_splits_even_across_classes(self):
        rows = []
        for label in image_utils.CLASS_LABELS:
            for i in range(6):
                group = f"shared-source-{i}" if i < 2 else f"{label}-source-{i}"
                rows.append({"path": Path(f"/{label}-{i}.png"), "label": label, "group": group})
        splits = prepare_dataset.split_rows(rows)
        assigned = {row["group"]: split for split, items in splits.items() for row in items}
        self.assertEqual(len(assigned), len(set(row["group"] for row in rows)))
        for group in set(row["group"] for row in rows):
            self.assertEqual(len({split for split, items in splits.items() for row in items if row["group"] == group}), 1)

    def test_insufficient_validation_forces_review(self):
        y = np.tile(np.arange(4), 2)
        probs = np.full((8, 4), .25)
        result = thresholding.select_review_threshold(y, probs, 4)
        self.assertTrue(result["force_review"])
        self.assertEqual(result["confidence_threshold"], 1.0)
        self.assertEqual(result["selection_status"], "insufficient_validation_data")
        self.assertTrue(thresholding.is_uncertain(1.0, result))


class ArtifactAndInferenceTests(unittest.TestCase):
    def _write_artifacts(self, folder, threshold=.8, force_review=False):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "nodal_civic.keras").write_bytes(b"mock model marker")
        (folder / "class_labels.json").write_text(json.dumps({"classes": list(image_utils.CLASS_LABELS), "input_size": [224, 224]}), encoding="utf-8")
        (folder / "inference_config.json").write_text(json.dumps({"confidence_threshold": threshold, "force_review": force_review}), encoding="utf-8")

    def test_missing_and_incompatible_artifacts_are_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with self.assertRaisesRegex(model_artifacts.ArtifactError, "Missing civic model artifact"):
                model_artifacts.load_metadata(folder)
            self._write_artifacts(folder)
            labels, config = model_artifacts.load_metadata(folder)
            model_artifacts.validate_model_shape(SimpleNamespace(input_shape=(None, 224, 224, 3), output_shape=(None, 4)), labels, (224, 224))
            with self.assertRaisesRegex(model_artifacts.ArtifactError, "output shape"):
                model_artifacts.validate_model_shape(SimpleNamespace(input_shape=(None, 224, 224, 3), output_shape=(None, 3)), labels, (224, 224))
            with self.assertRaisesRegex(model_artifacts.ArtifactError, "input shape"):
                model_artifacts.validate_model_shape(SimpleNamespace(input_shape=(None, 160, 160, 3), output_shape=(None, 4)), labels, (224, 224))
            (folder / "class_labels.json").write_text(json.dumps({"classes": list(reversed(image_utils.CLASS_LABELS)), "input_size": [224, 224]}), encoding="utf-8")
            with self.assertRaisesRegex(model_artifacts.ArtifactError, "canonical ordered classes"):
                model_artifacts.load_metadata(folder)
            (folder / "class_labels.json").write_text(json.dumps({"classes": list(image_utils.CLASS_LABELS), "input_size": [224, 224]}), encoding="utf-8")
            (folder / "inference_config.json").write_text(json.dumps({"confidence_threshold": 1.2}), encoding="utf-8")
            with self.assertRaisesRegex(model_artifacts.ArtifactError, "between 0 and 1"):
                model_artifacts.load_metadata(folder)

    def test_cli_uses_saved_class_mapping_threshold_and_review_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); artifacts = root / "artifacts"; self._write_artifacts(artifacts, threshold=.95)
            image = root / "input.png"; make_image(image, (20, 40, 60))
            captured = {}
            def fake_predict(batch, verbose=0):
                captured["batch"] = batch.numpy() if hasattr(batch, "numpy") else np.asarray(batch)
                return np.array([[.04, .90, .03, .03]])
            fake_model = SimpleNamespace(input_shape=(None, 224, 224, 3), output_shape=(None, 4), predict=fake_predict)
            with mock.patch.object(predict.tf.keras.models, "load_model", return_value=fake_model):
                preds, review = predict.predict_image(image, artifacts)
            self.assertEqual(preds[0]["label"], "garbage")
            self.assertTrue(preds[0]["uncertain"])
            self.assertTrue(review)
            np.testing.assert_array_equal(captured["batch"][0], image_utils.load_preprocessed_image(image).numpy())

    def test_flask_prediction_applies_the_same_threshold_and_preprocessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"; make_image(source, (70, 100, 140))
            captured = {}
            class FakeModel:
                def predict(self, batch, verbose=0):
                    captured["batch"] = batch.numpy() if hasattr(batch, "numpy") else np.asarray(batch)
                    return np.array([[.03, .90, .04, .03]])
            state = {"model": FakeModel(), "classes": list(image_utils.CLASS_LABELS),
                     "config": {"confidence_threshold": .95, "force_review": False}}
            with mock.patch.object(vision_service, "_load_civic_model", return_value=state):
                data = source.read_bytes()
                pil_image = vision_service._read_image(data)
                predictions, review = vision_service._predict_civic(pil_image)
            expected = image_utils.load_preprocessed_image(source)[None, ...].numpy()
            np.testing.assert_array_equal(captured["batch"], expected)
            self.assertEqual(predictions[0]["label"], "garbage")
            self.assertTrue(predictions[0]["review_required"])
            self.assertTrue(review)

    def test_demo_is_default_and_missing_civic_model_returns_clear_503(self):
        image = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        image.close()
        path = Path(image.name)
        try:
            make_image(path, (4, 5, 6))
            data = path.read_bytes()
            fake_state = {"model": SimpleNamespace(predict=lambda batch, verbose=0: np.array([[.1]])),
                          "preprocess": lambda batch: batch,
                          "decode": lambda scores, top=3: [[("n0", "test_label", .9)]]}
            with mock.patch.dict(os.environ):
                os.environ.pop("NODAL_VISION_MODE", None)
                with mock.patch.object(vision_service, "_load_model", return_value=fake_state):
                    result = vision_service.predict(data)
                self.assertEqual(result[0]["label"], "test label")
                os.environ["NODAL_VISION_MODE"] = "civic"
                os.environ["NODAL_VISION_ARTIFACTS"] = str(path.parent / "definitely-missing-nodal-artifacts")
                vision_service._civic_state.update(model=None, classes=None, config=None)
                from flask import Flask
                app = Flask(__name__); app.register_blueprint(vision_bp)
                response = app.test_client().post("/vision/predict", data={"image": (path.open("rb"), "test.png")})
                self.assertEqual(response.status_code, 503)
                self.assertIn("Missing civic model artifact", response.get_json()["error"])
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
