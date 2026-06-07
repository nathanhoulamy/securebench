"""Preflight helpers for Berkeley adversarial run configs."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.errors import ConfigError
from securebench.harnesses.shared import container_image_for_task

from berkeley.run import BERKELEY_ROOT, load_berkeley_config


DEFAULT_CONFIG_GLOB = "realism-*.yaml"


def required_images_for_configs(config_paths: list[str | Path]) -> list[str]:
    """Return unique benchmark container images required by Berkeley configs."""
    images: list[str] = []
    seen: set[str] = set()
    for config_path in config_paths:
        config = load_berkeley_config(config_path)
        pack = load_benchmark_pack(config.benchmark.manifest, config.benchmark.tasks)
        for task in compile_benchmark_pack(pack, limit=config.benchmark.limit):
            image = container_image_for_task(task)
            if image not in seen:
                seen.add(image)
                images.append(image)
    return images


def missing_images(images: list[str]) -> list[str]:
    """Return images that are not available to the local Docker daemon."""
    missing = []
    for image in images:
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise ConfigError(f"failed to inspect Docker images: {exc}") from exc
        if result.returncode != 0:
            missing.append(image)
    return missing


def default_realism_configs() -> list[Path]:
    return sorted((BERKELEY_ROOT / "configs").glob(DEFAULT_CONFIG_GLOB))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Docker images required by Berkeley configs")
    parser.add_argument("configs", nargs="*", help="Berkeley config paths; defaults to berkeley/configs/realism-*.yaml")
    parser.add_argument("--json", action="store_true", help="Write machine-readable JSON")
    args = parser.parse_args(argv)

    config_paths = [Path(path) for path in args.configs] if args.configs else default_realism_configs()
    try:
        images = required_images_for_configs(config_paths)
        missing = missing_images(images)
    except ConfigError as exc:
        print(f"berkeley preflight failed: {exc}")
        return 2

    if args.json:
        print(json.dumps({"configs": [str(path) for path in config_paths], "images": images, "missing": missing}, indent=2))
    else:
        print("Berkeley realism image preflight")
        for image in images:
            status = "missing" if image in missing else "available"
            print(f"- {status}: {image}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
