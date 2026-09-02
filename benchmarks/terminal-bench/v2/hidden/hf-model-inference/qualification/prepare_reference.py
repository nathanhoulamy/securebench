"""Build the bounded reference Candidate in a disposable networked container."""

from pathlib import Path
import shutil

from transformers import AutoModelForSequenceClassification, AutoTokenizer


MODEL = "distilbert-base-uncased-finetuned-sst-2-english"
REVISION = "714eb0fa89d2f80546fda750413ed43d93601a13"
MODEL_PATH = Path("/app/model_cache/sentiment_model")


model = AutoModelForSequenceClassification.from_pretrained(MODEL, revision=REVISION)
tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
model.save_pretrained(MODEL_PATH)
tokenizer.save_pretrained(MODEL_PATH)
for optional_name in ("tokenizer.json", "special_tokens_map.json"):
    (MODEL_PATH / optional_name).unlink()

shutil.copyfile("/qualification/reference.py", "/app/app.py")
Path("/app/hf_service_dependencies").mkdir()
