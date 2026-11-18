"""Construtor determinístico de cena 3D completa no Blender a partir de arquivos DWG/DXF com exportação (.blend, .glb, .png)."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import ezdxf
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from localstudies.blender_part_builder import ACI_COLOR_MAP
from localstudies.dwg_pipeline import convert_dwg_to_dxf

DEFAULT_EXPORT_DIR = Path("exports")


def _detect_unit_scale(doc: ezdxf.document.Drawing, raw_width: float) -> float:
    """Converte unidades CAD para metros no Blender (mm -> 0.001, cm -> 0.01, ou heurística se sem unidade)."""
    insunits = int(doc.header.get("$INSUNITS", 0))
    if insunits == 4:  # Millimeters
        return 0.001
    if insunits == 5:  # Centimeters
        return 0.01
    if insunits == 6:  # Meters
        return 1.0
    if raw_width > 2000.0:
        return 0.001
    return 1.0


def extract_full_geometry(
    file_path: Path | str,
    extrude_height: float = 1.5,
    beam_width: float = 0.08,
    max_entities_per_layer: int = 800,
) -> dict[str, Any]:
    """Extrai toda a geometria 2D/3D do DXF/DWG normalizada em metros e centralizada na origem (0,0,0)."""
    target = Path(file_path)
    if target.suffix.lower() == ".dwg":
        target = convert_dwg_to_dxf(target)
    target = target.resolve()
    if not target.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {target}")

    doc = ezdxf.readfile(str(target))
    msp = doc.modelspace()

    layer_colors: dict[str, int] = {}
    for layer in doc.layers:
        layer_colors[layer.dxf.name] = abs(int(layer.dxf.color)) if layer.dxf.hasattr("color") else 7

    raw_segments: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
    raw_polys: dict[str, list[tuple[list[tuple[float, float]], bool]]] = defaultdict(list)
    raw_circles: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    raw_inserts: list[dict[str, Any]] = []

    xs: list[float] = []
    ys: list[float] = []

    for ent in msp:
        etype = ent.dxftype()
        layer = ent.dxf.layer if ent.dxf.hasattr("layer") else "0"
        handle = str(ent.dxf.handle) if ent.dxf.hasattr("handle") else ""

        if etype == "LINE":
            s, e = ent.dxf.start, ent.dxf.end
            if len(raw_segments[layer]) < max_entities_per_layer:
                raw_segments[layer].append((s.x, s.y, e.x, e.y))
            xs.extend((s.x, e.x))
            ys.extend((s.y, e.y))
        elif etype == "ARC":
            c = ent.dxf.center
            r = float(ent.dxf.radius)
            a1 = math.radians(float(ent.dxf.start_angle))
            a2 = math.radians(float(ent.dxf.end_angle))
            if a2 < a1:
                a2 += 2 * math.pi
            steps = 8
            prev_x = c.x + r * math.cos(a1)
            prev_y = c.y + r * math.sin(a1)
            xs.append(prev_x)
            ys.append(prev_y)
            for i in range(1, steps + 1):
                ang = a1 + (a2 - a1) * (i / steps)
                nx = c.x + r * math.cos(ang)
                ny = c.y + r * math.sin(ang)
                if len(raw_segments[layer]) < max_entities_per_layer:
                    raw_segments[layer].append((prev_x, prev_y, nx, ny))
                xs.append(nx)
                ys.append(ny)
                prev_x, prev_y = nx, ny
        elif etype == "LWPOLYLINE":
            pts = [(float(p[0]), float(p[1])) for p in ent.get_points("xy")]
            if len(pts) >= 2:
                if len(raw_polys[layer]) < max_entities_per_layer:
                    raw_polys[layer].append((pts, bool(ent.closed)))
                for px, py in pts:
                    xs.append(px)
                    ys.append(py)
        elif etype == "CIRCLE":
            c = ent.dxf.center
            r = float(ent.dxf.radius)
            if len(raw_circles[layer]) < max_entities_per_layer:
                raw_circles[layer].append((c.x, c.y, r))
            xs.append(c.x)
            ys.append(c.y)
        elif etype == "INSERT":
            ins = ent.dxf.insert
            attribs: dict[str, str] = {}
            try:
                for attr in ent.attribs:
                    t = str(attr.dxf.tag).strip()
                    v = str(attr.dxf.text).strip()
                    if t and v:
                        attribs[t] = v
            except Exception:
                pass
            raw_inserts.append(
                {
                    "handle": handle,
                    "layer": layer,
                    "block_name": str(ent.dxf.name),
                    "x": float(ins.x),
                    "y": float(ins.y),
                    "attribs": attribs,
                }
            )
            xs.append(float(ins.x))
            ys.append(float(ins.y))

    if not xs or not ys:
        raise ValueError(f"Nenhuma geometria 2D/3D encontrada em {target}")

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    scale = _detect_unit_scale(doc, max_x - min_x)

    layers_payload: dict[str, dict[str, Any]] = {}
    all_layers = sorted(set(raw_segments) | set(raw_polys) | set(raw_circles))
    for lname in all_layers:
        segs = [
            [
                round((x1 - cx) * scale, 4),
                round((y1 - cy) * scale, 4),
                round((x2 - cx) * scale, 4),
                round((y2 - cy) * scale, 4),
            ]
            for (x1, y1, x2, y2) in raw_segments.get(lname, [])
        ]
        polys = [
            {
                "closed": closed,
                "pts": [[round((px - cx) * scale, 4), round((py - cy) * scale, 4)] for px, py in pts],
            }
            for (pts, closed) in raw_polys.get(lname, [])
        ]
        circs = [
            [
                round((rx - cx) * scale, 4),
                round((ry - cy) * scale, 4),
                max(0.02, round(rr * scale, 4)),
            ]
            for (rx, ry, rr) in raw_circles.get(lname, [])
        ]
        layers_payload[lname] = {
            "aci_color": layer_colors.get(lname, 7),
            "segments": segs,
            "polylines": polys,
            "circles": circs,
        }

    inserts_payload = [
        {
            "handle": ins["handle"],
            "layer": ins["layer"],
            "block_name": ins["block_name"],
            "pos": [round((ins["x"] - cx) * scale, 4), round((ins["y"] - cy) * scale, 4), 0.0],
            "attribs": ins["attribs"],
        }
        for ins in raw_inserts[:100]
    ]

    return {
        "source_file": target.name,
        "stem": target.stem,
        "unit_scale": scale,
        "origin_offset_cad": [round(cx, 3), round(cy, 3), 0.0],
        "scene_span_m": [round((max_x - min_x) * scale, 3), round((max_y - min_y) * scale, 3)],
        "extrude_height": extrude_height,
        "beam_width": beam_width,
        "layers": layers_payload,
        "inserts": inserts_payload,
    }


def build_scene_bpy_script(
    payload: dict[str, Any],
    export_dir: Path | str = DEFAULT_EXPORT_DIR,
    clear_scene: bool = True,
    export_individual_parts: bool = True,
) -> tuple[str, dict[str, str]]:
    """Gera script `bpy` completo para montar a cena 3D no Blender e salvar .blend, .glb, _preview.png e cada peça em `pecas/*.blend`."""
    stem = payload["stem"]
    out_dir = Path(export_dir).resolve() / stem
    parts_dir = out_dir / "pecas"
    out_dir.mkdir(parents=True, exist_ok=True)
    if export_individual_parts:
        parts_dir.mkdir(parents=True, exist_ok=True)

    blend_path = str(out_dir / f"{stem}.blend")
    glb_path = str(out_dir / f"{stem}.glb")
    png_path = str(out_dir / f"{stem}_preview.png")

    full_data = {
        **payload,
        "aci_map": {str(k): list(v) for k, v in ACI_COLOR_MAP.items()},
        "clear_scene": clear_scene,
        "export_individual_parts": export_individual_parts,
        "parts_dir": str(parts_dir),
        "blend_path": blend_path,
        "glb_path": glb_path,
        "png_path": png_path,
    }
    data_json = json.dumps(full_data, ensure_ascii=False)

    script = f"""import json
