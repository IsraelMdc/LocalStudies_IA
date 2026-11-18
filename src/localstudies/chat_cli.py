"""Terminal interativo para conversar com o modelo e gerenciar LM Studio, LM Link, Cofre Obsidian, Samarco CAD e Blender MCP."""

from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import AsyncExitStack
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from localstudies.auto_allocator import AUTO_ALLOCATE_SCHEMA, apply_allocation_plan
from localstudies.blender_part_builder import PART_BUILDER_SCHEMA, generate_detailed_part_script
from localstudies.dwg_pipeline import CAD_INSPECT_SCHEMA, inspect_cad_file
from localstudies.dxf_to_blender import (
    BUILD_CAD_3D_SCHEMA,
    build_scene_bpy_script,
    extract_full_geometry,
)
from localstudies.lms_tools import (
    LMS_TOOL_DISPATCH,
    LMS_TOOL_SCHEMAS,
    MUTATING_LMS_TOOLS,
    lms_link_status,
    lms_list_loaded,
)
from localstudies.obsidian_vault import (
    OBSIDIAN_TOOL_SCHEMAS,
    ingest_dxf_to_vault,
    init_vault,
    read_vault_note,
    update_part_blender_status,
)
from localstudies.router import RouterConfig, list_api_models, load_fleet_config, resolve_model_for_role
from localstudies.samarco_index import SAMARCO_SEARCH_SCHEMA, search_catalog

console = Console()

SYSTEM_PROMPT = """Você é o assistente de engenharia 3D do repositório LocalStudies_IA (arquitetura Mestre e Servos via LM Link).
Suas responsabilidades obrigatórias:
1. GERENCIAMENTO E ALOCAÇÃO AUTOMÁTICA LM STUDIO / FROTA: Você pode consultar, configurar e alocar automaticamente os modelos nas 5 máquinas do LM Link usando `lms_auto_allocate_fleet`, `lms_apply_role_profile` e demais ferramentas `lms_*`.
2. ANTI-ALUCINAÇÃO (COFRE OBSIDIAN): Sempre consulte/ingira o arquivo CAD no Cofre Obsidian (`obsidian_ingest_cad` e `obsidian_read_note`) como Fonte da Verdade (Ground Truth) antes de modelar, e atualize o status com `obsidian_update_part_status` após criar cada peça.
3. DETALHAMENTO MÁXIMO NO BLENDER: Para gerar a cena 3D completa de um .dwg/.dxf no Blender (e salvar `.blend`, `.glb` e `_preview.png` em `exports/`), SEMPRE chame `build_cad_3d_in_blender` primeiro! Para adicionar ou ajustar peças avulsas com Custom Properties completas (`dwg_source`, `dwg_handle`, `dwg_layer`, `part_tag`, `material_spec`, `dimensions_m`, `cad_attribs_json`, `nearby_notes`), use `generate_detailed_part_script`. IMPORTANTE: Sempre posicione peças perto da origem `(0, 0, 0)`.
Responda sempre em português claro e objetivo."""


def _print_fleet_table() -> None:
    fleet = load_fleet_config()
    table = Table(title="Alocação de Modelos por Máquina (config/fleet_models.json)")
    table.add_column("Nó", style="cyan", no_wrap=True)
    table.add_column("GPU / VRAM", style="magenta")
    table.add_column("Papel", style="green")
    table.add_column("Modelo Recomendado", style="yellow")
    table.add_column("Fallback Instalado", style="white")
    table.add_column("Contexto", justify="right")

    for key, info in fleet.get("nodes", {}).items():
        table.add_row(
            f"{info.get('host_label', key)} ({str(info.get('device_id', ''))[:8]})",
            f"{info.get('gpu')} ({info.get('vram_gb')} GB)",
            str(info.get("role")),
            str(info.get("recommended_model")),
            str(info.get("fallback_model")),
            str(info.get("context_length")),
        )
    console.print(table)


def _print_allocation_result(result: dict[str, Any]) -> None:
    table = Table(title="Resultado da Alocação Automática de Modelos (LM Link)")
    table.add_column("Papel", style="green")
    table.add_column("Nó", style="cyan")
    table.add_column("Modelo", style="yellow")
    table.add_column("Tamanho", justify="right")
    table.add_column("Status", style="magenta")
    for act in result.get("actions", []):
        table.add_row(
            str(act.get("role")),
            str(act.get("node")),
            str(act.get("model_key")),
            f"{act.get('size_gb')} GB",
            str(act.get("status")),
        )
    console.print(table)


