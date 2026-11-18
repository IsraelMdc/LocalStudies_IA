"""Wrappers seguros da CLI `lms` expostos como OpenAI Function Calling tools."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from localstudies.router import get_role_profile


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    command: list[str]
    stdout: str
    stderr: str
    returncode: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "command": " ".join(self.command),
                "returncode": self.returncode,
                "stdout": self.stdout.strip(),
                "stderr": self.stderr.strip(),
            },
            ensure_ascii=False,
        )


def _resolve_lms_bin() -> str:
    found = shutil.which("lms")
    if found:
        return found
    return r"C:\Users\israe.MAGALHÃES_NOTE\.lmstudio\bin\lms.exe"


def run_lms(args: list[str], timeout: int = 30) -> CommandResult:
    """Executa um subcomando `lms` de forma segura (sem shell=True)."""
    cmd = [_resolve_lms_bin(), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return CommandResult(
            ok=proc.returncode == 0,
            command=cmd,
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            ok=False,
            command=cmd,
            stdout="",
            stderr=f"Executável lms não encontrado: {exc}",
            returncode=127,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            ok=False,
            command=cmd,
            stdout="",
            stderr=f"Timeout após {timeout}s executando {' '.join(cmd)}",
            returncode=124,
        )


def lms_link_status() -> str:
    return run_lms(["link", "status"]).to_json()


def lms_server_status() -> str:
    return run_lms(["server", "status"]).to_json()


def lms_list_local_models() -> str:
    return run_lms(["ls"]).to_json()


def lms_list_loaded() -> str:
    return run_lms(["ps"]).to_json()


def lms_load_model(
    model: str,
    context_length: int | None = None,
    gpu_offload: str | None = None,
    yes: bool = True,
) -> str:
    args = ["load", model]
    if context_length is not None:
        args.extend(["--context-length", str(context_length)])
    if gpu_offload is not None:
        args.extend(["--gpu", gpu_offload])
    if yes:
        args.append("-y")
    return run_lms(args, timeout=120).to_json()


def lms_unload_model(model: str | None = None) -> str:
    args = ["unload", model] if model else ["unload", "--all"]
    return run_lms(args, timeout=30).to_json()


def lms_set_preferred_device(device: str) -> str:
    return run_lms(["link", "set-preferred-device", device]).to_json()


def lms_apply_role_profile(role: str = "coder_3d", use_fallback: bool = False) -> str:
    """Aplica o perfil de máquina e modelo de `config/fleet_models.json` para a tarefa desejada."""
    profile = get_role_profile(role)
    if not profile:
        return json.dumps({"ok": False, "error": f"Papel '{role}' não encontrado em config/fleet_models.json."})

    device_id = profile.get("device_id", "")
    model = profile.get("fallback_model") if use_fallback else profile.get("recommended_model")
    if not model or model == "none":
        model = profile.get("fallback_model", "")

    steps: list[dict[str, Any]] = []
    if device_id and device_id != "local":
        dev_res = json.loads(lms_set_preferred_device(device_id))
        steps.append({"step": "set_preferred_device", "device": device_id, "result": dev_res})

    load_res = json.loads(
        lms_load_model(
            model=str(model),
            context_length=int(profile.get("context_length", 16384)),
            gpu_offload=str(profile.get("gpu_offload", "max")),
        )
    )
    steps.append({"step": "load_model", "model": model, "result": load_res})
    return json.dumps({"ok": load_res.get("ok", False), "profile": profile, "steps": steps}, ensure_ascii=False)


MUTATING_LMS_TOOLS = {
    "lms_load_model",
    "lms_unload_model",
    "lms_set_preferred_device",
    "lms_apply_role_profile",
}


LMS_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lms_link_status",
            "description": "Mostra o status do LM Link e quais dispositivos remotos (servos) estão conectados.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lms_server_status",
            "description": "Verifica se o servidor HTTP local do LM Studio está ativo.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lms_list_local_models",
            "description": "Lista os modelos baixados disponíveis para carregar no LM Studio.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lms_list_loaded",
            "description": "Lista os modelos atualmente carregados na memória/VRAM e em qual máquina estão.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lms_load_model",
            "description": "Carrega um modelo no dispositivo preferido do LM Link (ex: berinjela).",
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Identificador ou nome do modelo."},
                    "context_length": {
                        "type": "integer",
                        "description": "Tamanho de contexto desejado (ex: 16384 ou 24576).",
                    },
                    "gpu_offload": {
                        "type": "string",
                        "description": "Fração de offload para GPU (ex: 'max', '0.8').",
                    },
                },
                "required": ["model"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lms_unload_model",
            "description": "Descarrega um modelo específico ou todos os modelos carregados para liberar VRAM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "Nome do modelo a descarregar. Omita para descarregar todos.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lms_set_preferred_device",
            "description": "Define qual máquina conectada no LM Link será o dispositivo preferido para carregar modelos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {
                        "type": "string",
                        "description": "Nome ou Device ID do dispositivo no LM Link (ex: berinjela).",
                    }
                },
                "required": ["device"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lms_apply_role_profile",
            "description": "Configura automaticamente no LM Link a máquina e o modelo ideais de `config/fleet_models.json` para a tarefa ('coder_3d', 'dwg_planner', 'vision_audit', 'embeddings_rag').",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "Papel da tarefa: 'coder_3d', 'dwg_planner', 'vision_audit' ou 'embeddings_rag'.",
                    },
                    "use_fallback": {
                        "type": "boolean",
                        "description": "Se true, carrega o fallback_model já instalado caso o recommended_model ainda não tenha sido baixado.",
                    },
                },
                "required": ["role"],
            },
        },
    },
]


LMS_TOOL_DISPATCH: dict[str, Callable[..., str]] = {
    "lms_link_status": lms_link_status,
    "lms_server_status": lms_server_status,
    "lms_list_local_models": lms_list_local_models,
    "lms_list_loaded": lms_list_loaded,
    "lms_load_model": lms_load_model,
    "lms_unload_model": lms_unload_model,
    "lms_set_preferred_device": lms_set_preferred_device,
    "lms_apply_role_profile": lms_apply_role_profile,
}
