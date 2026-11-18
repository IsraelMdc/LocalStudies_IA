"""Gerador de scripts `bpy` padronizados com Custom Properties completas, materiais PBR e chanfro técnico."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Mapa básico AutoCAD Color Index (ACI) -> RGBA linear para materiais PBR no Blender
ACI_COLOR_MAP: dict[int, tuple[float, float, float, float]] = {
    1: (0.85, 0.12, 0.12, 1.0),  # Red
    2: (0.90, 0.82, 0.15, 1.0),  # Yellow
    3: (0.15, 0.78, 0.25, 1.0),  # Green
    4: (0.15, 0.78, 0.85, 1.0),  # Cyan
    5: (0.18, 0.35, 0.88, 1.0),  # Blue
    6: (0.82, 0.18, 0.78, 1.0),  # Magenta
    7: (0.78, 0.80, 0.82, 1.0),  # White / Light Steel
    8: (0.42, 0.44, 0.46, 1.0),  # Dark Grey
    9: (0.62, 0.64, 0.66, 1.0),  # Light Grey
}

MATERIAL_PBR_PRESETS: dict[str, dict[str, float]] = {
    "steel": {"metallic": 0.85, "roughness": 0.32},
    "concrete": {"metallic": 0.0, "roughness": 0.88},
    "piping": {"metallic": 0.70, "roughness": 0.28},
    "equipment": {"metallic": 0.55, "roughness": 0.40},
    "generic": {"metallic": 0.15, "roughness": 0.50},
}


@dataclass(frozen=True)
class PartSpec:
    dwg_source: str
    dwg_handle: str
    dwg_layer: str
    part_tag: str
    entity_type: str = "LWPOLYLINE"
    system_collection: str = "Samarco_Geral"
    material_category: str = "steel"
    aci_color: int = 7
    points_xy: list[list[float]] = field(default_factory=list)
    location_xyz: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    dimensions_xyz: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    extrude_height: float = 3.0
    wall_thickness: float = 0.0
    bevel_width: float = 0.008
    cad_attributes: dict[str, Any] = field(default_factory=dict)
    nearby_notes: list[str] = field(default_factory=list)

    @property
    def object_name(self) -> str:
        safe_layer = "".join(c if c.isalnum() or c in "_-" else "_" for c in self.dwg_layer)
        safe_tag = "".join(c if c.isalnum() or c in "_-" else "_" for c in self.part_tag)
        safe_handle = "".join(c if c.isalnum() else "" for c in self.dwg_handle) or "000"
        return f"{safe_layer}__{safe_tag}__{safe_handle}"


def build_detailed_part_bpy_script(spec: PartSpec) -> str:
    """Gera código Python `bpy` que cria a peça 3D, aplica PBR + Bevel/Solidify e grava todas as Custom Properties."""
    rgba = ACI_COLOR_MAP.get(abs(spec.aci_color) % 256, ACI_COLOR_MAP[7])
    pbr = MATERIAL_PBR_PRESETS.get(spec.material_category.lower(), MATERIAL_PBR_PRESETS["generic"])

    custom_props = {
        "dwg_source": spec.dwg_source,
        "dwg_handle": spec.dwg_handle,
        "dwg_layer": spec.dwg_layer,
        "dwg_type": spec.entity_type,
        "part_tag": spec.part_tag,
        "material_spec": spec.material_category,
        "aci_color": spec.aci_color,
        "dimensions_m": json.dumps(spec.dimensions_xyz, ensure_ascii=False),
        "extrude_height_m": spec.extrude_height,
        "wall_thickness_m": spec.wall_thickness,
        "elevation_m": spec.location_xyz[2] if len(spec.location_xyz) >= 3 else 0.0,
        "cad_attribs_json": json.dumps(spec.cad_attributes, ensure_ascii=False),
        "nearby_notes": " | ".join(spec.nearby_notes),
    }

    payload_json = json.dumps(
        {
            "obj_name": spec.object_name,
            "root_col": spec.dwg_source.replace(".dwg", "").replace(".dxf", ""),
            "sys_col": spec.system_collection,
            "layer_col": spec.dwg_layer,
            "mat_name": f"MAT_{spec.dwg_layer}_{spec.material_category}_ACI{spec.aci_color}",
            "rgba": list(rgba),
            "metallic": pbr["metallic"],
            "roughness": pbr["roughness"],
            "points_xy": spec.points_xy,
            "location_xyz": spec.location_xyz,
            "dimensions_xyz": spec.dimensions_xyz,
            "extrude_height": spec.extrude_height,
            "wall_thickness": spec.wall_thickness,
            "bevel_width": spec.bevel_width,
            "custom_props": custom_props,
        },
        ensure_ascii=False,
    )

    return f"""import json