import math
import bpy
import bmesh
from mathutils import Vector

DATA = json.loads({data_json!r})

if DATA["clear_scene"]:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

def ensure_collection(name, parent=None):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        target = parent if parent is not None else bpy.context.scene.collection
        target.children.link(col)
    return col

root_col = ensure_collection(DATA["stem"])
layers_col = ensure_collection("Layers_3D", root_col)
blocks_col = ensure_collection("Blocos_INSERT", root_col)

def get_layer_material(layer_name, aci_color):
    mat_name = f"MAT_{{layer_name}}_ACI{{aci_color}}"
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True
        rgba = DATA["aci_map"].get(str(aci_color % 10 or 7), [0.75, 0.78, 0.82, 1.0])
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = tuple(rgba)
            bsdf.inputs["Metallic"].default_value = 0.65
            bsdf.inputs["Roughness"].default_value = 0.35
        mat.diffuse_color = tuple(rgba)
    return mat

def add_thick_segment(bm, x1, y1, x2, y2, width, height):
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-4:
        return
    nx = -dy / length * (width * 0.5)
    ny = dx / length * (width * 0.5)
    v1 = bm.verts.new((x1 + nx, y1 + ny, 0.0))
    v2 = bm.verts.new((x2 + nx, y2 + ny, 0.0))
    v3 = bm.verts.new((x2 - nx, y2 - ny, 0.0))
    v4 = bm.verts.new((x1 - nx, y1 - ny, 0.0))
    v5 = bm.verts.new((x1 + nx, y1 + ny, height))
    v6 = bm.verts.new((x2 + nx, y2 + ny, height))
    v7 = bm.verts.new((x2 - nx, y2 - ny, height))
    v8 = bm.verts.new((x1 - nx, y1 - ny, height))
    for quad in ((v1, v2, v3, v4), (v5, v8, v7, v6), (v1, v5, v6, v2), (v2, v6, v7, v3), (v3, v7, v8, v4), (v4, v8, v5, v1)):
        try:
            bm.faces.new(quad)
        except ValueError:
            pass

