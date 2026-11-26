"""Validate curated image labels and atomically build deterministic splits."""
import argparse
import csv
import hashlib
import random
import shutil
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path

from PIL import Image

try:
    from .image_utils import CLASS_LABELS, load_rgb_array
except ImportError:  # direct script execution from the repository root
    from image_utils import CLASS_LABELS, load_rgb_array

CLASSES = CLASS_LABELS
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SEED = 42
SPLIT_RATIOS = {"train": .70, "validation": .15, "test": .15}


class DatasetError(ValueError):
    pass


def records_from_dirs(root):
    root = Path(root)
    rows = []
    unsupported = sorted(p.name for p in root.iterdir() if p.is_dir() and p.name not in CLASSES) if root.is_dir() else []
    for label in CLASSES:
        folder = root / label
        if folder.exists():
            rows.extend({"path": p, "label": label, "group": ""}
                        for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS)
    return rows, unsupported


def records_from_manifest(manifest):
    rows = []
    with Path(manifest).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not {"filepath", "label"}.issubset(reader.fieldnames or []):
            raise DatasetError("Manifest needs filepath,label columns; optional group_id prevents source leakage.")
        for line, row in enumerate(reader, start=2):
            raw_path = (row.get("filepath") or "").strip()
            p = Path(raw_path)
            if not p.is_absolute():
                p = Path(manifest).parent / p
            rows.append({"path": p, "label": (row.get("label") or "").strip(),
                         "group": (row.get("group_id") or "").strip(), "line": line})
    return rows, []


def validate_records(rows, unsupported_dirs=()):
    problems = []
    if unsupported_dirs:
        problems.append("Unsupported class directory label(s): " + ", ".join(unsupported_dirs))
    unsupported = sorted({r["label"] or "<blank>" for r in rows if r["label"] not in CLASSES})
    if unsupported:
        problems.append("Unsupported manifest label(s): " + ", ".join(unsupported))
    missing = [f"{r['path']} (manifest line {r.get('line', '?')})" for r in rows if not r["path"].is_file()]
    if missing:
        problems.append("Missing image path(s): " + "; ".join(missing))
    if problems:
        raise DatasetError("\n".join(problems))

    hashes = {}
    valid = []
    duplicate_paths = []
    corrupt = []
    conflicts = []
    for row in rows:
        path = row["path"]
        try:
            raw = path.read_bytes()
            # Decode fully and check format, not just filename extension.
            with Image.open(path) as image:
                image.verify()
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError(f"unsupported image format {image.format}")
            load_rgb_array(path)  # verifies decodability and target conversion
        except Exception as exc:
            corrupt.append(f"{path}: {exc}")
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if digest in hashes:
            previous = hashes[digest]
            if previous["label"] != row["label"]:
                conflicts.append(f"{previous['path']} ({previous['label']}) == {path} ({row['label']})")
            else:
                duplicate_paths.append(f"{path} duplicates {previous['path']}")
            continue
        hashes[digest] = row
        valid.append(row)
    if corrupt:
        problems.append("Corrupt or unsupported image file(s): " + "; ".join(corrupt))
    if conflicts:
        problems.append("Exact duplicate bytes have conflicting labels: " + "; ".join(conflicts))
    if problems:
        raise DatasetError("\n".join(problems))
    return valid, duplicate_paths


def split_rows(rows, seed=SEED):
    rng = random.Random(seed)
    grouped = defaultdict(list)
    for row in rows:
        # A source ID is global, so a source represented in multiple classes is
        # still held entirely in one split.
        key = row["group"] or f"__file__:{row['path'].resolve()}"
        grouped[key].append(row)
    groups = list(grouped.values())
    if len(groups) < 3:
        raise DatasetError("Need at least 3 independent source groups overall for train/validation/test.")
    for label in CLASSES:
        n_groups = len({row["group"] or f"__file__:{row['path'].resolve()}" for row in rows if row["label"] == label})
        if n_groups < 3:
            raise DatasetError(f"Class '{label}' has only {n_groups} independent image/source group(s); need at least 3.")
    rng.shuffle(groups)
    labels = {label: sum(row["label"] == label for row in rows) for label in CLASSES}
    targets = {split: {label: ratio * labels[label] for label in CLASSES}
               for split, ratio in SPLIT_RATIOS.items()}
    counts = {split: defaultdict(int) for split in SPLIT_RATIOS}
    result = {split: [] for split in SPLIT_RATIOS}
    groups.sort(key=len, reverse=True)
    for group in groups:
        group_counts = defaultdict(int)
        for row in group:
            group_counts[row["label"]] += 1
        def deficit(split):
            return sum((targets[split][label] - counts[split][label]) / max(targets[split][label], 1)
                       for label in group_counts)
        split = max(SPLIT_RATIOS, key=deficit)
        result[split].extend(group)
        for label, count in group_counts.items():
            counts[split][label] += count
    for label in CLASSES:
        absent = [split for split, items in result.items() if not any(row["label"] == label for row in items)]
        if absent:
            raise DatasetError(f"Grouped split leaves class '{label}' empty in {', '.join(absent)}; adjust source groups/data.")
    return result


