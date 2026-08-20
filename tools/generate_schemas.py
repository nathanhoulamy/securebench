"""Generate checked-in JSON Schemas from the SecureBench v2 models."""

from __future__ import annotations

import json
from pathlib import Path

from securebench.schemas.benchmark import BenchmarkPackManifestV2, BenchmarkRowDocumentV2
from securebench.verification.component_contracts import (
    AdapterManifestV2,
    TrustedHelperContract,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = {
    ROOT / "schemas" / "benchmark-pack-v2.schema.json": BenchmarkPackManifestV2,
    ROOT / "schemas" / "benchmark-row-v2.schema.json": BenchmarkRowDocumentV2,
    ROOT / "schemas" / "adapter-v2.schema.json": AdapterManifestV2,
    ROOT / "schemas" / "trusted-helper-contract-v1.schema.json": TrustedHelperContract,
}


def main() -> None:
    for path, model in OUTPUTS.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://securebench.dev/schemas/{path.name}"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
