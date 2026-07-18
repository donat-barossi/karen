"""
Caricamento configurazione Karen con profili piattaforma.

Ordine di merge (ultimo vince):
  config/base.yaml → config/{profile}.yaml → config.yaml (override locale)
"""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

import yaml


def default_profile() -> str:
    env = os.environ.get("KAREN_PROFILE")
    if env:
        return env
    return "jetson" if platform.machine() == "aarch64" else "topgro"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(
    host_dir: Path | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    root = host_dir or Path(__file__).resolve().parent.parent
    profile = profile or default_profile()

    cfg: dict[str, Any] = {}
    config_dir = root / "config"

    for name in ("base.yaml", f"{profile}.yaml"):
        path = config_dir / name
        if not path.exists():
            continue
        with open(path) as f:
            cfg = deep_merge(cfg, yaml.safe_load(f) or {})

    for local_name in ("config.local.yaml", "config.yaml"):
        local_path = root / local_name
        if not local_path.exists():
            continue
        with open(local_path) as f:
            cfg = deep_merge(cfg, yaml.safe_load(f) or {})

    if not cfg:
        example = root / "config.yaml.example"
        raise FileNotFoundError(
            f"Nessuna config trovata in {config_dir} (profilo '{profile}'). "
            f"Crea config/base.yaml + config/{profile}.yaml oppure copia {example} → config.yaml"
        )

    cfg.setdefault("platform", profile)
    return cfg
