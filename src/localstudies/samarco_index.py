"""Catalogador e buscador para os arquivos CAD/documentos da pasta Samarco, com abastecimento automático do Cofre Obsidian local."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from localstudies.obsidian_vault import ingest_dxf_to_vault, init_vault

load_dotenv()

DEFAULT_INDEX_PATH = Path("build/samarco_catalog.json")


def _extract_group_prefix(rel_path: str) -> str:
    """Agrupa arquivos pelo prefixo do pacote (ex: DRW, DP4, DOC, ZTK) para manter o Obsidian limpo."""
    parts = Path(rel_path).parts
    target = parts[1] if len(parts) > 2 else parts[0]
    prefix = target.split("_")[0].split("-")[0].upper()
    cleaned = "".join(c for c in prefix if c.isalnum())
    return cleaned or "GERAL"


def sync_catalog_to_obsidian(
    catalog: dict[str, Any],
    vault_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Grava `Catalogo_Samarco.md` e notas por prefixo (`Catalogo_<PREFIXO>.md`) no Cofre Obsidian local."""
    root = init_vault(vault_dir)
    index_dir = root / "00_Indice_e_Regras"
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in catalog.get("files", []):
        prefix = _extract_group_prefix(entry.get("rel_path", ""))
        grouped[prefix].append(entry)

    group_links: list[str] = []
    created_notes: list[str] = []

    for prefix, items in sorted(grouped.items()):
        note_stem = f"Catalogo_{prefix}"
        note_path = index_dir / f"{note_stem}.md"
        ext_counts = Counter(i.get("ext", "") for i in items)
        dwg_count = ext_counts.get(".dwg", 0)
        summary_exts = ", ".join(f"`{k}`: {v}" for k, v in ext_counts.most_common())

        lines = [
            "---",
            "type: samarco_package_group",
            f"prefix: {prefix}",
            f"total_files: {len(items)}",
            f"dwg_files: {dwg_count}",
            f"updated_at: {now_iso}",
            "---",
            "",
            f"# Catálogo Samarco — Grupo `{prefix}` ({len(items)} arquivos)",
            f"Voltar para [[Catalogo_Samarco]] | [[00_Home_Samarco]]",
            "",
            f"**Resumo por extensão:** {summary_exts}",
            "",
            "## Arquivos Catalogados",
        ]

        # Lista primeiro os .dwg e depois os demais anexos (limitado para manter boa leitura no Obsidian)
        sorted_items = sorted(items, key=lambda x: (0 if x.get("ext") == ".dwg" else 1, x.get("rel_path", "")))
        for item in sorted_items[:400]:
            size_kb = round(item.get("size_bytes", 0) / 1024, 1)
            rel = item.get("rel_path", "")
            stem = Path(item.get("name", "")).stem
            prancha_note = root / "01_Pranchas_DWG" / f"{stem}.md"
            status_tag = f" → [[{stem}]]" if prancha_note.exists() else ""
            lines.append(f"- `{item.get('ext')}` | `{rel}` ({size_kb} KB){status_tag}")

        if len(sorted_items) > 400:
            lines.append(f"\n> *Mostrando 400 de {len(sorted_items)} arquivos. Use `samarco_search_files` no chat para buscar qualquer item.*")

        note_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        created_notes.append(str(note_path))
        group_links.append(f"- [[{note_stem}]] — **{len(items)} arquivos** (`{dwg_count}` `.dwg`)")

    ext_table = "\n".join(
        f"| `{ext or '(sem ext)'}` | {count} |"
        for ext, count in catalog.get("by_extension", {}).items()
    )
    main_catalog_path = index_dir / "Catalogo_Samarco.md"
    main_catalog_path.write_text(
        f"""---
type: samarco_master_catalog
total_files: {catalog.get('total_files', 0)}
total_mb: {catalog.get('total_mb', 0)}
updated_at: {now_iso}
---

# Catálogo Geral — Pasta Samarco (Máquina Local)

Voltar para [[00_Home_Samarco]]

- **Raiz local:** `{catalog.get('root')}`
- **Total de arquivos:** **{catalog.get('total_files')}** ({catalog.get('total_mb')} MB)

## Distribuição por Extensão
| Extensão | Quantidade |
| :--- | ---: |
{ext_table}

## Grupos de Pacotes (Clique para navegar)
{chr(10).join(group_links)}
""",
        encoding="utf-8",
    )

    return {
        "vault_dir": str(root),
        "main_catalog": str(main_catalog_path),
        "group_notes_count": len(created_notes),
    }