import bpy
import bmesh

DATA = json.loads({payload_json!r})

def ensure_collection(name, parent=None):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        target_parent = parent if parent is not None else bpy.context.scene.collection
        target_parent.children.link(col)
    return col

root_col = ensure_collection(DATA["root_col"])
sys_col = ensure_collection(DATA["sys_col"], root_col)
layer_col = ensure_collection(DATA["layer_col"], sys_col)

# Material PBR Principled BSDF com cor ACI e propriedades físicas
mat = bpy.data.materials.get(DATA["mat_name"])
if mat is None:
    mat = bpy.data.materials.new(name=DATA["mat_name"])
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = tuple(DATA["rgba"])
        bsdf.inputs["Metallic"].default_value = float(DATA["metallic"])
        bsdf.inputs["Roughness"].default_value = float(DATA["roughness"])
    mat.diffuse_color = tuple(DATA["rgba"])

mesh = bpy.data.meshes.new(DATA["obj_name"] + "_Mesh")
bm = bmesh.new()

pts = DATA["points_xy"]
if pts and len(pts) >= 3:
    verts = [bm.verts.new((float(p[0]), float(p[1]), 0.0)) for p in pts]
    face = bm.faces.new(verts)
    if float(DATA["extrude_height"]) > 0:
        extruded = bmesh.ops.extrude_face_region(bm, geom=[face])
        extruded_verts = [v for v in extruded["geom"] if isinstance(v, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, vec=(0.0, 0.0, float(DATA["extrude_height"])), verts=extruded_verts)
else:
    bmesh.ops.create_cube(bm, size=1.0)
    dx, dy, dz = [float(x) for x in DATA["dimensions_xyz"]]
    bmesh.ops.scale(bm, vec=(dx, dy, dz), verts=bm.verts)

bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
bm.to_mesh(mesh)
bm.free()

obj = bpy.data.objects.new(DATA["obj_name"], mesh)
obj.location = tuple(float(c) for c in DATA["location_xyz"])
layer_col.objects.link(obj)

if len(obj.data.materials) == 0:
    obj.data.materials.append(mat)
else:
    obj.data.materials[0] = mat

# Modificadores não-destrutivos para detalhamento visual 3D
if float(DATA["wall_thickness"]) > 0:
    sol = obj.modifiers.new(name="CAD_Solidify", type="SOLIDIFY")
    sol.thickness = float(DATA["wall_thickness"])
    sol.offset = 0.0

if float(DATA["bevel_width"]) > 0:
    bev = obj.modifiers.new(name="CAD_Bevel", type="BEVEL")
    bev.width = float(DATA["bevel_width"])
    bev.segments = 2
    bev.harden_normals = True

wn = obj.modifiers.new(name="CAD_WeightedNormal", type="WEIGHTED_NORMAL")
wn.keep_sharp = True

# Grava todas as Custom Properties de engenharia no Objeto e na Malha
for k, v in DATA["custom_props"].items():
    obj[k] = v
    obj.data[k] = v

# Ajusta Clip End das Viewports 3D para desenhos industriais grandes e seleciona o objeto criado
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        for space in area.spaces:
            if space.type == "VIEW_3D" and space.clip_end < 10000.0:
                space.clip_end = 10000.0
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
"""


def generate_detailed_part_script(
    dwg_source: str,
    dwg_handle: str,
    dwg_layer: str,
    part_tag: str,
    entity_type: str = "LWPOLYLINE",
    system_collection: str = "Samarco_Geral",
    material_category: str = "steel",
    aci_color: int = 7,
    points_xy: list[list[float]] | None = None,
    location_xyz: list[float] | None = None,
    dimensions_xyz: list[float] | None = None,
    extrude_height: float = 3.0,
    wall_thickness: float = 0.0,
    bevel_width: float = 0.008,
    cad_attributes: dict[str, Any] | None = None,
    nearby_notes: list[str] | None = None,
) -> str:
    spec = PartSpec(
        dwg_source=dwg_source,
        dwg_handle=dwg_handle,
        dwg_layer=dwg_layer,
        part_tag=part_tag,
        entity_type=entity_type,
        system_collection=system_collection,
        material_category=material_category,
        aci_color=aci_color,
        points_xy=points_xy or [],
        location_xyz=location_xyz or [0.0, 0.0, 0.0],
        dimensions_xyz=dimensions_xyz or [1.0, 1.0, 1.0],
        extrude_height=extrude_height,
        wall_thickness=wall_thickness,
        bevel_width=bevel_width,
        cad_attributes=cad_attributes or {},
        nearby_notes=nearby_notes or [],
    )
    script = build_detailed_part_bpy_script(spec)
    return json.dumps(
        {
            "ok": True,
            "object_name": spec.object_name,
            "bpy_script": script,
        },
        ensure_ascii=False,
    )


PART_BUILDER_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_detailed_part_script",
        "description": "Gera um script Python `bpy` padronizado para criar uma peça 3D no Blender com todas as Custom Properties do DWG, hierarquia de Collections, material PBR (cor ACI) e modificadores Bevel/Solidify/WeightedNormal.",
        "parameters": {
            "type": "object",
            "properties": {
                "dwg_source": {"type": "string", "description": "Nome do arquivo DWG/DXF de origem."},
                "dwg_handle": {"type": "string", "description": "Handle hexadecimal único da entidade no CAD."},
                "dwg_layer": {"type": "string", "description": "Nome da layer original do DWG."},
                "part_tag": {"type": "string", "description": "TAG do equipamento, nome do bloco ou identificador da peça."},
                "entity_type": {"type": "string", "description": "Tipo CAD (LWPOLYLINE, INSERT, LINE, 3DFACE)."},
                "system_collection": {"type": "string", "description": "Subsistema ou disciplina (ex: Britagem, Estrutura_Metalica)."},
                "material_category": {
                    "type": "string",
                    "description": "Categoria PBR: 'steel', 'concrete', 'piping', 'equipment' ou 'generic'.",
                },
                "aci_color": {"type": "integer", "description": "Cor ACI da layer (1..255, padrão 7)."},
                "points_xy": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Lista de vértices 2D [[x, y], ...] do contorno da peça.",
                },
                "location_xyz": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Posição 3D [x, y, z] da peça em metros.",
                },
                "dimensions_xyz": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Dimensões [largura, profundidade, altura] caso não haja points_xy.",
                },
                "extrude_height": {"type": "number", "description": "Altura de extrusão no eixo Z (metros)."},
                "wall_thickness": {"type": "number", "description": "Espessura de parede/chapa para modificador Solidify (0 para desativar)."},
                "bevel_width": {"type": "number", "description": "Largura do chanfro técnico Bevel em metros (padrão 0.008)."},
                "cad_attributes": {"type": "object", "description": "Dicionário com atributos ATTRIB e XDATA do bloco CAD."},
                "nearby_notes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Textos e cotas próximos à peça no desenho 2D.",
                },
            },
            "required": ["dwg_source", "dwg_handle", "dwg_layer", "part_tag"],
        },
    },
}
