"""Gerenciador do Cofre Obsidian dedicado (`vault_samarco/`) como memória persistente anti-alucinação."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from localstudies.dwg_pipeline import convert_dwg_to_dxf, summarize_dxf

load_dotenv()

DEFAULT_VAULT_DIR = Path("vault_samarco")


def get_vault_dir(vault_dir: Path | str | None = None) -> Path:
    if vault_dir is not None:
        return Path(vault_dir).resolve()
    return Path(os.getenv("OBSIDIAN_VAULT_DIR", str(DEFAULT_VAULT_DIR))).resolve()

VAULT_FOLDERS = (
    "00_Indice_e_Regras",
    "01_Pranchas_DWG",
    "02_Pecas_e_Blocos",
    "03_Logs_Modelagem",
)


def _safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "_-." else "_" for c in name.strip())
    return cleaned or "unnamed"


def init_vault(vault_dir: Path | str | None = None) -> Path:
    """Inicializa a estrutura de pastas e notas base do Cofre Obsidian para o projeto Samarco."""
    root = get_vault_dir(vault_dir)
    for folder in VAULT_FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)

    home_note = root / "00_Indice_e_Regras" / "00_Home_Samarco.md"
    if not home_note.exists():
        home_note.write_text(
            """---
type: vault_index
project: LocalStudies_IA_Samarco
topology: master_servos_lm_link
---

# Cofre de Engenharia Samarco — Fonte da Verdade (Anti-Alucinação)

Este cofre Obsidian armazena os **fatos geométricos imutáveis** extraídos dos arquivos `.dwg`/`.dxf` da Samarco pelo `ezdxf` e o **estado de modelagem 3D no Blender**.

## Estrutura
- [[Regras_Layers_e_Materiais]] — Convenção de layers CAD, cores ACI, materiais PBR e Custom Properties obrigatórias no Blender.
- [[Frota_LM_Link]] — Divisão de tarefas entre `Magalhães_note` e os 4 servos (`berinjela`, `nixos_ada`, `nixos_4060`, `nuttec`).
- `01_Pranchas_DWG/` — Uma nota por prancha DWG inspecionada, com YAML Frontmatter travado.
- `02_Pecas_e_Blocos/` — Notas individuais por peça/equipamento (`INSERT`/bloco) com TAG, `handle` e `blender_object_name`.
- `03_Logs_Modelagem/` — Registro cronológico de execuções e auditorias visuais.
""",
            encoding="utf-8",
        )

    rules_note = root / "00_Indice_e_Regras" / "Regras_Layers_e_Materiais.md"
    if not rules_note.exists():
        rules_note.write_text(
            """---
type: engineering_rules
immutable_ground_truth: true
---

# Regras de Engenharia, Metadados e Detalhamento 3D no Blender

1. **Proibido inventar medidas:** Toda coordenada, altura ou dimensão deve vir do YAML Frontmatter da prancha em `01_Pranchas_DWG/` ou da peça em `02_Pecas_e_Blocos/`.
2. **Custom Properties obrigatórias em cada objeto Blender (`obj["..."]`):**
   - `dwg_source`, `dwg_handle`, `dwg_layer`, `dwg_type`, `part_tag`, `material_spec`, `dimensions_m`, `elevation_m`, `cad_attribs_json`, `nearby_notes`.
3. **Detalhamento visual obrigatório:**
   - Hierarquia de `Collections`: `Prancha -> Sistema -> Layer`.
   - Material PBR `Principled BSDF` baseado na cor ACI da layer e categoria física (`steel`, `concrete`, `piping`, `equipment`).
   - Modificadores `Bevel` (2 segmentos, `harden_normals=True`) + `WeightedNormal` (e `Solidify` quando houver espessura).
""",
            encoding="utf-8",
        )

    fleet_note = root / "00_Indice_e_Regras" / "Frota_LM_Link.md"
    if not fleet_note.exists():
        fleet_note.write_text(
            """---
type: fleet_allocation
total_servo_vram_gb: 46.4
---

# Alocação de Modelos por Máquina (LM Link)

