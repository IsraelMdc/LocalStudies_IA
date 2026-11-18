"""Pipeline DWG -> DXF -> JSON rico em metadados de engenharia por peça para LLMs, Obsidian e Blender MCP."""

from __future__ import annotations

import json
import math
import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import ezdxf
from dotenv import load_dotenv

load_dotenv()


def _resolve_oda_converter(oda_converter_path: str | None = None) -> str:
    """Resolve o executável do ODA File Converter via argumento, `.env`/ambiente ou auto-detecção no Windows."""
    explicit = (oda_converter_path or os.getenv("ODA_CONVERTER_PATH", "")).strip()
    if explicit and Path(explicit).exists():
        return explicit
    for base in (Path(r"C:\Program Files\ODA"), Path(r"C:\Program Files (x86)\ODA")):
        if base.exists():
            matches = sorted(base.glob("ODAFileConverter*/ODAFileConverter.exe"), reverse=True)
            if matches:
                return str(matches[0])
    return ""


def convert_dwg_to_dxf(
    dwg_path: Path | str,
    output_dir: Path | str = Path("build/dxf"),
    oda_converter_path: str | None = None,
) -> Path:
    """Converte um .dwg em .dxf usando ODA File Converter (CLI)."""
    src = Path(dwg_path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Arquivo DWG não encontrado: {src}")

    oda_exe = _resolve_oda_converter(oda_converter_path)
    if not oda_exe or not Path(oda_exe).exists():
        raise RuntimeError(
            "ODA_CONVERTER_PATH não configurado ou inválido. "
            "Instale o ODA File Converter e defina ODA_CONVERTER_PATH no .env, "
            "ou forneça um arquivo .dxf já convertido."
        )

    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        oda_exe,
        str(src.parent),
        str(out_dir),
        "ACAD2018",
        "DXF",
        "0",
        "1",
        src.name,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"Falha ao converter DWG: {proc.stderr or proc.stdout}")

    expected_dxf = out_dir / f"{src.stem}.dxf"
    if not expected_dxf.exists():
        raise FileNotFoundError(f"Conversão concluída sem gerar {expected_dxf}")
    return expected_dxf


def _extract_xdata(ent: Any) -> dict[str, list[str]]:
    """Extrai dados estendidos (XDATA) anexados à entidade CAD, quando presentes."""
    result: dict[str, list[str]] = {}
    if not getattr(ent, "has_xdata", False):
        return result
    try:
        for appid in ent.xdata.appids():
            tags = ent.get_xdata(appid)
            result[str(appid)] = [f"{t.code}:{t.value}" for t in tags[:15]]
    except Exception:
        pass
    return result


def _safe_elevation(ent: Any) -> float:
    """Extrai elevação como float mesmo quando `ent.dxf.elevation` é um Vec3 (ex: POLYLINE)."""
    if not ent.dxf.hasattr("elevation"):
        return 0.0
    val = ent.dxf.elevation
    if hasattr(val, "z"):
        return round(float(val.z), 4)
    try:
        return round(float(val), 4)
    except (TypeError, ValueError):
        return 0.0


