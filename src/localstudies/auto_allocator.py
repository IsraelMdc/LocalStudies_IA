"""Alocador automático de modelos na frota LM Link baseado em `lms ls --json`, `lms ps --json` e orçamento de VRAM."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from localstudies.lms_tools import run_lms
from localstudies.router import DEFAULT_FLEET_CONFIG_PATH, load_fleet_config


@dataclass(frozen=True)
class AllocationDecision:
    role: str
    node_key: str
    host_label: str
    device_id: str
    model_key: str
    indexed_identifier: str
    size_gb: float
    vram_budget_gb: float
    context_length: int
    identifier_alias: str
    already_loaded: bool
    note: str = ""


def list_downloaded_models_json() -> list[dict[str, Any]]:
    """Retorna a lista estruturada de `lms ls --json`."""
    res = run_lms(["ls", "--json"], timeout=30)
    if not res.ok or not res.stdout.strip():
        return []
    try:
        data = json.loads(res.stdout)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def list_loaded_models_json() -> list[dict[str, Any]]:
    """Retorna a lista estruturada de `lms ps --json`."""
    res = run_lms(["ps", "--json"], timeout=20)
    if not res.ok or not res.stdout.strip():
        return []
    try:
        data = json.loads(res.stdout)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _bytes_to_gb(size_bytes: int | float) -> float:
    return round(float(size_bytes) / 1_000_000_000, 2)


def _select_best_candidate(
    models_on_device: list[dict[str, Any]],
    vram_gb: float,
    kv_reserve_gb: float,
    model_type: str = "llm",
    require_vision: bool = False,
    preferred_substrings: list[str] | None = None,
) -> dict[str, Any] | None:
    """Escolhe o melhor modelo que cabe em `vram_gb - kv_reserve_gb` respeitando tipo, visão e preferência."""
    max_weight_gb = max(0.5, vram_gb - kv_reserve_gb)
    prefs = [p.lower() for p in (preferred_substrings or []) if p]

    valid: list[dict[str, Any]] = []
    for m in models_on_device:
        if m.get("type") != model_type:
            continue
        if require_vision and not m.get("vision", False):
            continue
        size_gb = _bytes_to_gb(m.get("sizeBytes", 0))
        if size_gb <= max_weight_gb:
            valid.append(m)

    if not valid:
        return None

    def _score(item: dict[str, Any]) -> tuple[int, int, float]:
        ident = f"{item.get('modelKey', '')} {item.get('path', '')}".lower()
        pref_rank = 0
        for idx, sub in enumerate(prefs):
            if sub in ident:
                pref_rank = len(prefs) - idx
                break
        tool_bonus = 1 if item.get("trainedForToolUse", False) else 0
        size_gb = _bytes_to_gb(item.get("sizeBytes", 0))
        return (pref_rank, tool_bonus, size_gb)

    valid.sort(key=_score, reverse=True)
    return valid[0]


def compute_allocation_plan(
    downloaded: list[dict[str, Any]] | None = None,
    loaded: list[dict[str, Any]] | None = None,
    config_path: Path | str = DEFAULT_FLEET_CONFIG_PATH,
) -> list[AllocationDecision]:
    """Calcula qual modelo deve rodar em cada servo do LM Link sem estourar a VRAM."""
    all_models = downloaded if downloaded is not None else list_downloaded_models_json()
    active_models = loaded if loaded is not None else list_loaded_models_json()
    fleet = load_fleet_config(config_path)
    nodes = fleet.get("nodes", {})

    loaded_identifiers = {
        str(m.get("identifier") or m.get("indexedModelIdentifier") or m.get("modelKey") or "")
        for m in active_models
    }
    loaded_paths = {str(m.get("path") or m.get("indexedModelIdentifier") or "") for m in active_models}

    by_device: dict[str, list[dict[str, Any]]] = {}
    for m in all_models:
        dev = m.get("deviceIdentifier") or "local"
        by_device.setdefault(dev, []).append(m)

    decisions: list[AllocationDecision] = []

    # 1. Servo 1 (berinjela - 15.6 GB): coder_3d
    berinjela = nodes.get("berinjela", {})
    b_dev = berinjela.get("device_id", "c9d558e8a7f1ab7610cba197267c4d38")
    b_vram = float(berinjela.get("vram_gb", 15.6))
    b_cand = _select_best_candidate(
        by_device.get(b_dev, []),
        vram_gb=b_vram,
        kv_reserve_gb=3.0,
        model_type="llm",
        preferred_substrings=["lmstudio-community/qwen3-14b", "qwen3-14b", "qwen2.5-coder-14b"],
    )
    if b_cand:
        idx_id = str(b_cand.get("indexedModelIdentifier") or b_cand.get("path"))
        decisions.append(
            AllocationDecision(
                role="coder_3d",
                node_key="berinjela",
                host_label=berinjela.get("host_label", "berinjela"),
                device_id=b_dev,
                model_key=str(b_cand.get("modelKey")),
                indexed_identifier=idx_id,
                size_gb=_bytes_to_gb(b_cand.get("sizeBytes", 0)),
                vram_budget_gb=b_vram,
                context_length=int(berinjela.get("context_length", 24576)),
                identifier_alias="coder_3d",
                already_loaded=("coder_3d" in loaded_identifiers or idx_id in loaded_paths),
                note="Modelo principal 14B 100% na VRAM com ~5 GB livres para KV cache (24k tokens).",
            )
        )

    # 2. Servo 2 (nixos_ada - 15.6 GB): dwg_planner
    nixos_ada = nodes.get("nixos_ada", {})
    na_dev = nixos_ada.get("device_id", "8d27c8a9351745605bfede9f7cd6dc07")
    na_vram = float(nixos_ada.get("vram_gb", 15.6))
    na_cand = _select_best_candidate(
        by_device.get(na_dev, []),
        vram_gb=na_vram,
        kv_reserve_gb=2.0,
        model_type="llm",
        preferred_substrings=["qwen3-30b-a3b", "qwen3.8-14b", "qwen3-14b"],
    )
    if na_cand:
        idx_id = str(na_cand.get("indexedModelIdentifier") or na_cand.get("path"))
        decisions.append(
            AllocationDecision(
                role="dwg_planner",
                node_key="nixos_ada",
                host_label=nixos_ada.get("host_label", "nixos (RTX 2000 Ada)"),
                device_id=na_dev,
                model_key=str(na_cand.get("modelKey")),
                indexed_identifier=idx_id,
                size_gb=_bytes_to_gb(na_cand.get("sizeBytes", 0)),
                vram_budget_gb=na_vram,
                context_length=int(nixos_ada.get("context_length", 24576)),
                identifier_alias="dwg_planner",
                already_loaded=("dwg_planner" in loaded_identifiers or idx_id in loaded_paths),
                note="Alocado diretamente no Servo 2 (RTX 2000 Ada).",
            )
        )

    # 3. Servo 3 (nixos_4060 - 7.6 GB): vision_audit
    nixos_4060 = nodes.get("nixos_4060", {})
    n4_dev = nixos_4060.get("device_id", "3a54719e8256bdd028946faa0a585341")
    n4_vram = float(nixos_4060.get("vram_gb", 7.6))
    # Reserva de 0.9 GB garante escolher Q3_K_M (6.51 GB) em vez de Q4_K_M (7.38 GB) na placa de 7.6 GB
    n4_cand = _select_best_candidate(
        by_device.get(n4_dev, []),
        vram_gb=n4_vram,
        kv_reserve_gb=0.9,
        model_type="llm",
        require_vision=True,
        preferred_substrings=["q3_k_m", "qwen2.5-vl-7b", "qwen3.8-vl"],
    )
    if n4_cand:
        idx_id = str(n4_cand.get("indexedModelIdentifier") or n4_cand.get("path"))
        decisions.append(
            AllocationDecision(
                role="vision_audit",
                node_key="nixos_4060",
                host_label=nixos_4060.get("host_label", "nixos (RTX 4060)"),
                device_id=n4_dev,
                model_key=str(n4_cand.get("modelKey")),
                indexed_identifier=idx_id,
                size_gb=_bytes_to_gb(n4_cand.get("sizeBytes", 0)),
                vram_budget_gb=n4_vram,
                context_length=int(nixos_4060.get("context_length", 8192)),
                identifier_alias="vision_audit",
                already_loaded=("vision_audit" in loaded_identifiers or idx_id in loaded_paths),
                note="Selecionada variante que deixa >1 GB livre para imagens e KV cache na RTX 4060.",
            )
        )

    # 4. Servo 4 (nuttec - 7.6 GB): embeddings_rag + fast_triage (rejeita 14B de 8.68 GB > 7.6 GB)
    nuttec = nodes.get("nuttec", {})
    nu_dev = nuttec.get("device_id", "98c80cdab4b745a990b39b3c7662ff27")
    nu_vram = float(nuttec.get("vram_gb", 7.6))
    nu_emb = _select_best_candidate(
        by_device.get(nu_dev, []),
        vram_gb=nu_vram,
        kv_reserve_gb=1.5,
        model_type="embedding",
        preferred_substrings=["bge-m3@q8_0", "bge-m3", "nomic-embed"],
    )
    used_nu_vram = 0.0
    if nu_emb:
        emb_size = _bytes_to_gb(nu_emb.get("sizeBytes", 0))
        used_nu_vram += emb_size
        idx_id = str(nu_emb.get("indexedModelIdentifier") or nu_emb.get("path"))
        decisions.append(
            AllocationDecision(
                role="embeddings_rag",
                node_key="nuttec",
                host_label=nuttec.get("host_label", "nuttec"),
                device_id=nu_dev,
                model_key=str(nu_emb.get("modelKey")),
                indexed_identifier=idx_id,
                size_gb=emb_size,
                vram_budget_gb=nu_vram,
                context_length=2048,
                identifier_alias="embeddings_rag",
                already_loaded=("embeddings_rag" in loaded_identifiers or idx_id in loaded_paths),
                note="Embedding multilíngue BGE-M3 para catálogo Samarco e Cofre Obsidian.",
            )
        )

    nu_llm = _select_best_candidate(
        by_device.get(nu_dev, []),
        vram_gb=nu_vram - used_nu_vram,
        kv_reserve_gb=1.5,
        model_type="llm",
        preferred_substrings=["qwen3-4b", "qwen3.8-4b", "qwen3-8b"],
    )
    if nu_llm:
        idx_id = str(nu_llm.get("indexedModelIdentifier") or nu_llm.get("path"))
        decisions.append(
            AllocationDecision(
                role="fast_triage",
                node_key="nuttec",
                host_label=nuttec.get("host_label", "nuttec"),
                device_id=nu_dev,
                model_key=str(nu_llm.get("modelKey")),
                indexed_identifier=idx_id,
                size_gb=_bytes_to_gb(nu_llm.get("sizeBytes", 0)),
                vram_budget_gb=nu_vram,
                context_length=int(nuttec.get("context_length", 8192)),
                identifier_alias="fast_triage",
                already_loaded=("fast_triage" in loaded_identifiers or idx_id in loaded_paths),
                note="Co-alocado na nuttec junto com BGE-M3 (ignora modelos 14B > 7.6 GB VRAM).",
            )
        )

    return decisions


def apply_allocation_plan(
    roles: list[str] | None = None,
    dry_run: bool = False,
    config_path: Path | str = DEFAULT_FLEET_CONFIG_PATH,
) -> dict[str, Any]:
    """Executa `lms load` para cada decisão do plano de alocação automática."""
    plan = compute_allocation_plan(config_path=config_path)
    target_roles = set(roles) if roles else None

    actions: list[dict[str, Any]] = []
    for dec in plan:
        if target_roles and dec.role not in target_roles:
            continue

        cmd_args = [
            "load",
            dec.model_key,
            "--identifier",
            dec.identifier_alias,
            "--context-length",
            str(dec.context_length),
            "--gpu",
            "max",
            "-y",
        ]
        if dry_run or dec.already_loaded:
            actions.append(
                {
                    "role": dec.role,
                    "node": dec.host_label,
                    "model_key": dec.model_key,
                    "size_gb": dec.size_gb,
                    "status": "already_loaded" if dec.already_loaded else "dry_run",
                    "command": f"lms {' '.join(cmd_args)}",
                    "note": dec.note,
                }
            )
            continue

        # Define o preferred-device antes do load para garantir roteamento correto no LM Link
        run_lms(["link", "set-preferred-device", dec.device_id], timeout=15)
        res = run_lms(cmd_args, timeout=180)
        actions.append(
            {
                "role": dec.role,
                "node": dec.host_label,
                "model_key": dec.model_key,
                "size_gb": dec.size_gb,
                "status": "loaded" if res.ok else "error",
                "command": f"lms {' '.join(cmd_args)}",
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "note": dec.note,
            }
        )

    # Restaura berinjela como preferred-device padrão após carregar a frota
    fleet = load_fleet_config(config_path)
    primary_dev = fleet.get("nodes", {}).get("berinjela", {}).get("device_id")
    if primary_dev and not dry_run:
        run_lms(["link", "set-preferred-device", primary_dev], timeout=15)

    return {
        "ok": all(a["status"] != "error" for a in actions),
        "dry_run": dry_run,
        "plan": [asdict(d) for d in plan],
        "actions": actions,
    }


AUTO_ALLOCATE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "lms_auto_allocate_fleet",
        "description": "Inspeciona automaticamente todas as máquinas do LM Link (`lms ls --json`), filtra os modelos que cabem na VRAM de cada GPU e os carrega nos servos corretos (`berinjela`, `nixos`, `nuttec`).",
        "parameters": {
            "type": "object",
            "properties": {
                "dry_run": {
                    "type": "boolean",
                    "description": "Se true, apenas calcula e mostra o plano de alocação sem carregar na VRAM.",
                },
                "roles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista opcional de papéis específicos para carregar (ex: ['coder_3d', 'vision_audit']). Omita para alocar toda a frota.",
                },
            },
            "required": [],
        },
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Alocador automático de modelos na frota LM Link")
    parser.add_argument("--apply", action="store_true", help="Carrega efetivamente os modelos nos servos do LM Link.")
    parser.add_argument("--role", action="append", help="Filtra por papel específico (ex: --role coder_3d).")
    args = parser.parse_args()

    result = apply_allocation_plan(roles=args.role, dry_run=not args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
