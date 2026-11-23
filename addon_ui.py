"""Blender 3D Viewport sidebar add-on wrapping validator and blender_prep."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import bpy  # type: ignore

from blender_prep import (
    collect_mesh_metrics,
    export_asset,
    fix_mesh_objects,
    get_target_meshes,
    render_preview_thumbnail,
)
from validator import audit_meshes

bl_info = {
    "name": "Roblox & Game Engine Asset Prep",
    "author": "Kirill Kapinos",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar (N) > Asset Prep",
    "description": "Audit, auto-fix transforms/normals, and export game-ready FBX/GLB assets",
    "category": "Import-Export",
}


def _store_report_on_scene(scene: Any, report: Any) -> None:
    scene.asset_prep_summary = (
        f"{'PASS' if report.passed else 'FAIL'} | "
        f"Meshes: {report.mesh_count} | Tris: {report.total_triangles:,} | "
        f"Err: {report.error_count} | Warn: {report.warning_count}"
    )


class ASSET_OT_audit_scene(bpy.types.Operator):
    """Audit active mesh objects against target game-engine limits."""

    bl_idname = "asset_prep.audit_scene"
    bl_label = "Audit Scene"

    def execute(self, context: Any) -> set[str]:
        meshes = get_target_meshes(bpy, selected_only=context.scene.asset_prep_selected_only)
        report = audit_meshes(
            collect_mesh_metrics(meshes),
            target=context.scene.asset_prep_target,
        )
        _store_report_on_scene(context.scene, report)
        level = "INFO" if report.passed else "WARNING"
        self.report({level}, context.scene.asset_prep_summary)
        return {"FINISHED"}


class ASSET_OT_fix_scene(bpy.types.Operator):
    """Apply scale/rotation, recalculate normals, remove empty material slots, and clean names."""

    bl_idname = "asset_prep.fix_scene"
    bl_label = "Auto-Fix Meshes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        meshes = get_target_meshes(bpy, selected_only=context.scene.asset_prep_selected_only)
        summary = fix_mesh_objects(
            meshes,
            center_origin=context.scene.asset_prep_center_origin,
        )
        report = audit_meshes(
            collect_mesh_metrics(meshes),
            target=context.scene.asset_prep_target,
        )
        _store_report_on_scene(context.scene, report)
        self.report(
            {"INFO"},
            f"Fixed {summary['transforms_applied']} mesh(es); {context.scene.asset_prep_summary}",
        )
        return {"FINISHED"}


class ASSET_OT_export_bundle(bpy.types.Operator):
    """Export validated asset as FBX/GLB and optionally render a PNG preview."""

    bl_idname = "asset_prep.export_bundle"
    bl_label = "Export FBX / GLB"

    def execute(self, context: Any) -> set[str]:
        meshes = get_target_meshes(bpy, selected_only=context.scene.asset_prep_selected_only)
        if not meshes:
            self.report({"ERROR"}, "No mesh objects found to export.")
            return {"CANCELLED"}

        out_dir = Path(bpy.path.abspath(context.scene.asset_prep_export_dir or "//export"))
        fmt = context.scene.asset_prep_format
        stem = meshes[0].name
        asset_path = export_asset(
            meshes,
            out_dir / f"{stem}.{fmt}",
            fmt=fmt,
            target=context.scene.asset_prep_target,
        )
        if context.scene.asset_prep_render_preview:
            render_preview_thumbnail(meshes, out_dir / f"{stem}_preview.png")

        self.report({"INFO"}, f"Exported to {asset_path}")
        return {"FINISHED"}


class VIEW3D_PT_roblox_asset_prep(bpy.types.Panel):
    """Sidebar panel for 1-click Roblox/Unity/Unreal asset preparation."""

    bl_label = "Asset Prep"
    bl_idname = "VIEW3D_PT_roblox_asset_prep"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Asset Prep"

    def draw(self, context: Any) -> None:
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "asset_prep_target")
        layout.prop(scene, "asset_prep_selected_only")
        layout.prop(scene, "asset_prep_center_origin")
        layout.separator()
        layout.operator("asset_prep.audit_scene", icon="CHECKMARK")
        layout.operator("asset_prep.fix_scene", icon="MODIFIER")
        if scene.asset_prep_summary:
            box = layout.box()
            box.label(text=scene.asset_prep_summary)
        layout.separator()
        layout.prop(scene, "asset_prep_format")
        layout.prop(scene, "asset_prep_export_dir")
        layout.prop(scene, "asset_prep_render_preview")
        layout.operator("asset_prep.export_bundle", icon="EXPORT")


CLASSES = (
    ASSET_OT_audit_scene,
    ASSET_OT_fix_scene,
    ASSET_OT_export_bundle,
    VIEW3D_PT_roblox_asset_prep,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.asset_prep_target = bpy.props.EnumProperty(
        name="Target Engine",
        items=[
            ("roblox", "Roblox Studio", "10k tri limit & 0.01 FBX scale"),
            ("unity", "Unity", "65k tri limit & 1.0 FBX scale"),
            ("unreal", "Unreal Engine", "100k tri limit & 1.0 FBX scale"),
        ],
        default="roblox",
    )
    bpy.types.Scene.asset_prep_selected_only = bpy.props.BoolProperty(
        name="Selected Only", default=False
    )
    bpy.types.Scene.asset_prep_center_origin = bpy.props.BoolProperty(
        name="Center Origin", default=False
    )
    bpy.types.Scene.asset_prep_format = bpy.props.EnumProperty(
        name="Format",
        items=[("fbx", "FBX", "Export .fbx"), ("glb", "GLB", "Export .glb")],
        default="fbx",
    )
    bpy.types.Scene.asset_prep_export_dir = bpy.props.StringProperty(
        name="Output Folder", subtype="DIR_PATH", default="//export"
    )
    bpy.types.Scene.asset_prep_render_preview = bpy.props.BoolProperty(
        name="Render PNG Preview", default=True
    )
    bpy.types.Scene.asset_prep_summary = bpy.props.StringProperty(default="")


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    for prop in (
        "asset_prep_target",
        "asset_prep_selected_only",
        "asset_prep_center_origin",
        "asset_prep_format",
        "asset_prep_export_dir",
        "asset_prep_render_preview",
        "asset_prep_summary",
    ):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)


if __name__ == "__main__":
    register()