def summarize_dxf(
    dxf_path: Path | str,
    max_samples_per_type: int = 40,
    proximity_radius: float = 50.0,
) -> dict[str, Any]:
    """Extrai resumo rico por peça (layers com cor ACI, blocos com ATTRIB, cotas, Z/thickness e notas próximas)."""
    path = Path(dxf_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Arquivo DXF não encontrado: {path}")

    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()

    layer_metadata: dict[str, dict[str, Any]] = {}
    for layer in doc.layers:
        lname = layer.dxf.name
        layer_metadata[lname] = {
            "aci_color": int(layer.dxf.color) if layer.dxf.hasattr("color") else 7,
            "linetype": str(layer.dxf.linetype) if layer.dxf.hasattr("linetype") else "Continuous",
            "lineweight": int(layer.dxf.lineweight) if layer.dxf.hasattr("lineweight") else -1,
            "entity_count": 0,
        }

    entity_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    texts: list[dict[str, Any]] = []
    dimensions: list[dict[str, Any]] = []
    polylines: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    block_instances: list[dict[str, Any]] = []
    blocks: Counter[str] = Counter()

    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")

    def _update_bounds(x: float, y: float, z: float = 0.0) -> None:
        nonlocal min_x, min_y, min_z, max_x, max_y, max_z
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        min_z = min(min_z, z)
        max_x = max(max_x, x)
        max_y = max(max_y, y)
        max_z = max(max_z, z)

    for ent in msp:
        etype = ent.dxftype()
        layer = ent.dxf.layer if ent.dxf.hasattr("layer") else "0"
        handle = str(ent.dxf.handle) if ent.dxf.hasattr("handle") else ""
        thickness = round(float(ent.dxf.thickness), 4) if ent.dxf.hasattr("thickness") else 0.0
        elevation = _safe_elevation(ent)

        entity_counts[etype] += 1
        layer_counts[layer] += 1
        if layer in layer_metadata:
            layer_metadata[layer]["entity_count"] += 1
        else:
            layer_metadata[layer] = {
                "aci_color": 7,
                "linetype": "Continuous",
                "lineweight": -1,
                "entity_count": 1,
            }

        if etype == "LINE":
            s = ent.dxf.start
            e = ent.dxf.end
            _update_bounds(s.x, s.y, getattr(s, "z", 0.0))
            _update_bounds(e.x, e.y, getattr(e, "z", 0.0))
            if len(lines) < max_samples_per_type:
                length_3d = math.dist(
                    (s.x, s.y, getattr(s, "z", 0.0)),
                    (e.x, e.y, getattr(e, "z", 0.0)),
                )
                lines.append(
                    {
                        "handle": handle,
                        "layer": layer,
                        "start": [round(s.x, 3), round(s.y, 3), round(getattr(s, "z", 0.0), 3)],
                        "end": [round(e.x, 3), round(e.y, 3), round(getattr(e, "z", 0.0), 3)],
                        "length": round(length_3d, 3),
                        "thickness": thickness,
                    }
                )
        elif etype == "LWPOLYLINE":
            pts = [[round(p[0], 3), round(p[1], 3)] for p in ent.get_points("xy")]
            for px, py in pts:
                _update_bounds(px, py, elevation)
            if len(polylines) < max_samples_per_type and pts:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                polylines.append(
                    {
                        "handle": handle,
                        "layer": layer,
                        "closed": bool(ent.closed),
                        "elevation": elevation,
                        "thickness": thickness,
                        "bbox": {
                            "min": [min(xs), min(ys)],
                            "max": [max(xs), max(ys)],
                            "width": round(max(xs) - min(xs), 3),
                            "depth": round(max(ys) - min(ys), 3),
                        },
                        "points": pts[:24],
                        "xdata": _extract_xdata(ent),
                    }
                )
        elif etype in {"TEXT", "MTEXT"}:
            content = (ent.dxf.text if etype == "TEXT" else ent.text).strip()
            ins = ent.dxf.insert if ent.dxf.hasattr("insert") else None
            pos = [round(ins.x, 3), round(ins.y, 3)] if ins is not None else [0.0, 0.0]
            if ins is not None:
                _update_bounds(ins.x, ins.y, getattr(ins, "z", 0.0))
            if content and len(texts) < max_samples_per_type * 2:
                texts.append(
                    {
                        "handle": handle,
                        "layer": layer,
                        "text": content[:160],
                        "position": pos,
                    }
                )
        elif etype == "DIMENSION":
            measurement = (
                round(float(ent.dxf.actual_measurement), 4)
                if ent.dxf.hasattr("actual_measurement")
                else None
            )
            dim_text = str(ent.dxf.text).strip() if ent.dxf.hasattr("text") else ""
            defpoint = ent.dxf.defpoint if ent.dxf.hasattr("defpoint") else None
            pos = [round(defpoint.x, 3), round(defpoint.y, 3)] if defpoint is not None else [0.0, 0.0]
            if len(dimensions) < max_samples_per_type:
                dimensions.append(
                    {
                        "handle": handle,
                        "layer": layer,
                        "measurement": measurement,
                        "override_text": dim_text,
                        "position": pos,
                    }
                )
        elif etype == "INSERT":
            bname = str(ent.dxf.name)
            blocks[bname] += 1
            ins = ent.dxf.insert if ent.dxf.hasattr("insert") else None
            pos3d = (
                [round(ins.x, 3), round(ins.y, 3), round(getattr(ins, "z", 0.0), 3)]
                if ins is not None
                else [0.0, 0.0, 0.0]
            )
            if ins is not None:
                _update_bounds(ins.x, ins.y, getattr(ins, "z", 0.0))

            attribs: dict[str, str] = {}
            try:
                for attr in ent.attribs:
                    tag = str(attr.dxf.tag).strip()
                    val = str(attr.dxf.text).strip()
                    if tag and val:
                        attribs[tag] = val
            except Exception:
                pass

            if len(block_instances) < max_samples_per_type:
                block_instances.append(
                    {
                        "handle": handle,
                        "block_name": bname,
                        "layer": layer,
                        "position": pos3d,
                        "rotation": round(float(ent.dxf.rotation), 2) if ent.dxf.hasattr("rotation") else 0.0,
                        "scale": [
                            round(float(ent.dxf.xscale), 3) if ent.dxf.hasattr("xscale") else 1.0,
                            round(float(ent.dxf.yscale), 3) if ent.dxf.hasattr("yscale") else 1.0,
                            round(float(ent.dxf.zscale), 3) if ent.dxf.hasattr("zscale") else 1.0,
                        ],
                        "attributes": attribs,
                        "xdata": _extract_xdata(ent),
                        "nearby_notes": [],
                    }
                )

    # Associação espacial de textos próximos a cada peça/bloco (INSERT)
    for inst in block_instances:
        ix, iy = inst["position"][0], inst["position"][1]
        near: list[str] = []
        for txt in texts:
            tx, ty = txt["position"][0], txt["position"][1]
            if math.hypot(ix - tx, iy - ty) <= proximity_radius:
                near.append(txt["text"])
                if len(near) >= 5:
                    break
        inst["nearby_notes"] = near

    bbox = None
    origin_offset = [0.0, 0.0, 0.0]
    if min_x != float("inf"):
        cx = round((min_x + max_x) / 2.0, 3)
        cy = round((min_y + max_y) / 2.0, 3)
        cz = round(min_z, 3)
        origin_offset = [cx, cy, cz]
        bbox = {
            "min": [round(min_x, 3), round(min_y, 3), round(min_z, 3)],
            "max": [round(max_x, 3), round(max_y, 3), round(max_z, 3)],
            "width": round(max_x - min_x, 3),
            "height": round(max_y - min_y, 3),
            "depth_z": round(max_z - min_z, 3),
            "recommended_origin_offset": origin_offset,
        }

        # Adiciona coordenadas normalizadas perto da origem (0,0,0) para o Blender não jogar peças a quilômetros
        for inst in block_instances:
            px, py, pz = inst["position"]
            inst["local_position_centered"] = [
                round(px - cx, 3),
                round(py - cy, 3),
                round(pz - cz, 3),
            ]
        for poly in polylines:
            poly["local_points_centered"] = [
                [round(pt[0] - cx, 3), round(pt[1] - cy, 3)]
                for pt in poly["points"]
            ]

    return {
        "file": str(path),
        "dxf_version": doc.dxfversion,
        "units_code": doc.header.get("$INSUNITS", 0),
        "recommended_origin_offset": origin_offset,
        "bounding_box": bbox,
        "layers": dict(layer_counts.most_common(40)),
        "layer_details": layer_metadata,
        "entity_counts": dict(entity_counts.most_common()),
        "top_blocks": dict(blocks.most_common(20)),
        "block_instances": block_instances,
        "dimensions": dimensions,
        "sample_texts": texts[:max_samples_per_type],
        "sample_polylines": polylines,
        "sample_lines": lines,
    }


def inspect_cad_file(file_path: str, max_samples_per_type: int = 40) -> str:
    """Aceita .dxf diretamente ou converte .dwg -> .dxf e retorna JSON rico em metadados por peça."""
    target = Path(file_path)
    if target.suffix.lower() == ".dwg":
        target = convert_dwg_to_dxf(target)
    summary = summarize_dxf(target, max_samples_per_type=max_samples_per_type)
    return json.dumps(summary, ensure_ascii=False)


CAD_INSPECT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "inspect_cad_file",
        "description": "Inspeciona um arquivo .dxf (ou .dwg se ODA_CONVERTER_PATH estiver configurado) e retorna layers (com cor ACI), blocos com ATTRIB, cotas DIMENSION, coordenadas Z/thickness e textos próximos por peça em JSON.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Caminho do arquivo .dxf ou .dwg."},
                "max_samples_per_type": {
                    "type": "integer",
                    "description": "Limite de amostras por tipo de entidade (padrão 40).",
                },
            },
            "required": ["file_path"],
        },
    },
}
