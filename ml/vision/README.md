# NODAL Vision training workflow

This is a separate experimental four-class MobileNetV2 workflow. It does not
change the existing complaint text classifier or train inside Flask. No civic
image dataset was present when this pipeline was added, so no civic model or
performance claim is included.

## Prepare reviewed data

Either place verified images under `datasets/vision/raw/<class>/...` for
`pothole`, `garbage`, `waterlogging`, and `damaged_infrastructure`, or provide
a CSV manifest with `filepath,label` and preferably `group_id` columns. The
group should identify a source, sequence, location, or original dataset item;
all images with the same group ID remain in one split, including across labels.
Without group IDs, individual images are split and source-level leakage may
remain. Exact byte duplicates are reported and deduplicated; corrupt images,
unsupported labels, missing paths, and classes with fewer than three
independent image/source groups fail before replacing the existing split.
Splits are staged beside the target and replace the previous generated split;
the raw dataset is protected.

Check each dataset's license and labeling guidance before use. RDD2022's D40
is the pothole label; other damage labels are not potholes. TACO has
object-level annotations, so derive image labels carefully. FloodNet contains
aerial imagery; track its source/viewpoint in `group_id` and assess it
separately from street-level data where possible. The scripts never download
or invent labels.

## Run locally or in Colab

Use `.venv-vision` locally (or install `ml/vision/requirements-vision.txt` in
Colab). From the repository root:

```powershell
python ml/vision/prepare_dataset.py --input datasets/vision/raw --output datasets/vision/split
python ml/vision/train.py --data datasets/vision/split --artifacts ml/vision/artifacts
python ml/vision/evaluate.py --data datasets/vision/split --model ml/vision/artifacts/nodal_civic.keras
```

The notebook `NODAL_Vision_Training.ipynb` walks through these steps. Training
uses a fixed seed, a 70/15/15 source-group split, augmentation on training
batches only, explicit Pillow bilinear resizing to RGB 224x224, shared
MobileNetV2 preprocessing, and a frozen ImageNet backbone before optional
fine-tuning. Training, validation, test, CLI, and Flask civic inference share
the same decoding/resizing/preprocessing code. Keep the test set held out from
tuning.
Artifacts and generated datasets are git-ignored.

After training, civic inference can be enabled by setting
`NODAL_VISION_MODE=civic`; default `demo` mode retains the existing ImageNet
recognizer. Civic mode requires all three artifacts: `nodal_civic.keras`,
`class_labels.json`, and `inference_config.json`. The threshold is selected
from validation results only; if validation cannot meet the documented
precision rule, every prediction requires human review. Specifically, the
lowest confidence threshold whose selected validation predictions have a
95% Wilson lower bound of at least 0.80 top-1 accuracy (with at least 20
selected examples) is used to maximize coverage subject to that rule. Selection
requires at least 40 validation examples and five per class; otherwise the
saved configuration forces review for every prediction. These safeguards do
not establish real-world reliability.
