import { useEffect, useRef, useState } from "react";
import "./VisionPanel.css";
import { request } from "./api";

const ALLOWED = ["image/jpeg", "image/png", "image/webp"];
const MAX_MB = 5;

export default function VisionPanel() {
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  // Free the preview URL when it changes or the component unmounts
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  function chooseFile(f) {
    setResult(null);
    setError("");
    if (!f) return;
    if (!ALLOWED.includes(f.type)) {
      setError("Unsupported file type. Please choose a JPEG, PNG or WebP image.");
      return;
    }
    if (f.size > MAX_MB * 1024 * 1024) {
      setError(`Image is too large. Maximum size is ${MAX_MB} MB.`);
      return;
    }
    setFile(f);
    setPreviewUrl(URL.createObjectURL(f));
  }

  function reset() {
    setFile(null);
    setPreviewUrl(null);
    setResult(null);
    setError("");
    if (inputRef.current) inputRef.current.value = "";
  }

  function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    chooseFile(e.dataTransfer.files?.[0]);
  }

  async function analyze() {
    if (!file) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const body = new FormData();
      body.append("image", file);
      const data = await request("/vision/predict", { method: "POST", body });
      setResult(data);
    } catch (err) {
      setError(err.message || "Cannot reach the API. Is the Flask server running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="vision">
      <h2>NODAL Vision</h2>

      <div className="vision-warning">
        <b>Image assistance:</b> The default ImageNet demo recognizes general objects; it is not a
        civic issue detector. Predictions never submit a report or choose its category. A civic
        prototype is available only after a separately trained model is installed and still needs
        human verification.
      </div>

      <div className="vision-body">
        <div
          className={`dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          {previewUrl ? (
            <img src={previewUrl} alt="Selected upload preview" className="preview" />
          ) : (
            <p>Drag and drop an image here, or choose one (JPEG, PNG, WebP, max {MAX_MB} MB)</p>
          )}
          <input
            ref={inputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            hidden
            onChange={(e) => chooseFile(e.target.files?.[0])}
          />
        </div>

        <div className="vision-side">
          <div className="vision-actions">
            <button onClick={() => inputRef.current?.click()} disabled={loading}>
              {file ? "Choose another image" : "Upload image"}
            </button>
            <button onClick={analyze} disabled={!file || loading}>
              {loading ? "Analysing..." : "Analyze Image"}
            </button>
            {file && !loading && (
              <button className="secondary" onClick={reset}>
                Clear
              </button>
            )}
          </div>

          {loading && (
            <div className="spinner-row">
              <span className="spinner" /> Running model (the first request loads it and can take a
              few seconds)
            </div>
          )}

          {error && <p className="error">{error}</p>}

          {result && (
            <div className="vision-result">
              <p className="hint">
                {result.model}. {result.warning}
              </p>
              {result.predictions.map((p) => (
                <div key={p.label} className="pred">
                  <div className="pred-row">
                    <span>{p.label}{p.uncertain ? " · uncertain, review required" : ""}</span>
                    <b>{(p.confidence * 100).toFixed(1)}%</b>
                  </div>
                  <div className="bar">
                    <div style={{ width: `${Math.max(p.confidence * 100, 1)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
