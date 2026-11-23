"""Unit tests for 3D asset validation rules, naming sanitization, and CLI parsing."""

from __future__ import annotations

import pytest

from blender_prep import parse_cli_args
from validator import MeshMetrics, audit_meshes, get_preset, sanitize_asset_name


def _clean_mesh(**overrides: object) -> MeshMetrics:
    base = {
        "name": "Fighter_Wing",
        "triangle_count": 2400,
        "vertex_count": 1300,
        "scale": (1.0, 1.0, 1.0),
        "rotation_deg": (0.0, 0.0, 0.0),
        "determinant": 1.0,
        "dimensions": (4.2, 1.8, 0.6),
        "bbox_center_local": (0.0, 0.0, 0.1),
        "material_slots": 1,
        "empty_material_slots": 0,
        "non_manifold_edges": 0,
    }
    base.update(overrides)
    return MeshMetrics(**base)  # type: ignore[arg-type]


def test_sanitize_asset_name() -> None:
    assert sanitize_asset_name("  MiG-29 Fuselage v2 ") == "MiG_29_Fuselage_v2"
    assert sanitize_asset_name("123_Wing") == "Asset_123_Wing"
    assert sanitize_asset_name("!!!") == "Asset_Mesh"


def test_audit_passes_clean_roblox_mesh() -> None:
    report = audit_meshes([_clean_mesh()], target="roblox")
    assert report.passed is True
    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.total_triangles == 2400
    assert "PASS" in report.to_markdown()


def test_audit_catches_roblox_poly_limit_and_negative_scale() -> None:
    bad_mesh = _clean_mesh(
        name="Heavy Plane!",
        triangle_count=14_500,
        scale=(-1.0, 1.5, 1.0),
        rotation_deg=(15.0, 0.0, 0.0),
        determinant=-1.5,
        bbox_center_local=(12.0, 0.0, 0.0),
        empty_material_slots=2,
        non_manifold_edges=4,
    )
    report = audit_meshes([bad_mesh], target="roblox")
    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert {
        "POLY_LIMIT_EXCEEDED",
        "NEGATIVE_SCALE_NORMALS",
        "UNAPPLIED_ROTATION",
        "FAR_ORIGIN",
        "EMPTY_MATERIAL_SLOTS",
        "NON_MANIFOLD_EDGES",
        "NAME_NOT_CLEAN",
    }.issubset(codes)

    # Same triangle count passes Unity's higher 65k budget when transforms are clean.
    unity_mesh = _clean_mesh(triangle_count=14_500)
    unity_report = audit_meshes([unity_mesh], target="unity")
    assert unity_report.passed is True


def test_audit_empty_scene_and_invalid_preset() -> None:
    empty_report = audit_meshes([], target="roblox")
    assert empty_report.passed is False
    assert empty_report.issues[0].code == "EMPTY_SCENE"

    with pytest.raises(ValueError):
        get_preset("godot")


def test_cli_arg_parsing_after_double_dash() -> None:
    args = parse_cli_args(
        ["--target", "roblox", "--fix", "--export", "out/plane.fbx", "--preview", "out/p.png"]
    )
    assert args.target == "roblox"
    assert args.fix is True
    assert args.export == "out/plane.fbx"
    assert args.preview == "out/p.png"
