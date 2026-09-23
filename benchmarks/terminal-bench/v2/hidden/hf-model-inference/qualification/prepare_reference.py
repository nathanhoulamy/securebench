"""Build the bounded reference Candidate in a disposable networked container."""

from pathlib import Path
import shutil

from transformers import AutoModelForSequenceClassification, AutoTokenizer


MODEL = "distilbert-base-uncased-finetuned-sst-2-english"
REVISION = "714eb0fa89d2f80546fda750413ed43d93601a13"
MODEL_PATH = Path("/app/model_cache/sentiment_model")


model = AutoModelForSequenceClassification.from_pretrained(MODEL, revision=REVISION)
# The public instruction just says "download the model and save it"; this is
# the plain upstream-default export an ordinary Agent produces: the default
# *fast* tokenizer (which also writes tokenizer.json/special_tokens_map.json),
# with no post-save cleanup. The row's candidate bounds are raised by tester
# policy (benchmarks/terminal-bench/tester-*.yaml -> capture.max_candidate_bytes,
# see docs/benchmark-conversions/TerminalBench/hf-model-inference.md, "Review
# correction") specifically so this default six-file, 268,777,554-byte export
# fits with headroom.
tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
model.save_pretrained(MODEL_PATH)
tokenizer.save_pretrained(MODEL_PATH)

shutil.copyfile("/qualification/reference.py", "/app/app.py")
Path("/app/hf_service_dependencies").mkdir()