h_default = float(DATA["extrude_height"])
w_beam = float(DATA["beam_width"])
created_objects = []

for lname, ldata in DATA["layers"].items():
    bm = bmesh.new()
    for x1, y1, x2, y2 in ldata.get("segments", []):
        add_thick_segment(bm, x1, y1, x2, y2, w_beam, h_default * 0.5)

    for poly in ldata.get("polylines", []):
        pts = poly.get("pts", [])
        if len(pts) < 2:
            continue
        if poly.get("closed") and len(pts) >= 3:
            try:
                verts = [bm.verts.new((p[0], p[1], 0.0)) for p in pts]
                face = bm.faces.new(verts)
                ext = bmesh.ops.extrude_face_region(bm, geom=[face])
                ext_verts = [g for g in ext["geom"] if isinstance(g, bmesh.types.BMVert)]
                bmesh.ops.translate(bm, vec=(0.0, 0.0, h_default), verts=ext_verts)
            except Exception:
                for i in range(len(pts)):
                    p1, p2 = pts[i], pts[(i + 1) % len(pts)]
                    add_thick_segment(bm, p1[0], p1[1], p2[0], p2[1], w_beam, h_default)
        else:
            for i in range(len(pts) - 1):
                add_thick_segment(bm, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], w_beam, h_default * 0.7)

    for cx, cy, cr in ldata.get("circles", []):
        mat_loc = Vector((cx, cy, h_default * 0.5))
        ret = bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            cap_tris=False,
            segments=12,
            radius1=cr,
            radius2=cr,
            depth=h_default,
        )
        bmesh.ops.translate(bm, verts=ret["verts"], vec=mat_loc)

    if len(bm.verts) == 0:
        bm.free()
        continue

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(f"{{lname}}_Mesh")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(f"LAYER__{{lname}}", mesh)
    layers_col.objects.link(obj)
    obj.data.materials.append(get_layer_material(lname, int(ldata.get("aci_color", 7))))
    obj["dwg_source"] = DATA["source_file"]
    obj["dwg_layer"] = lname
    obj["origin_offset_cad"] = json.dumps(DATA["origin_offset_cad"])
    obj["unit_scale"] = DATA["unit_scale"]
    created_objects.append(obj)

