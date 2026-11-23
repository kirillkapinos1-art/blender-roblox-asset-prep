"""Blender (bpy) automation engine: audit, auto-fix, thumbnail render, and FBX/GLB export."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from validator import MeshMetrics, ValidationReport, audit_meshes, get_preset, sanitize_asset_name


def _require_bpy() -> tuple[Any, Any, Any]:
    try:
        import bmesh  # type: ignore
        import bpy  # type: ignore
        from mathutils import Vector  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "This module requires Blender's Python environment (bpy, bmesh, mathutils). "
            "Run via: blender --background <file.blend> --python blender_prep.py -- ..."
        ) from exc
    return bpy, bmesh, Vector


def get_target_meshes(bpy: Any, *, selected_only: bool = False) -> list[Any]:
    """Return visible mesh objects from current selection or the active scene."""
    pool = bpy.context.selected_objects if selected_only else bpy.context.scene.objects
    return [obj for obj in pool if obj.type == "MESH"]


def collect_mesh_metrics(objects: list[Any]) -> list[MeshMetrics]:
    """Extract geometric and transform telemetry from Blender mesh objects."""
    bpy, bmesh, Vector = _require_bpy()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    metrics: list[MeshMetrics] = []

    for obj in objects:
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        try:
            mesh.calc_loop_triangles()
            tri_count = len(mesh.loop_triangles)
            vert_count = len(mesh.vertices)

            bm = bmesh.new()
            bm.from_mesh(mesh)
            non_manifold = sum(1 for edge in bm.edges if not edge.is_manifold)
            bm.free()
        finally:
            eval_obj.to_mesh_clear()

        corners = [Vector(corner) for corner in obj.bound_box]
        bbox_center = sum(corners, Vector((0.0, 0.0, 0.0))) / 8.0
        det = float(obj.matrix_world.to_3x3().determinant())
        rot_deg = tuple(round(math.degrees(a), 3) for a in obj.rotation_euler)
        empty_slots = sum(1 for slot in obj.material_slots if slot.material is None)

        metrics.append(
            MeshMetrics(
                name=obj.name,
                triangle_count=tri_count,
                vertex_count=vert_count,
                scale=(
                    round(float(obj.scale.x), 4),
                    round(float(obj.scale.y), 4),
                    round(float(obj.scale.z), 4),
                ),
                rotation_deg=(rot_deg[0], rot_deg[1], rot_deg[2]),
                determinant=round(det, 6),
                dimensions=(
                    round(float(obj.dimensions.x), 4),
                    round(float(obj.dimensions.y), 4),
                    round(float(obj.dimensions.z), 4),
                ),
                bbox_center_local=(
                    round(float(bbox_center.x), 4),
                    round(float(bbox_center.y), 4),
                    round(float(bbox_center.z), 4),
                ),
                material_slots=len(obj.material_slots),
                empty_material_slots=empty_slots,
                non_manifold_edges=non_manifold,
            )
        )
    return metrics


def fix_mesh_objects(
    objects: list[Any],
    *,
    center_origin: bool = False,
    sanitize_names: bool = True,
) -> dict[str, int]:
    """Apply scale/rotation, recalculate outward normals, prune empty materials, and clean names."""
    bpy, bmesh, _ = _require_bpy()
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    summary = {
        "transforms_applied": 0,
        "normals_recalculated": 0,
        "empty_slots_removed": 0,
        "renamed": 0,
        "origins_centered": 0,
    }

    for obj in objects:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        summary["transforms_applied"] += 1

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        summary["normals_recalculated"] += 1

        for idx in range(len(obj.material_slots) - 1, -1, -1):
            if obj.material_slots[idx].material is None:
                obj.active_material_index = idx
                bpy.ops.object.material_slot_remove()
                summary["empty_slots_removed"] += 1

        if center_origin:
            bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
            summary["origins_centered"] += 1

        if sanitize_names:
            clean = sanitize_asset_name(obj.name)
            if clean != obj.name:
                obj.name = clean
            if obj.data.name != f"{clean}_Mesh":
                obj.data.name = f"{clean}_Mesh"
            summary["renamed"] += 1

    return summary


def export_asset(
    objects: list[Any],
    output_path: str | Path,
    *,
    fmt: str = "fbx",
    target: str = "roblox",
) -> Path:
    """Export selected mesh objects as FBX or GLB with engine-appropriate scaling."""
    bpy, _, _ = _require_bpy()
    preset = get_preset(target)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)

    fmt_lower = fmt.strip().lower()
    if fmt_lower == "fbx":
        bpy.ops.export_scene.fbx(
            filepath=str(out),
            use_selection=True,
            apply_unit_scale=True,
            global_scale=preset.fbx_scale,
            bake_space_transform=True,
            mesh_smooth_type="FACE",
            use_mesh_modifiers=True,
        )
    elif fmt_lower in ("glb", "gltf"):
        bpy.ops.export_scene.gltf(
            filepath=str(out),
            use_selection=True,
            export_format="GLB" if fmt_lower == "glb" else "GLTF_SEPARATE",
        )
    else:
        raise ValueError(f"Unsupported export format: {fmt!r}")
    return out


def render_preview_thumbnail(
    objects: list[Any],
    output_png: str | Path,
    *,
    width: int = 1024,
    height: int = 1024,
) -> Path:
    """Frame a temporary camera and 3-point rig around objects to render a PNG preview."""
    bpy, _, Vector = _require_bpy()
    if not objects:
        raise ValueError("Cannot render preview of empty object list.")

    world_pts: list[Any] = []
    for obj in objects:
        for corner in obj.bound_box:
            world_pts.append(obj.matrix_world @ Vector(corner))

    min_v = Vector((min(p.x for p in world_pts), min(p.y for p in world_pts), min(p.z for p in world_pts)))
    max_v = Vector((max(p.x for p in world_pts), max(p.y for p in world_pts), max(p.z for p in world_pts)))
    center = (min_v + max_v) * 0.5
    radius = max((max_v - min_v).length * 0.5, 0.5)

    scene = bpy.context.scene
    cam_data = bpy.data.cameras.new("PrepPreviewCam")
    cam_obj = bpy.data.objects.new("PrepPreviewCam", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = center + Vector((radius * 2.1, -radius * 2.1, radius * 1.1))
    direction = (center - cam_obj.location).normalized()
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    key_data = bpy.data.lights.new("PrepKeyLight", type="AREA")
    key_data.energy = radius * radius * 60.0
    key_obj = bpy.data.objects.new("PrepKeyLight", key_data)
    scene.collection.objects.link(key_obj)
    key_obj.location = center + Vector((radius * 2.5, -radius * 1.5, radius * 3.0))

    prev_cam = scene.camera
    out = Path(output_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        scene.camera = cam_obj
        scene.render.filepath = str(out)
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)
    finally:
        scene.camera = prev_cam
        bpy.data.objects.remove(cam_obj, do_unlink=True)
        bpy.data.cameras.remove(cam_data, do_unlink=True)
        bpy.data.objects.remove(key_obj, do_unlink=True)
        bpy.data.lights.remove(key_data, do_unlink=True)
    return out


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse arguments passed after `--` to Blender's background Python runner."""
    if argv is None:
        raw = sys.argv
        argv = raw[raw.index("--") + 1 :] if "--" in raw else []

    parser = argparse.ArgumentParser(
        description="Audit, auto-fix, and export Blender assets for Roblox/Unity/Unreal."
    )
    parser.add_argument("--target", default="roblox", choices=("roblox", "unity", "unreal"))
    parser.add_argument("--fix", action="store_true", help="Auto-fix transforms, normals, and slots")
    parser.add_argument("--center-origin", action="store_true", help="Center origin to geometry bounds")
    parser.add_argument("--export", default="", help="Output .fbx or .glb file path")
    parser.add_argument("--preview", default="", help="Optional output preview .png path")
    parser.add_argument("--report", default="", help="Optional JSON validation report path")
    parser.add_argument("--selected-only", action="store_true")
    return parser.parse_args(argv)


def run_pipeline(args: argparse.Namespace) -> ValidationReport:
    """Execute the full Blender asset preparation pipeline."""
    bpy, _, _ = _require_bpy()
    meshes = get_target_meshes(bpy, selected_only=args.selected_only)

    if args.fix and meshes:
        fix_summary = fix_mesh_objects(meshes, center_origin=args.center_origin)
        print("[ASSET PREP FIX]", json.dumps(fix_summary, ensure_ascii=False))

    metrics = collect_mesh_metrics(meshes)
    report = audit_meshes(metrics, target=args.target)
    print(report.to_markdown())

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if args.export and meshes:
        fmt = Path(args.export).suffix.lstrip(".") or "fbx"
        exported = export_asset(meshes, args.export, fmt=fmt, target=args.target)
        print(f"[EXPORTED] {exported}")

    if args.preview and meshes:
        png = render_preview_thumbnail(meshes, args.preview)
        print(f"[PREVIEW] {png}")

    return report


if __name__ == "__main__":
    parsed = parse_cli_args()
    final_report = run_pipeline(parsed)
    if not final_report.passed:
        raise SystemExit(2)