def count_splits(splits):
    return {split: {label: sum(row["label"] == label for row in rows) for label in CLASSES}
            for split, rows in splits.items()}


def _is_within(child, parent):
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def prepare_dataset(input_dir, output_dir, manifest=None):
    requested_output = Path(output_dir).absolute()
    if requested_output.is_symlink():
        raise DatasetError("Refusing to replace a symlink as the split output directory.")
    output = requested_output.resolve()
    if manifest:
        rows, unsupported_dirs = records_from_manifest(manifest)
        raw_root = None
    else:
        rows, unsupported_dirs = records_from_dirs(input_dir)
        raw_root = Path(input_dir).resolve()
    output_covers_source = any(_is_within(row["path"], output) for row in rows)
    if (raw_root and _is_within(output, raw_root)) or output_covers_source:
        raise DatasetError("Output split directory must be separate from the raw dataset; raw files are protected.")
    rows, duplicates = validate_records(rows, unsupported_dirs)
    input_counts = {label: sum(row["label"] == label for row in rows) for label in CLASSES}
    missing_classes = [label for label, count in input_counts.items() if count == 0]
    if missing_classes:
        raise DatasetError("No valid images for class(es): " + ", ".join(missing_classes))
    missing_groups = sum(not row.get("group") for row in rows)
    if missing_groups:
        print(f"WARNING: {missing_groups} image(s) lack group_id; exact duplicates were removed, but source-level leakage may remain.")
    splits = split_rows(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    staged_parent = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    staged = staged_parent / output.name
    backup = output.parent / f".{output.name}.backup-{uuid.uuid4().hex}"
    moved_old = False
    try:
        for split, items in splits.items():
            for row in items:
                target_dir = staged / split / row["label"]
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / row["path"].name
                if target.exists():
                    suffix = hashlib.sha256(str(row["path"].resolve()).encode()).hexdigest()[:12]
                    target = target_dir / f"{row['path'].stem}_{suffix}{row['path'].suffix.lower()}"
                shutil.copy2(row["path"], target)
        if output.exists():
            if not output.is_dir():
                raise DatasetError(f"Output exists and is not a directory: {output}")
            output.replace(backup)
            moved_old = True
        staged.replace(output)
        if moved_old:
            shutil.rmtree(backup)
    except Exception:
        if moved_old and backup.exists() and not output.exists():
            backup.replace(output)
        raise
    finally:
        if staged_parent.exists():
            shutil.rmtree(staged_parent, ignore_errors=True)
        if backup.exists() and output.exists():
            shutil.rmtree(backup, ignore_errors=True)
    report = {"input_counts": input_counts, "split_counts": count_splits(splits),
              "duplicates_removed": len(duplicates), "missing_group_ids": missing_groups,
              "total_images": len(rows), "seed": SEED}
    for duplicate in duplicates:
        print(f"DUPLICATE removed: {duplicate}")
    print("Input image counts:", report["input_counts"])
    print("Split image counts:", report["split_counts"])
    print(f"Total: {report['total_images']}; duplicates removed: {report['duplicates_removed']}; seed: {SEED}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("datasets/vision/raw"))
    parser.add_argument("--manifest", type=Path, help="CSV with filepath,label[,group_id]")
    parser.add_argument("--output", type=Path, default=Path("datasets/vision/split"))
    args = parser.parse_args()
    try:
        prepare_dataset(args.input, args.output, args.manifest)
    except DatasetError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
