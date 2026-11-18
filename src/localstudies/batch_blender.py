"""Processador em lote resumível para converter arquivos .dwg da pasta Samarco em .blend, .glb e _preview.png."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from localstudies.dxf_to_blender import DEFAULT_EXPORT_DIR, build_cad_3d_in_blender
from localstudies.samarco_index import _extract_group_prefix, search_catalog


def run_batch(
    limit: int = 0,
    query: str = "",
    export_dir: Path | str = DEFAULT_EXPORT_DIR,
    skip_existing: bool = True,
) -> dict[str, Any]:
    """Processa arquivos .dwg do catálogo Samarco em lote, organizados por grupo e peça em `exports/<GRUPO>/<PRANCHA>/pecas/`."""
    out_dir = Path(export_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    all_dwgs = search_catalog(query=query, extension=".dwg", limit=10000)
    targets = all_dwgs[:limit] if limit > 0 else all_dwgs

    processed: list[dict[str, Any]] = []
    skipped = 0
    succeeded = 0
    failed = 0

    for item in targets:
        full_path = Path(item["full_path"])
        stem = full_path.stem
        group = _extract_group_prefix(item.get("rel_path", ""))
        group_dir = out_dir / group
        prancha_dir = group_dir / stem
        expected_glb = prancha_dir / f"{stem}.glb"
        expected_blend = prancha_dir / f"{stem}.blend"
        expected_parts = prancha_dir / "pecas"

        if skip_existing and expected_glb.exists() and expected_blend.exists() and expected_parts.exists():
            skipped += 1
            continue

        try:
            res = build_cad_3d_in_blender(str(full_path), export_dir=str(group_dir))
            succeeded += 1
            processed.append(
                {
                    "file": full_path.name,
                    "ok": True,
                    "layers": res["layers_count"],
                    "inserts": res["inserts_count"],
                    "glb": res["outputs"]["glb"],
                }
            )
        except Exception as exc:
            failed += 1
            processed.append(
                {
                    "file": full_path.name,
                    "ok": False,
                    "error": str(exc),
                }
            )

    report = {
        "total_catalog_dwgs": len(all_dwgs),
        "requested": len(targets),
        "skipped_existing": skipped,
        "succeeded": succeeded,
        "failed": failed,
        "results": processed,
    }
    (out_dir / "batch_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Processa DWGs da Samarco em lote para Blender (.blend/.glb/.png)")
    parser.add_argument("--limit", type=int, default=10, help="Quantidade máxima de DWGs a processar (0 = todos os 1.583).")
    parser.add_argument("--query", default="", help="Filtro opcional por código/nome da prancha.")
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR))
    parser.add_argument("--force", action="store_true", help="Reprocessa mesmo se .glb e .blend já existirem.")
    args = parser.parse_args()

    report = run_batch(
        limit=args.limit,
        query=args.query,
        export_dir=args.export_dir,
        skip_existing=not args.force,
    )
    print(
        json.dumps(
            {
                "total_catalog_dwgs": report["total_catalog_dwgs"],
                "requested": report["requested"],
                "skipped_existing": report["skipped_existing"],
                "succeeded": report["succeeded"],
                "failed": report["failed"],
                "report_file": str(Path(args.export_dir) / "batch_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
