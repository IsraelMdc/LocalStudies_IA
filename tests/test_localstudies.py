"""Testes unitários para o pipeline Samarco, DXF rico, Blender part builder, Cofre Obsidian, auto_allocator, router e lms_tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import ezdxf

from localstudies.auto_allocator import compute_allocation_plan
from localstudies.blender_part_builder import PartSpec, build_detailed_part_bpy_script, generate_detailed_part_script
from localstudies.dwg_pipeline import summarize_dxf
from localstudies.dxf_to_blender import build_scene_bpy_script, extract_full_geometry
from localstudies.lms_tools import LMS_TOOL_DISPATCH, lms_link_status
from localstudies.obsidian_vault import ingest_dxf_to_vault, init_vault, read_vault_note, update_part_blender_status
from localstudies.router import RouterConfig, get_role_profile, resolve_model_for_role
from localstudies.samarco_index import build_catalog, search_catalog


def test_build_and_search_samarco_catalog(tmp_path: Path) -> None:
    sample_dir = tmp_path / "Samarco"
    sub = sample_dir / "ZTK_U030905"
    sub.mkdir(parents=True)
    (sub / "planta_01.dwg").write_bytes(b"dwg-fake")
    (sub / "memorial.pdf").write_bytes(b"pdf-fake")

    index_file = tmp_path / "build" / "catalog.json"
    vault_dir = tmp_path / "vault_samarco"
    catalog = build_catalog(root_dir=sample_dir, output_path=index_file, vault_dir=vault_dir)

    assert catalog["total_files"] == 2
    assert catalog["by_extension"][".dwg"] == 1
    assert catalog["by_extension"][".pdf"] == 1
    assert (vault_dir / "00_Indice_e_Regras" / "Catalogo_Samarco.md").exists()
    assert (vault_dir / "00_Indice_e_Regras" / "Catalogo_ZTK.md").exists()

    dwg_hits = search_catalog(query="planta_01", extension=".dwg", index_path=index_file)
    assert len(dwg_hits) == 1
    assert dwg_hits[0]["name"] == "planta_01.dwg"


def test_summarize_dxf_extracts_rich_metadata_and_blocks(tmp_path: Path) -> None:
    dxf_path = tmp_path / "teste_rico.dxf"
    doc = ezdxf.new("R2018")
    doc.layers.add("ESTRUTURA_ACO", color=1)
    msp = doc.modelspace()

    msp.add_line((0, 0, 1.5), (10, 0, 1.5), dxfattribs={"layer": "ESTRUTURA_ACO", "thickness": 0.25})
    msp.add_lwpolyline(
        [(0, 0), (10, 0), (10, 5), (0, 5)],
        close=True,
        dxfattribs={"layer": "LAJE", "elevation": 3.0},
    )
    msp.add_text("COTA +3.00m", dxfattribs={"layer": "TEXTOS", "insert": (1.0, 1.0)})

    blk = doc.blocks.new(name="BOMBA_SAMARCO")
    blk.add_line((0, 0), (1, 1))
    ins = msp.add_blockref("BOMBA_SAMARCO", (1.2, 1.2, 3.0), dxfattribs={"layer": "ESTRUTURA_ACO"})
    ins.add_attrib("TAG", "BMB-001", (1.2, 1.2))
    ins.add_attrib("MATERIAL", "ACO_ASTM_A36", (1.2, 1.2))

    doc.saveas(str(dxf_path))

    summary = summarize_dxf(dxf_path)
    assert summary["layer_details"]["ESTRUTURA_ACO"]["aci_color"] == 1
    assert summary["bounding_box"]["width"] == 10.0
    assert summary["sample_lines"][0]["thickness"] == 0.25
    assert summary["sample_polylines"][0]["elevation"] == 3.0
    assert len(summary["block_instances"]) == 1
    inst = summary["block_instances"][0]
    assert inst["block_name"] == "BOMBA_SAMARCO"
    assert inst["attributes"]["TAG"] == "BMB-001"
    assert inst["attributes"]["MATERIAL"] == "ACO_ASTM_A36"
    assert "COTA +3.00m" in inst["nearby_notes"]


def test_blender_part_builder_includes_custom_props_and_pbr() -> None:
    spec = PartSpec(
        dwg_source="ZTK_U030905.dwg",
        dwg_handle="4F2A",
        dwg_layer="ESTRUTURA_ACO",
        part_tag="VIGA-V01",
        material_category="steel",
        aci_color=1,
        points_xy=[[0.0, 0.0], [2.0, 0.0], [2.0, 0.5], [0.0, 0.5]],
        extrude_height=4.0,
        wall_thickness=0.02,
        cad_attributes={"PERFIL": "W200x35.9", "PESO_KG": "143.6"},
        nearby_notes=["EL. +102.50m"],
    )
    script = build_detailed_part_bpy_script(spec)
    assert "Principled BSDF" in script
    assert "CAD_Bevel" in script
    assert "CAD_Solidify" in script
    assert "CAD_WeightedNormal" in script
    assert "W200x35.9" in script
    assert "ESTRUTURA_ACO__VIGA-V01__4F2A" in script

    tool_out = json.loads(
        generate_detailed_part_script(
            dwg_source="ZTK_U030905.dwg",
            dwg_handle="4F2A",
            dwg_layer="ESTRUTURA_ACO",
            part_tag="VIGA-V01",
        )
    )
    assert tool_out["ok"] is True


def test_obsidian_vault_ingest_and_status_update(tmp_path: Path) -> None:
    dxf_path = tmp_path / "ZTK_U030905.dxf"
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    blk = doc.blocks.new(name="CHUTE_01")
    blk.add_line((0, 0), (1, 1))
    ins = msp.add_blockref("CHUTE_01", (5.0, 5.0, 0.0), dxfattribs={"layer": "CALDEIRARIA"})
    ins.add_attrib("TAG", "CHT-101", (5.0, 5.0))
    doc.saveas(str(dxf_path))

    vault_dir = tmp_path / "vault_samarco"
    init_vault(vault_dir)
    res = ingest_dxf_to_vault(dxf_path, vault_dir=vault_dir)
    assert res["ok"] is True
    assert res["part_notes_created"] == 1

    part_note_path = Path(res["part_notes"][0])
    upd = json.loads(
        update_part_blender_status(
            part_note_name=part_note_path.stem,
            blender_object_name="CALDEIRARIA__CHT-101__HANDLE",
            status="modelado",
            notes="Extrudado com sucesso",
            vault_dir=vault_dir,
        )
    )
    assert upd["ok"] is True

    note_read = json.loads(read_vault_note(part_note_path.stem, vault_dir=vault_dir))
    assert note_read["ok"] is True
    assert "CALDEIRARIA__CHT-101__HANDLE" in note_read["content"]


def test_auto_allocator_respects_vram_budgets() -> None:
    sample_ls = [
        {
            "type": "llm",
            "modelKey": "qwen3-14b",
            "indexedModelIdentifier": "c9d558e8a7f1ab7610cba197267c4d38:lmstudio-community/Qwen3-14B",
            "deviceIdentifier": "c9d558e8a7f1ab7610cba197267c4d38",
            "sizeBytes": 9001753376,
            "vision": False,
            "trainedForToolUse": True,
        },
        {
            "type": "llm",
            "modelKey": "qwen2.5-vl-7b-instruct@q3_k_m",
            "indexedModelIdentifier": "3a54719e8256bdd028946faa0a585341:unsloth/Qwen2.5-VL-7B-Q3_K_M",
            "deviceIdentifier": "3a54719e8256bdd028946faa0a585341",
            "sizeBytes": 6511613131,
            "vision": True,
            "trainedForToolUse": False,
        },
        {
            "type": "llm",
            "modelKey": "qwen2.5-vl-7b-instruct@q4_k_m",
            "indexedModelIdentifier": "3a54719e8256bdd028946faa0a585341:unsloth/Qwen2.5-VL-7B-Q4_K_M",
            "deviceIdentifier": "3a54719e8256bdd028946faa0a585341",
            "sizeBytes": 7386295499,
            "vision": True,
            "trainedForToolUse": False,
        },
        {
            "type": "llm",
            "modelKey": "qwen3.8-14b-instruct-turbo-i1",
            "indexedModelIdentifier": "98c80cdab4b745a990b39b3c7662ff27:mradermacher/Qwen3.8-14B",
            "deviceIdentifier": "98c80cdab4b745a990b39b3c7662ff27",
            "sizeBytes": 8687851616,
            "vision": False,
            "trainedForToolUse": True,
        },
        {
            "type": "llm",
            "modelKey": "qwen3-4b",
            "indexedModelIdentifier": "98c80cdab4b745a990b39b3c7662ff27:lmstudio-community/Qwen3-4B",
            "deviceIdentifier": "98c80cdab4b745a990b39b3c7662ff27",
            "sizeBytes": 2497280704,
            "vision": False,
            "trainedForToolUse": True,
        },
        {
            "type": "embedding",
            "modelKey": "text-embedding-bge-m3@q8_0",
            "indexedModelIdentifier": "98c80cdab4b745a990b39b3c7662ff27:lm-kit/bge-m3-Q8_0",
            "deviceIdentifier": "98c80cdab4b745a990b39b3c7662ff27",
            "sizeBytes": 634553856,
        },
    ]

    plan = compute_allocation_plan(downloaded=sample_ls, loaded=[])
    by_role = {d.role: d for d in plan}

    assert by_role["coder_3d"].model_key == "qwen3-14b"
    assert by_role["vision_audit"].model_key == "qwen2.5-vl-7b-instruct@q3_k_m"
    assert by_role["embeddings_rag"].model_key == "text-embedding-bge-m3@q8_0"
    # Garante que na nuttec (7.6 GB) escolheu qwen3-4b (2.5 GB) e bloqueou o 14B (8.69 GB)
    assert by_role["fast_triage"].model_key == "qwen3-4b"


def test_router_fleet_profile_and_fallback() -> None:
    profile = get_role_profile("coder_3d")
    assert profile is not None
    assert profile["node_key"] == "berinjela"
    assert profile["vram_gb"] == 15.6

    cfg = RouterConfig(
        base_url="http://localhost:1234/v1",
        api_key="lm-studio",
        primary_model="qwen3-14b",
        vision_model="qwen2.5-vl-7b",
        embedding_model="text-embedding-bge-m3",
    )
    resolved = resolve_model_for_role(
        "coder_3d",
        config=cfg,
        available_models=["qwen2.5-coder-7b-instruct", "other-model"],
    )
    assert resolved == "qwen2.5-coder-7b-instruct"


def test_lms_tools_dispatch_mocked() -> None:
    assert "lms_load_model" in LMS_TOOL_DISPATCH
    assert "lms_apply_role_profile" in LMS_TOOL_DISPATCH
    with patch("localstudies.lms_tools.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Status: Online\nFound 4 devices"
        mock_run.return_value.stderr = ""
        payload = json.loads(lms_link_status())
        assert payload["ok"] is True
        assert "Found 4 devices" in payload["stdout"]


def test_dxf_to_blender_extracts_centered_geometry_and_exports(tmp_path: Path) -> None:
    dxf_path = tmp_path / "planta_teste.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    msp.add_line((10000, 5000), (20000, 5000), dxfattribs={"layer": "ESTRUTURA"})
    msp.add_circle((15000, 8000), 500, dxfattribs={"layer": "TUBULACAO"})
    doc.saveas(str(dxf_path))

    payload = extract_full_geometry(dxf_path)
    assert payload["unit_scale"] == 0.001
    assert "ESTRUTURA" in payload["layers"]
    assert "TUBULACAO" in payload["layers"]

    script, outputs = build_scene_bpy_script(payload, export_dir=tmp_path / "exports")
    assert "save_as_mainfile" in script
    assert "export_scene.gltf" in script
    assert outputs["glb"].endswith("planta_teste.glb")

