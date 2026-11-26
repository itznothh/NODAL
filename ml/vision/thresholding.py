"""Validation-only confidence threshold selection for human-review routing."""
import numpy as np

MIN_VALIDATION_TOTAL = 40
MIN_VALIDATION_PER_CLASS = 5
MIN_SELECTED = 20
TARGET_PRECISION_LOWER_BOUND = 0.80
FALLBACK_THRESHOLD = 1.0


def wilson_lower_bound(successes, total, z=1.96):
    """Two-sided 95% Wilson lower confidence bound for a binomial proportion."""
    if total <= 0:
        return 0.0
    p = successes / total
    z2 = z * z
    denom = 1 + z2 / total
    center = p + z2 / (2 * total)
    margin = z * ((p * (1 - p) / total + z2 / (4 * total * total)) ** 0.5)
    return (center - margin) / denom


def select_review_threshold(y_true, probabilities, class_count):
    """Choose lowest threshold maximizing coverage with a conservative precision bound.

    Among validation examples whose top class confidence meets a threshold, the
    top-1 accuracy Wilson 95% lower bound must be at least 0.80, with at least
    20 selected examples. This chooses the lowest (highest coverage) qualifying
    threshold. Insufficient validation uses threshold=1 plus force_review.
    """
    y_true = np.asarray(y_true, dtype=np.int64).reshape(-1)
    probs = np.asarray(probabilities, dtype=np.float64)
    if probs.ndim != 2 or probs.shape[1] != class_count or len(y_true) != len(probs):
        return {"confidence_threshold": FALLBACK_THRESHOLD, "force_review": True,
                "validation_sample_count": int(len(y_true)), "selection_status": "invalid_validation_predictions",
                "selection_rule": _rule_text()}
    if (not np.all(np.isfinite(probs)) or np.any(probs < 0) or np.any(probs > 1)
            or not np.allclose(probs.sum(axis=1), 1.0, atol=1e-3)):
        return {"confidence_threshold": FALLBACK_THRESHOLD, "force_review": True,
                "validation_sample_count": int(len(y_true)), "selection_status": "invalid_validation_probabilities",
                "selection_rule": _rule_text()}
    if len(y_true) == 0 or np.any(y_true < 0) or np.any(y_true >= class_count):
        return {"confidence_threshold": FALLBACK_THRESHOLD, "force_review": True,
                "validation_sample_count": int(len(y_true)), "selection_status": "invalid_validation_labels",
                "selection_rule": _rule_text()}
    counts = np.bincount(y_true, minlength=class_count)
    if len(y_true) < MIN_VALIDATION_TOTAL or np.any(counts < MIN_VALIDATION_PER_CLASS):
        return {"confidence_threshold": FALLBACK_THRESHOLD, "force_review": True,
                "validation_sample_count": int(len(y_true)), "validation_class_counts": counts.tolist(),
                "selection_status": "insufficient_validation_data", "selection_rule": _rule_text()}
    predicted = probs.argmax(axis=1)
    confidence = probs.max(axis=1)
    # Ascending candidates: the first qualifying value is the lowest threshold,
    # hence the highest coverage satisfying the precision lower-bound rule.
    for threshold in sorted(set(float(x) for x in confidence)):
        selected = confidence >= threshold
        total = int(selected.sum())
        correct = int((predicted[selected] == y_true[selected]).sum())
        if total >= MIN_SELECTED and wilson_lower_bound(correct, total) >= TARGET_PRECISION_LOWER_BOUND:
            return {"confidence_threshold": threshold, "force_review": False,
                    "validation_sample_count": int(len(y_true)), "validation_class_counts": counts.tolist(),
                    "selected_validation_count": total,
                    "selected_validation_accuracy": correct / total,
                    "selected_precision_wilson_95_lower_bound": wilson_lower_bound(correct, total),
                    "selection_status": "selected", "selection_rule": _rule_text()}
    return {"confidence_threshold": FALLBACK_THRESHOLD, "force_review": True,
            "validation_sample_count": int(len(y_true)), "validation_class_counts": counts.tolist(),
            "selection_status": "no_threshold_met_precision_rule", "selection_rule": _rule_text()}


def _rule_text():
    return ("Lowest confidence threshold maximizing coverage while the top-1 accuracy's "
            "95% Wilson lower bound is >= 0.80 on at least 20 selected validation examples; "
            "requires >=40 validation examples and >=5 per class. Otherwise force human review.")


def is_uncertain(confidence, config):
    return bool(config.get("force_review", False) or float(confidence) < float(config["confidence_threshold"]))


def format_predictions(probabilities, labels, config, top_k=3):
    scores = np.asarray(probabilities, dtype=np.float64).reshape(-1)
    if len(scores) != len(labels):
        raise ValueError("Prediction output count does not match class labels.")
    if not np.all(np.isfinite(scores)) or np.any(scores < 0) or np.any(scores > 1):
        raise ValueError("Model predictions must be finite probabilities between 0 and 1.")
    if not np.isclose(scores.sum(), 1.0, atol=1e-3):
        raise ValueError("Model predictions must sum to 1.")
    indices = np.argsort(scores)[::-1][:top_k]
    result = []
    for index in indices:
        confidence = float(scores[index])
        review = is_uncertain(confidence, config)
        result.append({"label": labels[int(index)], "confidence": round(confidence, 4),
                       "uncertain": review, "review_required": review})
    return result, bool(result and result[0]["review_required"])