def _mcp_tools_to_openai(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in mcp_tools:
        schema = (
            getattr(tool, "input_schema", None)
            or getattr(tool, "inputSchema", None)
            or {"type": "object", "properties": {}}
        )
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": f"blender__{tool.name}",
                    "description": tool.description or f"Ferramenta Blender MCP: {tool.name}",
                    "parameters": schema,
                },
            }
        )
    return converted


async def _execute_tool(
    name: str,
    raw_args: str,
    auto_approve: bool,
    mcp_session: ClientSession | None,
) -> str:
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        args = {}

    if name == "lms_auto_allocate_fleet":
        dry_run = bool(args.get("dry_run", False))
        if not dry_run and not auto_approve:
            console.print(f"[yellow]Alocação automática da frota solicitada:[/yellow] {args}")
            ans = console.input("[bold yellow]Executar alocação nos servos? [s/N]: [/bold yellow]").strip().lower()
            if ans not in {"s", "sim", "y", "yes"}:
                return json.dumps({"ok": False, "cancelled_by_user": True})
        return json.dumps(
            apply_allocation_plan(roles=args.get("roles"), dry_run=dry_run),
            ensure_ascii=False,
        )

    if name in LMS_TOOL_DISPATCH:
        if name in MUTATING_LMS_TOOLS and not auto_approve:
            console.print(f"[yellow]Ação LM Studio solicitada:[/yellow] {name}({args})")
            ans = console.input("[bold yellow]Executar? [s/N]: [/bold yellow]").strip().lower()
            if ans not in {"s", "sim", "y", "yes"}:
                return json.dumps({"ok": False, "cancelled_by_user": True})
        return LMS_TOOL_DISPATCH[name](**args)

    if name == "samarco_search_files":
        results = search_catalog(**args)
        return json.dumps(results, ensure_ascii=False)

    if name == "inspect_cad_file":
        try:
            return inspect_cad_file(**args)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    if name == "build_cad_3d_in_blender":
        try:
            payload = extract_full_geometry(
                args["file_path"],
                extrude_height=float(args.get("extrude_height", 1.5)),
                beam_width=float(args.get("beam_width", 0.08)),
            )
            script, outputs = build_scene_bpy_script(payload, export_dir=args.get("export_dir", "exports"))
            if mcp_session is not None:
                res = await mcp_session.call_tool("execute_blender_code", arguments={"code": script})
                blender_out = "\n".join(getattr(c, "text", str(c)) for c in res.content)
                return json.dumps({"ok": True, "mode": "blender_mcp", "outputs": outputs, "blender_output": blender_out[-800:]}, ensure_ascii=False)
            return json.dumps({"ok": False, "error": "Blender MCP não conectado (inicie com --blender)."}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    if name == "generate_detailed_part_script":
        try:
            return generate_detailed_part_script(**args)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    if name == "obsidian_ingest_cad":
        try:
            return json.dumps(ingest_dxf_to_vault(**args), ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    if name == "obsidian_read_note":
        return read_vault_note(**args)

    if name == "obsidian_update_part_status":
        return update_part_blender_status(**args)

    if name.startswith("blender__") and mcp_session is not None:
        real_name = name.removeprefix("blender__")
        result = await mcp_session.call_tool(real_name, arguments=args)
        parts = [getattr(c, "text", str(c)) for c in result.content]
        return "\n".join(parts)

    return json.dumps({"ok": False, "error": f"Ferramenta desconhecida ou desconectada: {name}"})


async def _run_chat(args: argparse.Namespace) -> None:
    load_dotenv()
    vault_path = init_vault()
    cfg = RouterConfig.from_env()
    client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
    auto_approve = args.auto_approve

    if args.auto_allocate:
        console.print("[cyan]Executando alocação automática de modelos nos servos do LM Link...[/cyan]")
        alloc_res = apply_allocation_plan(dry_run=False)
        _print_allocation_result(alloc_res)

    model = args.model or resolve_model_for_role("coder_3d", cfg)

    console.print(
        Panel.fit(
            f"[bold cyan]LocalStudies_IA — Chat, Frota LM Link, Cofre Obsidian & Blender MCP[/bold cyan]\n"
            f"API: [green]{cfg.base_url}[/green] | Modelo ativo: [yellow]{model}[/yellow]\n"
            f"Cofre Obsidian: [magenta]{vault_path}[/magenta]\n"
            f"Comandos: [bold]/allocate[/bold], [bold]/fleet[/bold], [bold]/vault[/bold], [bold]/status[/bold], [bold]/models[/bold], [bold]/auto[/bold], [bold]/reset[/bold], [bold]/sair[/bold]",
            border_style="cyan",
        )
    )

    async with AsyncExitStack() as stack:
        mcp_session: ClientSession | None = None
        blender_tools: list[dict[str, Any]] = []

        if args.blender:
            console.print("[cyan]Conectando ao blender-mcp (uvx blender-mcp)...[/cyan]")
            server_params = StdioServerParameters(command="uvx", args=["blender-mcp"])
            read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
            mcp_session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await mcp_session.initialize()
            listed = await mcp_session.list_tools()
            blender_tools = _mcp_tools_to_openai(listed.tools)
            console.print(f"[green]Blender MCP conectado ({len(blender_tools)} ferramentas).[/green]")

        tools = [
            AUTO_ALLOCATE_SCHEMA,
            *LMS_TOOL_SCHEMAS,
            SAMARCO_SEARCH_SCHEMA,
            CAD_INSPECT_SCHEMA,
            BUILD_CAD_3D_SCHEMA,
            PART_BUILDER_SCHEMA,
            *OBSIDIAN_TOOL_SCHEMAS,
            *blender_tools,
        ]
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        while True:
            try:
                user_text = console.input("\n[bold green]Você>[/bold green] ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_text:
                continue
            if user_text in {"/sair", "/exit", "/quit"}:
                break
            if user_text == "/reset":
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                console.print("[dim]Histórico limpo (memória preservada no Cofre Obsidian).[/dim]")
                continue
            if user_text == "/auto":
                auto_approve = not auto_approve
                console.print(f"[yellow]Auto-approve lms: {auto_approve}[/yellow]")
                continue
            if user_text == "/allocate":
                console.print("[cyan]Alocando modelos automaticamente nos servos do LM Link...[/cyan]")
                alloc_res = apply_allocation_plan(dry_run=False)
                _print_allocation_result(alloc_res)
                model = args.model or resolve_model_for_role("coder_3d", cfg)
                console.print(f"[green]Modelo ativo para chat:[/green] {model}")
                continue
            if user_text == "/fleet":
                _print_fleet_table()
                continue
            if user_text == "/vault":
                console.print(f"[magenta]Cofre Obsidian pronto em:[/magenta] {vault_path}")
                for sub in sorted(vault_path.rglob("*.md"))[:20]:
                    console.print(f"  - {sub.relative_to(vault_path).as_posix()}")
                continue
            if user_text == "/status":
                console.print(lms_link_status())
                console.print(lms_list_loaded())
                continue
            if user_text == "/models":
                try:
                    console.print({"api_models": list_api_models(cfg.base_url)})
                except Exception as exc:
                    console.print(f"[red]Erro consultando API ({cfg.base_url}): {exc}[/red]")
                continue

            messages.append({"role": "user", "content": user_text})

            while True:
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=tools,
                        temperature=0.2,
                    )
                except Exception as exc:
                    console.print(
                        f"[red]Falha ao chamar LM Studio em {cfg.base_url}:[/red] {exc}\n"
                        "[dim]Dica: digite `/allocate` para carregar os modelos nos servos ou rode `lms server start --port 1234`.[/dim]"
                    )
                    messages.pop()
                    break

                msg = response.choices[0].message
                tool_calls = msg.tool_calls or []

                assistant_entry: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
                if tool_calls:
                    assistant_entry["tool_calls"] = [tc.model_dump() for tc in tool_calls]
                messages.append(assistant_entry)

                if not tool_calls:
                    if msg.content:
                        console.print(Markdown(msg.content))
                    break

                for tc in tool_calls:
                    console.print(f"[dim]→ tool: {tc.function.name}[/dim]")
                    output = await _execute_tool(
                        tc.function.name,
                        tc.function.arguments,
                        auto_approve=auto_approve,
                        mcp_session=mcp_session,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": output,
                        }
                    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat CLI para gerenciar LM Studio, LM Link, Cofre Obsidian e Blender MCP")
    parser.add_argument("--model", help="Modelo específico no LM Studio (sobrescreve resolução automática da frota).")
    parser.add_argument("--blender", action="store_true", help="Conecta também ao servidor stdio `uvx blender-mcp`.")
    parser.add_argument("--auto-allocate", action="store_true", help="Aloca e carrega automaticamente os modelos nos servos ao iniciar.")
    parser.add_argument("--auto-approve", action="store_true", help="Executa comandos mutáveis do `lms` sem pedir confirmação.")
    parsed = parser.parse_args()
    asyncio.run(_run_chat(parsed))


if __name__ == "__main__":
    main()