- **Mestre (`Magalhães_note` — RTX 4060 Laptop):** VS Code + Blender + `blender-mcp` + `ezdxf` + Cofre Obsidian.
- **Servo 1 (`berinjela` — RTX 2000 Ada 15.6 GB):** Papel `coder_3d` (`Qwen3.8-14B-Instruct`, `ctx: 24576`).
- **Servo 2 (`nixos_ada` — RTX 2000 Ada 15.6 GB):** Papel `dwg_planner` (`Qwen3.8-14B` Thinking / `Qwen3.8-27B`).
- **Servo 3 (`nixos_4060` — RTX 4060 7.6 GB):** Papel `vision_audit` (`Qwen3.8-VL-8B` / `gemma-4-e4b-it-qat`).
- **Servo 4 (`nuttec` — RTX 4060 7.6 GB):** Papel `embeddings_rag` (`text-embedding-bge-m3` + `Qwen3.8-4B`).
""",
            encoding="utf-8",
        )

    return root


def ingest_dxf_to_vault(
    file_path: Path | str,
    vault_dir: Path | str | None = None,
    max_part_notes: int = 25,
) -> dict[str, Any]:
    """Extrai os metadados de um .dxf/.dwg e grava a nota da prancha + notas das peças principais no Cofre Obsidian."""
    root = init_vault(vault_dir)
    target = Path(file_path)
    if target.suffix.lower() == ".dwg":
        target = convert_dwg_to_dxf(target)

    summary = summarize_dxf(target)
    stem = _safe_filename(target.stem)
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    part_links: list[str] = []
    created_part_notes: list[str] = []

    for inst in summary.get("block_instances", [])[:max_part_notes]:
        handle = inst.get("handle") or "nohandle"
        bname = inst.get("block_name") or "bloco"
        tag = inst.get("attributes", {}).get("TAG") or bname
        part_note_stem = _safe_filename(f"{stem}__{tag}__{handle}")
        part_note_path = root / "02_Pecas_e_Blocos" / f"{part_note_stem}.md"

        frontmatter = {
            "type": "cad_part",
            "dwg_source": target.name,
            "parent_drawing": f"[[{stem}]]",
            "dwg_handle": handle,
            "block_name": bname,
            "part_tag": tag,
            "dwg_layer": inst.get("layer", "0"),
            "position_xyz": inst.get("position", [0.0, 0.0, 0.0]),
            "scale_xyz": inst.get("scale", [1.0, 1.0, 1.0]),
            "rotation_deg": inst.get("rotation", 0.0),
            "status": "planejado",
            "blender_object_name": "",
            "updated_at": now_iso,
        }
        body = [
            "---",
            json.dumps(frontmatter, ensure_ascii=False, indent=2),
            "---",
            "",
            f"# Peça / Bloco: `{tag}` (`{handle}`)",
            f"- **Prancha de Origem:** [[{stem}]]",
            f"- **Layer CAD:** `{inst.get('layer', '0')}`",
            f"- **Posição 3D (m/unid CAD):** `{inst.get('position')}`",
            f"- **Atributos CAD (`ATTRIB`):** `{json.dumps(inst.get('attributes', {}), ensure_ascii=False)}`",
            f"- **Notas Próximas (2D):** `{inst.get('nearby_notes', [])}`",
            "",
            "## Checklist de Modelagem 3D no Blender",
            "- [ ] Geometria 3D criada no Blender",
            "- [ ] Custom Properties (`dwg_handle`, `part_tag`, `cad_attribs_json`) gravadas",
            "- [ ] Material PBR + modificador `Bevel` aplicados",
            "- [ ] Auditado visualmente pelo Servo VLM",
            "",
        ]
        part_note_path.write_text("\n".join(body), encoding="utf-8")
        part_links.append(f"- [[{part_note_stem}]] (Layer: `{inst.get('layer')}`, Pos: `{inst.get('position')}`)")
        created_part_notes.append(str(part_note_path))

    drawing_note_path = root / "01_Pranchas_DWG" / f"{stem}.md"
    drawing_frontmatter = {
        "type": "cad_drawing",
        "dwg_file": target.name,
        "dxf_version": summary.get("dxf_version"),
        "units_code": summary.get("units_code"),
        "bounding_box": summary.get("bounding_box"),
        "entity_counts": summary.get("entity_counts"),
        "layers": summary.get("layers"),
        "status": "inspecionado",
        "ingested_at": now_iso,
    }
    layers_md = "\n".join(
        f"- `{lname}`: {info.get('entity_count', 0)} entidades (ACI Color: `{info.get('aci_color', 7)}`, Linetype: `{info.get('linetype')}`)"
        for lname, info in list(summary.get("layer_details", {}).items())[:30]
    )
    dims_md = "\n".join(
        f"- Layer `{d.get('layer')}`: medida `{d.get('measurement')}` (texto: `{d.get('override_text')}`) em `{d.get('position')}`"
        for d in summary.get("dimensions", [])[:20]
    )
    drawing_body = [
        "---",
        json.dumps(drawing_frontmatter, ensure_ascii=False, indent=2),
        "---",
        "",
        f"# Prancha CAD: `{target.name}`",
        "Regras aplicáveis: [[Regras_Layers_e_Materiais]] | Frota: [[Frota_LM_Link]]",
        "",
        "## Layers e Cores ACI (Ground Truth)",
        layers_md or "- *(Nenhuma layer detalhada)*",
        "",
        "## Cotas Extraídas (`DIMENSION`)",
        dims_md or "- *(Nenhuma entidade DIMENSION explícita)*",
        "",
        "## Peças e Blocos Catalogados (`INSERT`)",
        "\n".join(part_links) if part_links else "- *(Nenhum bloco INSERT encontrado)*",
        "",
    ]
    drawing_note_path.write_text("\n".join(drawing_body), encoding="utf-8")

    return {
        "ok": True,
        "vault_dir": str(root),
        "drawing_note": str(drawing_note_path),
        "part_notes_created": len(created_part_notes),
        "part_notes": created_part_notes,
    }


def update_part_blender_status(
    part_note_name: str,
    blender_object_name: str,
    status: str = "modelado",
    notes: str = "",
    vault_dir: Path | str | None = None,
) -> str:
    """Atualiza a nota de uma peça no Cofre Obsidian com o nome do objeto criado no Blender e grava log."""
    root = init_vault(vault_dir)
    stem = part_note_name.removesuffix(".md")
    note_path = root / "02_Pecas_e_Blocos" / f"{stem}.md"
    if not note_path.exists():
        return json.dumps({"ok": False, "error": f"Nota não encontrada: {note_path}"}, ensure_ascii=False)

    content = note_path.read_text(encoding="utf-8")
    updated = content.replace('"status": "planejado"', f'"status": "{status}"')
    updated = updated.replace('"blender_object_name": ""', f'"blender_object_name": "{blender_object_name}"')
    updated = updated.replace(
        "- [ ] Geometria 3D criada no Blender",
        f"- [x] Geometria 3D criada no Blender (`{blender_object_name}`)",
    )
    updated = updated.replace(
        "- [ ] Custom Properties (`dwg_handle`, `part_tag`, `cad_attribs_json`) gravadas",
        "- [x] Custom Properties (`dwg_handle`, `part_tag`, `cad_attribs_json`) gravadas",
    )
    updated = updated.replace(
        "- [ ] Material PBR + modificador `Bevel` aplicados",
        "- [x] Material PBR + modificador `Bevel` aplicados",
    )
    if notes:
        updated += f"\n- **Nota de execução:** {notes}\n"
    note_path.write_text(updated, encoding="utf-8")

    log_file = root / "03_Logs_Modelagem" / "historico_modelagem.md"
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"- `{now_iso}` | Peça [[{stem}]] -> Objeto Blender `{blender_object_name}` (`{status}`) {notes}\n")

    return json.dumps(
        {
            "ok": True,
            "updated_note": str(note_path),
            "blender_object_name": blender_object_name,
            "status": status,
        },
        ensure_ascii=False,
    )


def read_vault_note(rel_or_name: str, vault_dir: Path | str | None = None) -> str:
    """Lê uma nota do Cofre Obsidian pelo caminho relativo ou nome."""
    root = init_vault(vault_dir)
    candidate = root / rel_or_name
    if not candidate.exists() and not rel_or_name.endswith(".md"):
        candidate = root / f"{rel_or_name}.md"
    if not candidate.exists():
        matches = list(root.rglob(f"*{rel_or_name.removesuffix('.md')}*.md"))
        if not matches:
            return json.dumps({"ok": False, "error": f"Nota '{rel_or_name}' não encontrada no cofre."}, ensure_ascii=False)
        candidate = matches[0]
    return json.dumps(
        {
            "ok": True,
            "path": str(candidate),
            "content": candidate.read_text(encoding="utf-8"),
        },
        ensure_ascii=False,
    )


OBSIDIAN_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "obsidian_ingest_cad",
            "description": "Inspeciona um arquivo .dxf/.dwg e grava os fatos geométricos imutáveis (YAML Frontmatter + Wikilinks) no Cofre Obsidian (`vault_samarco/`).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Caminho do arquivo .dxf ou .dwg."},
                    "max_part_notes": {"type": "integer", "description": "Máximo de notas de peças a gerar (padrão 25)."},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obsidian_read_note",
            "description": "Lê uma nota do Cofre Obsidian (`vault_samarco/`) para consultar medidas reais (Ground Truth) e estado de modelagem antes de desenhar no Blender.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rel_or_name": {"type": "string", "description": "Nome da nota ou caminho relativo no cofre."},
                },
                "required": ["rel_or_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obsidian_update_part_status",
            "description": "Atualiza a nota de uma peça no Cofre Obsidian registrando o `blender_object_name` criado e marcando o checklist como modelado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "part_note_name": {"type": "string", "description": "Nome da nota da peça em 02_Pecas_e_Blocos."},
                    "blender_object_name": {"type": "string", "description": "Nome exato do objeto criado no Blender."},
                    "status": {"type": "string", "description": "Novo status (ex: 'modelado', 'auditado')."},
                    "notes": {"type": "string", "description": "Observações técnicas adicionais."},
                },
                "required": ["part_note_name", "blender_object_name"],
            },
        },
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerenciador do Cofre Obsidian Samarco (compatível com CLI e n8n batch)")
    parser.add_argument("--vault-dir", default=os.getenv("OBSIDIAN_VAULT_DIR", str(DEFAULT_VAULT_DIR)))
    parser.add_argument("--init", action="store_true", help="Inicializa a estrutura do Cofre Obsidian.")
    parser.add_argument("--ingest", help="Caminho de um arquivo .dxf ou .dwg para ingerir no Cofre Obsidian.")
    args = parser.parse_args()

    if args.ingest:
        res = ingest_dxf_to_vault(args.ingest, vault_dir=args.vault_dir)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        root = init_vault(args.vault_dir)
        print(json.dumps({"ok": True, "vault_initialized": str(root)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
