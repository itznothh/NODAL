import os
from pathlib import Path

import joblib
from dotenv import load_dotenv
from pymongo import MongoClient
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline

load_dotenv()
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
docs = list(client["nodal"]["complaints"].find({"category": {"$ne": "unclassified"}}))

texts = [d["description"] for d in docs]
labels = [d["category"] for d in docs]

X_train, X_test, y_train, y_test = train_test_split(
    texts, labels, test_size=0.25, random_state=42, stratify=labels
)

model = make_pipeline(
    TfidfVectorizer(ngram_range=(1, 2), lowercase=True),
    LogisticRegression(max_iter=1000),
)
model.fit(X_train, y_train)

print(classification_report(y_test, model.predict(X_test)))

# Retrain on everything before saving
model.fit(texts, labels)
out = Path(__file__).resolve().parent / "classifier.joblib"
joblib.dump(model, out)
print("Saved model to", out)