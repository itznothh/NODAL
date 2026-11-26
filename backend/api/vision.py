from flask import Blueprint, jsonify, request

try:
    from ..services.vision_service import CIVIC_MODEL_NAME, MAX_BYTES, MODEL_NAME, VisionError, predict
except ImportError:  # direct ``python backend/app.py`` execution
    from services.vision_service import CIVIC_MODEL_NAME, MAX_BYTES, MODEL_NAME, VisionError, predict

vision_bp = Blueprint("vision", __name__, url_prefix="/vision")

DEMO_WARNING = "Generic ImageNet image recognition only; not a civic issue detector."
CIVIC_WARNING = "Prototype classifier. Predictions require human verification. Model confidence does not prove correctness."


@vision_bp.post("/predict")
def vision_predict():
    file = request.files.get("image")
    if file is None or not file.filename:
        return jsonify(success=False, error="No image uploaded. Send a file in the 'image' field."), 400

    data = file.read(MAX_BYTES + 1)  # processed in memory, never saved to disk or MongoDB
    try:
        result = predict(data)
    except VisionError as err:
        return jsonify(success=False, error=err.message), err.status

    # Demo returns a list; civic returns (list, needs_review).
    civic = isinstance(result, tuple)
    predictions, needs_review = result if civic else (result, False)
    return jsonify(success=True, mode="civic" if civic else "demo",
                   model=CIVIC_MODEL_NAME if civic else MODEL_NAME,
                   warning=(CIVIC_WARNING + (" Low confidence: human review required." if needs_review else "")) if civic else DEMO_WARNING,
                   predictions=predictions, review_required=needs_review if civic else False)
