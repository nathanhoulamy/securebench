"""Reviewed restartable form of the upstream Flask reference."""

from flask import Flask, jsonify, request
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


app = Flask(__name__)
MODEL_PATH = "/app/model_cache/sentiment_model"
model = AutoModelForSequenceClassification.from_pretrained(
    MODEL_PATH,
    local_files_only=True,
)
tokenizer = AutoTokenizer.from_pretrained(
    MODEL_PATH,
    local_files_only=True,
    use_fast=False,
)


@app.post("/sentiment")
def sentiment():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        return jsonify({"error": "Please provide a text string"}), 400
    text = data["text"]
    inputs = tokenizer(
        text,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=512,
    )
    with torch.no_grad():
        probabilities = torch.softmax(model(**inputs).logits, dim=-1)[0].tolist()
    return jsonify(
        {
            "text": text,
            "sentiment": "positive" if probabilities[1] > probabilities[0] else "negative",
            "confidence": {
                "positive": float(probabilities[1]),
                "negative": float(probabilities[0]),
            },
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
