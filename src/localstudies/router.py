"""Roteador de modelos entre nós LM Studio / LM Link por papel usando `config/fleet_models.json`."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_FLEET_CONFIG_PATH = Path("config/fleet_models.json")


@dataclass(frozen=True)
class RouterConfig:
    base_url: str
    api_key: str
    primary_model: str
    vision_model: str
    embedding_model: str

    @classmethod
    def from_env(cls) -> "RouterConfig":
        return cls(
            base_url=os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/"),
            api_key=os.getenv("LMSTUDIO_API_KEY", "lm-studio"),
            primary_model=os.getenv("LM_PRIMARY_MODEL", "qwen3-14b"),
            vision_model=os.getenv("LM_VISION_MODEL", "qwen2.5-vl-7b-instruct"),
            embedding_model=os.getenv("LM_EMBEDDING_MODEL", "text-embedding-bge-m3"),
        )


def load_fleet_config(config_path: Path | str = DEFAULT_FLEET_CONFIG_PATH) -> dict[str, Any]:
    """Carrega o arquivo declarativo `config/fleet_models.json`."""
    path = Path(config_path)
    if not path.exists():
        return {"nodes": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def get_role_profile(
    role: str = "coder_3d",
    config_path: Path | str = DEFAULT_FLEET_CONFIG_PATH,
) -> dict[str, Any] | None:
    """Retorna o perfil da máquina/modelo associado ao papel (`coder_3d`, `dwg_planner`, `vision_audit`, `embeddings_rag`)."""
    role_aliases = {
        "primary": "coder_3d",
        "coder": "coder_3d",
        "planner": "dwg_planner",
        "vision": "vision_audit",
        "embedding": "embeddings_rag",
    }
    target_role = role_aliases.get(role, role)
    fleet = load_fleet_config(config_path)
    for node_key, node_data in fleet.get("nodes", {}).items():
        if node_data.get("role") == target_role or node_key == role:
            return {"node_key": node_key, **node_data}
    return None


def list_api_models(base_url: str | None = None, timeout: float = 5.0) -> list[str]:
    """Consulta os modelos atualmente expostos na API OpenAI-compatible do LM Studio."""
    url = f"{(base_url or os.getenv('LMSTUDIO_BASE_URL', 'http://localhost:1234/v1')).rstrip('/')}/models"
    resp = httpx.get(url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return [item["id"] for item in data if "id" in item]


def resolve_model_for_role(
    role: str = "primary",
    config: RouterConfig | None = None,
    available_models: list[str] | None = None,
    config_path: Path | str = DEFAULT_FLEET_CONFIG_PATH,
) -> str:
    """Resolve o melhor modelo para o papel solicitado consultando a frota e os modelos disponíveis na API."""
    cfg = config or RouterConfig.from_env()
    profile = get_role_profile(role, config_path=config_path)

    candidates: list[str] = [role]
    if profile:
        role_id = profile.get("role", "")
        if role_id and role_id not in candidates:
            candidates.append(role_id)
        rec = profile.get("recommended_model", "")
        if rec and rec != "none":
            candidates.append(rec.split("@")[0].split("/")[-1])
            candidates.append(rec.split("@")[0])
        fb = profile.get("fallback_model", "")
        if fb:
            candidates.append(fb)

    env_desired = {
        "primary": cfg.primary_model,
        "coder": cfg.primary_model,
        "coder_3d": cfg.primary_model,
        "vision": cfg.vision_model,
        "vision_audit": cfg.vision_model,
        "embedding": cfg.embedding_model,
        "embeddings_rag": cfg.embedding_model,
    }.get(role, cfg.primary_model)
    if env_desired not in candidates:
        candidates.insert(0, env_desired)

    if available_models is None:
        try:
            available_models = list_api_models(cfg.base_url)
        except Exception:
            return candidates[0]

    if not available_models:
        return candidates[0]

    for cand in candidates:
        if cand in available_models:
            return cand
        cand_lower = cand.lower()
        for avail in available_models:
            if cand_lower in avail.lower():
                return avail

    return available_models[0]
