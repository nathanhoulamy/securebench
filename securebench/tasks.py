"""Compiled benchmark task passed between SecureBench components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from securebench.resources import Component, ResourceBundle
from securebench.schemas.benchmark import EnvironmentSpec, PublicAsset, VerificationSpec


@dataclass(frozen=True)
class BenchmarkTask:
    """One fully validated and filesystem-resolved v2 benchmark row.

    Security-authoritative fields stay typed and top-level. ``metadata`` is
    provenance-only: it is never consulted for routing, capture, or scoring.
    """

    id: str
    benchmark_id: str
    family: str
    input: dict[str, object]
    assets: tuple[PublicAsset, ...]
    environment: EnvironmentSpec
    verification: VerificationSpec
    metadata: dict[str, object]
    resources: ResourceBundle
    pack_root: Path
    manifest_path: Path
    manifest_digest: str
    row_digest: str

    def agent_payload(self) -> dict[str, object]:
        """Return only the author-declared prompt/input object."""
        return dict(self.input)

    def view_for(self, component: Component):
        return self.resources.view_for(component)

    def resource_summary(self) -> list[dict[str, object]]:
        return self.resources.summary()