def build_catalog(
    root_dir: Path | str | None = None,
    output_path: Path | str = DEFAULT_INDEX_PATH,
    sync_obsidian: bool = True,
    vault_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Varre `root_dir`, salva `build/samarco_catalog.json` e abastece o Cofre Obsidian local."""
    source = Path(root_dir or os.getenv("SAMARCO_DIR", "Samarco"))
    if not source.exists():
        raise FileNotFoundError(f"Diretório não encontrado: {source.resolve()}")

    entries: list[dict[str, Any]] = []
    ext_counts: Counter[str] = Counter()
    total_bytes = 0

    for item in sorted(source.rglob("*")):
        if not item.is_file():
            continue
        ext = item.suffix.lower()
        size = item.stat().st_size
        ext_counts[ext] += 1
        total_bytes += size
        entries.append(
            {
                "name": item.name,
                "ext": ext,
                "size_bytes": size,
                "rel_path": item.relative_to(source).as_posix(),
                "full_path": str(item.resolve()),
            }
        )

    catalog = {
        "root": str(source.resolve()),
        "total_files": len(entries),
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "by_extension": dict(ext_counts.most_common()),
        "files": entries,
    }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    if sync_obsidian:
        catalog["obsidian_sync"] = sync_catalog_to_obsidian(catalog, vault_dir=vault_dir)

    return catalog


def search_catalog(
    query: str = "",
    extension: str = ".dwg",
    limit: int = 20,
    index_path: Path | str = DEFAULT_INDEX_PATH,
) -> list[dict[str, Any]]:
    """Busca arquivos no catálogo gerado (ou gera o catálogo automaticamente se não existir)."""
    idx = Path(index_path)
    if not idx.exists():
        catalog = build_catalog(output_path=idx)
    else:
        catalog = json.loads(idx.read_text(encoding="utf-8"))

    q = query.strip().lower()
    ext_filter = extension.strip().lower()
    if ext_filter and not ext_filter.startswith("."):
        ext_filter = f".{ext_filter}"

    matches: list[dict[str, Any]] = []
    for entry in catalog.get("files", []):
        if ext_filter and entry.get("ext") != ext_filter:
            continue
        if q and q not in entry.get("rel_path", "").lower():
            continue
        matches.append(entry)
        if len(matches) >= limit:
            break
    return matches


SAMARCO_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "samarco_search_files",
        "description": "Busca arquivos (.dwg, .pdf, .tif, .xls, .doc) no catálogo da pasta Samarco por código ou trecho do nome.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Trecho do nome ou código da prancha (ex: 'ZTK_U030905')."},
                "extension": {"type": "string", "description": "Extensão desejada (padrão '.dwg', ou vazio para todas)."},
                "limit": {"type": "integer", "description": "Máximo de resultados (padrão 20)."},
            },
            "required": [],
        },
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexa a pasta Samarco e abastece o Cofre Obsidian local")
    parser.add_argument("--no-obsidian", action="store_true", help="Não sincroniza as notas no Cofre Obsidian.")
    parser.add_argument(
        "--ingest-dwgs",
        type=int,
        default=0,
        help="Converte e ingere os primeiros N arquivos .dwg diretamente em 01_Pranchas_DWG/ e 02_Pecas_e_Blocos/.",
    )
    args = parser.parse_args()

    catalog = build_catalog(sync_obsidian=not args.no_obsidian)
    ingested_results: list[dict[str, Any]] = []

    if args.ingest_dwgs > 0:
        dwgs = [f for f in catalog.get("files", []) if f.get("ext") == ".dwg"][: args.ingest_dwgs]
        for item in dwgs:
            try:
                res = ingest_dxf_to_vault(item["full_path"])
                ingested_results.append({"file": item["name"], "ok": True, "part_notes": res["part_notes_created"]})
            except Exception as exc:
                ingested_results.append({"file": item["name"], "ok": False, "error": str(exc)})
        # Atualiza links [[prancha]] no catálogo após ingestão
        if not args.no_obsidian:
            catalog["obsidian_sync"] = sync_catalog_to_obsidian(catalog)

    print(
        json.dumps(
            {
                "root": catalog["root"],
                "total_files": catalog["total_files"],
                "total_mb": catalog["total_mb"],
                "by_extension": catalog["by_extension"],
                "saved_to": str(DEFAULT_INDEX_PATH),
                "obsidian_sync": catalog.get("obsidian_sync"),
                "ingested_dwgs": ingested_results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