for ins in DATA.get("inserts", []):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=max(0.3, w_beam * 4.0))
    mesh = bpy.data.meshes.new(f"BLK_{{ins['block_name']}}_{{ins['handle']}}_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    tag = ins["attribs"].get("TAG") or ins["block_name"]
    obj = bpy.data.objects.new(f"{{ins['layer']}}__{{tag}}__{{ins['handle']}}", mesh)
    obj.location = (ins["pos"][0], ins["pos"][1], h_default * 0.5)
    blocks_col.objects.link(obj)
    obj.data.materials.append(get_layer_material(ins["layer"], 2))
    obj["dwg_source"] = DATA["source_file"]
    obj["dwg_handle"] = ins["handle"]
    obj["dwg_layer"] = ins["layer"]
    obj["part_tag"] = tag
    obj["cad_attribs_json"] = json.dumps(ins["attribs"], ensure_ascii=False)
    obj["origin_offset_cad"] = json.dumps(DATA["origin_offset_cad"])
    created_objects.append(obj)

# Iluminação e Câmera enquadrada automaticamente no desenho 3D
span_x, span_y = DATA["scene_span_m"]
cam_dist = max(15.0, max(span_x, span_y) * 1.15)

sun_data = bpy.data.lights.new(name="Sun_Samarco", type="SUN")
sun_data.energy = 3.0
sun_obj = bpy.data.objects.new(name="Sun_Samarco", object_data=sun_data)
sun_obj.rotation_euler = (math.radians(45), math.radians(15), math.radians(35))
root_col.objects.link(sun_obj)

cam_data = bpy.data.cameras.new(name="Cam_Samarco")
cam_data.clip_end = 10000.0
cam_obj = bpy.data.objects.new(name="Cam_Samarco", object_data=cam_data)
cam_obj.location = (cam_dist * 0.65, -cam_dist * 0.65, cam_dist * 0.55)
direction = Vector((0.0, 0.0, 0.0)) - cam_obj.location
cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
root_col.objects.link(cam_obj)
bpy.context.scene.camera = cam_obj

# Atualiza Viewport 3D se disponível
if bpy.context.screen is not None:
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.clip_end = 10000.0

# Salva .blend completo, cada peça separada em pecas/*.blend, exporta .glb e renderiza preview .png
import os as _os
bpy.ops.wm.save_as_mainfile(filepath=DATA["blend_path"])
if DATA.get("export_individual_parts"):
    _os.makedirs(DATA["parts_dir"], exist_ok=True)
    for _obj in created_objects:
        _safe_name = "".join(c if c.isalnum() or c in "_-." else "_" for c in _obj.name)
        _part_blend = _os.path.join(DATA["parts_dir"], f"{{_safe_name}}.blend")
        bpy.data.libraries.write(_part_blend, {{_obj}}, fake_user=True)
bpy.ops.export_scene.gltf(filepath=DATA["glb_path"], export_format="GLB")
bpy.context.scene.render.engine = "BLENDER_WORKBENCH"
bpy.context.scene.render.filepath = DATA["png_path"]
bpy.context.scene.render.resolution_x = 1280
bpy.context.scene.render.resolution_y = 720
bpy.ops.render.render(write_still=True)
print(json.dumps({{"ok": True, "objects_created": len(created_objects), "parts_dir": DATA["parts_dir"], "blend": DATA["blend_path"], "glb": DATA["glb_path"], "png": DATA["png_path"]}}))
"""
    return script, {"blend": blend_path, "glb": glb_path, "png": png_path, "parts_dir": str(parts_dir)}


async def run_script_via_blender_mcp(script: str) -> str:
    """Executa o script `bpy` diretamente no Blender ativo via `uvx blender-mcp`."""
    params = StdioServerParameters(command="uvx", args=["blender-mcp"])
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            res = await session.call_tool("execute_blender_code", arguments={"code": script})
            return "\n".join(getattr(c, "text", str(c)) for c in res.content)


def find_blender_executable() -> str:
    """Localiza `blender.exe` no PATH ou nas pastas padrão do Windows."""
    found = shutil.which("blender")
    if found:
        return found
    for base in (Path(r"C:\Program Files\Blender Foundation"), Path(r"C:\Program Files (x86)\Blender Foundation")):
        if base.exists():
            matches = sorted(base.glob("Blender*/blender.exe"), reverse=True)
            if matches:
                return str(matches[0])
    steam = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe")
    if steam.exists():
        return str(steam)
    return ""


def run_script_via_blender_background(script: str) -> str:
    """Executa o script `bpy` via `blender --background --python` caso o addon MCP não esteja aberto."""
    exe = find_blender_executable()
    if not exe:
        raise RuntimeError("Blender não encontrado no PATH nem em C:\\Program Files\\Blender Foundation.")
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
        tmp.write(script)
        tmp_path = tmp.name
    try:
        proc = subprocess.run([exe, "--background", "--python", tmp_path], capture_output=True, text=True, timeout=240)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout)
        return proc.stdout
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def build_cad_3d_in_blender(
    file_path: str,
    extrude_height: float = 1.5,
    beam_width: float = 0.08,
    export_dir: str = str(DEFAULT_EXPORT_DIR),
    use_background_fallback: bool = True,
) -> dict[str, Any]:
    """Pipeline completo: .dwg/.dxf -> geometria 3D -> Blender (.blend + .glb + _preview.png)."""
    payload = extract_full_geometry(file_path, extrude_height=extrude_height, beam_width=beam_width)
    script, outputs = build_scene_bpy_script(payload, export_dir=export_dir)
    try:
        mcp_out = asyncio.run(run_script_via_blender_mcp(script))
        mode = "blender_mcp"
    except Exception as mcp_exc:
        if not use_background_fallback:
            raise
        mcp_out = run_script_via_blender_background(script)
        mode = f"blender_background (mcp offline: {mcp_exc})"

    return {
        "ok": True,
        "mode": mode,
        "source_file": payload["source_file"],
        "scene_span_m": payload["scene_span_m"],
        "layers_count": len(payload["layers"]),
        "inserts_count": len(payload["inserts"]),
        "outputs": outputs,
        "blender_output": mcp_out.strip()[-1000:],
    }


BUILD_CAD_3D_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "build_cad_3d_in_blender",
        "description": "Gera a cena 3D completa de um arquivo .dwg ou .dxf no Blender (todas as layers, linhas, polilinhas, arcos, círculos e blocos INSERT com Custom Properties e PBR) e salva .blend, .glb e _preview.png dentro da pasta `exports/` do repositório.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Caminho do arquivo .dwg ou .dxf."},
                "extrude_height": {"type": "number", "description": "Altura de extrusão 3D em metros (padrão 1.5)."},
                "beam_width": {"type": "number", "description": "Espessura de perfis/linhas em metros (padrão 0.08)."},
                "export_dir": {"type": "string", "description": "Pasta de saída no repositório (padrão 'exports')."},
            },
            "required": ["file_path"],
        },
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Converte DWG/DXF em modelo 3D completo no Blender e exporta .blend/.glb/.png")
    parser.add_argument("file_path", help="Caminho do arquivo .dwg ou .dxf")
    parser.add_argument("--extrude-height", type=float, default=1.5)
    parser.add_argument("--beam-width", type=float, default=0.08)
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR))
    args = parser.parse_args()

    res = build_cad_3d_in_blender(
        file_path=args.file_path,
        extrude_height=args.extrude_height,
        beam_width=args.beam_width,
        export_dir=args.export_dir,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
