"""Platform-agnostic 3D mesh validation rules for Roblox Studio, Unity, and Unreal Engine."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Literal

Severity = Literal["ERROR", "WARNING", "INFO"]
TargetName = Literal["roblox", "unity", "unreal"]

_INVALID_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


@dataclass(frozen=True, slots=True)
class PlatformPreset:
    """Geometry, transform, and export limits for a target game engine."""

    name: TargetName
    max_tris_per_mesh: int
    warn_tris_per_mesh: int
    max_scene_tris: int
    max_dimension_m: float
    fbx_scale: float
    max_origin_offset_m: float


PLATFORM_PRESETS: dict[str, PlatformPreset] = {
    "roblox": PlatformPreset(
        name="roblox",
        max_tris_per_mesh=10_000,
        warn_tris_per_mesh=6_500,
        max_scene_tris=50_000,
        max_dimension_m=2048.0,
        fbx_scale=0.01,
        max_origin_offset_m=5.0,
    ),
    "unity": PlatformPreset(
        name="unity",
        max_tris_per_mesh=65_000,
        warn_tris_per_mesh=25_000,
        max_scene_tris=200_000,
        max_dimension_m=500.0,
        fbx_scale=1.0,
        max_origin_offset_m=5.0,
    ),
    "unreal": PlatformPreset(
        name="unreal",
        max_tris_per_mesh=100_000,
        warn_tris_per_mesh=50_000,
        max_scene_tris=500_000,
        max_dimension_m=2000.0,
        fbx_scale=1.0,
        max_origin_offset_m=5.0,
    ),
}


@dataclass(frozen=True, slots=True)
class MeshMetrics:
    """Extracted geometric and transform telemetry for a single Blender mesh object."""

    name: str
    triangle_count: int
    vertex_count: int
    scale: tuple[float, float, float]
    rotation_deg: tuple[float, float, float]
    determinant: float
    dimensions: tuple[float, float, float]
    bbox_center_local: tuple[float, float, float]
    material_slots: int
    empty_material_slots: int
    non_manifold_edges: int = 0


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Single validation diagnostic emitted during asset auditing."""

    severity: Severity
    code: str
    object_name: str
    message: str
    auto_fixable: bool = False


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Full audit summary across all inspected meshes."""

    target: str
    mesh_count: int
    total_triangles: int
    issues: tuple[ValidationIssue, ...]

    @property
    def error_count(self) -> int:
        return sum(1 for item in self.issues if item.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for item in self.issues if item.severity == "WARNING")

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "mesh_count": self.mesh_count,
            "total_triangles": self.total_triangles,
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [asdict(item) for item in self.issues],
        }

    def to_markdown(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [
            f"# 3D Asset Validation Report ({self.target.upper()}) — {status}",
            "",
            f"- **Meshes inspected:** {self.mesh_count}",
            f"- **Total triangles:** {self.total_triangles:,}",
            f"- **Errors:** {self.error_count} | **Warnings:** {self.warning_count}",
        ]
        if self.issues:
            lines.append("\n## Diagnostics")
            for issue in self.issues:
                fix_tag = " *(auto-fixable)*" if issue.auto_fixable else ""
                lines.append(
                    f"- **[{issue.severity}]** `{issue.object_name}` ({issue.code}): "
                    f"{issue.message}{fix_tag}"
                )
        else:
            lines.append("\nNo issues detected. Asset is export-ready.")
        return "\n".join(lines)


def get_preset(target: str) -> PlatformPreset:
    """Return the PlatformPreset matching target ('roblox', 'unity', or 'unreal')."""
    key = target.strip().lower()
    if key not in PLATFORM_PRESETS:
        supported = ", ".join(sorted(PLATFORM_PRESETS))
        raise ValueError(f"Unsupported target {target!r}. Choose one of: {supported}")
    return PLATFORM_PRESETS[key]


def sanitize_asset_name(name: str) -> str:
    """Convert arbitrary Blender object names into clean ASCII asset identifiers."""
    cleaned = _INVALID_NAME_RE.sub("_", name.strip())
    cleaned = _MULTI_UNDERSCORE_RE.sub("_", cleaned).strip("_")
    if not cleaned:
        return "Asset_Mesh"
    if cleaned[0].isdigit():
        return f"Asset_{cleaned}"
    return cleaned


def _approx_equal_vec(
    vec: tuple[float, float, float], expected: float, tol: float = 1e-3
) -> bool:
    return all(abs(axis - expected) <= tol for axis in vec)


def audit_meshes(
    meshes: Sequence[MeshMetrics], *, target: str = "roblox"
) -> ValidationReport:
    """Run geometry, transform, material, and naming checks for the target engine."""
    preset = get_preset(target)
    issues: list[ValidationIssue] = []

    if not meshes:
        issues.append(
            ValidationIssue(
                severity="ERROR",
                code="EMPTY_SCENE",
                object_name="<scene>",
                message="No mesh objects found to validate or export.",
            )
        )
        return ValidationReport(
            target=preset.name,
            mesh_count=0,
            total_triangles=0,
            issues=tuple(issues),
        )

    total_tris = 0
    for mesh in meshes:
        total_tris += mesh.triangle_count

        if mesh.triangle_count == 0:
            issues.append(
                ValidationIssue(
                    severity="ERROR",
                    code="ZERO_TRIANGLES",
                    object_name=mesh.name,
                    message="Mesh has 0 triangles.",
                )
            )
        elif mesh.triangle_count > preset.max_tris_per_mesh:
            issues.append(
                ValidationIssue(
                    severity="ERROR",
                    code="POLY_LIMIT_EXCEEDED",
                    object_name=mesh.name,
                    message=(
                        f"Mesh has {mesh.triangle_count:,} triangles, exceeding "
                        f"{preset.name} limit of {preset.max_tris_per_mesh:,}."
                    ),
                )
            )
        elif mesh.triangle_count > preset.warn_tris_per_mesh:
            issues.append(
                ValidationIssue(
                    severity="WARNING",
                    code="POLY_COUNT_HIGH",
                    object_name=mesh.name,
                    message=(
                        f"Mesh has {mesh.triangle_count:,} triangles "
                        f"(recommended <= {preset.warn_tris_per_mesh:,} for {preset.name})."
                    ),
                )
            )

        if mesh.determinant < 0:
            issues.append(
                ValidationIssue(
                    severity="ERROR",
                    code="NEGATIVE_SCALE_NORMALS",
                    object_name=mesh.name,
                    message="Negative transform determinant detected; normals will render inside-out.",
                    auto_fixable=True,
                )
            )
        elif not _approx_equal_vec(mesh.scale, 1.0):
            issues.append(
                ValidationIssue(
                    severity="WARNING",
                    code="UNAPPLIED_SCALE",
                    object_name=mesh.name,
                    message=f"Object scale is {mesh.scale} instead of (1.0, 1.0, 1.0).",
                    auto_fixable=True,
                )
            )

        if not _approx_equal_vec(mesh.rotation_deg, 0.0, tol=0.05):
            issues.append(
                ValidationIssue(
                    severity="WARNING",
                    code="UNAPPLIED_ROTATION",
                    object_name=mesh.name,
                    message=f"Object has unapplied rotation {mesh.rotation_deg}°.",
                    auto_fixable=True,
                )
            )

        max_dim = max(mesh.dimensions) if mesh.dimensions else 0.0
        if max_dim > preset.max_dimension_m:
            issues.append(
                ValidationIssue(
                    severity="ERROR",
                    code="OVERSIZED_BOUNDING_BOX",
                    object_name=mesh.name,
                    message=f"Max dimension {max_dim:.2f}m exceeds {preset.max_dimension_m:.0f}m.",
                )
            )

        origin_dist = math.sqrt(sum(c * c for c in mesh.bbox_center_local))
        if origin_dist > preset.max_origin_offset_m:
            issues.append(
                ValidationIssue(
                    severity="WARNING",
                    code="FAR_ORIGIN",
                    object_name=mesh.name,
                    message=(
                        f"Geometry center is {origin_dist:.2f}m away from object origin; "
                        "consider centering origin."
                    ),
                    auto_fixable=True,
                )
            )

        if mesh.empty_material_slots > 0:
            issues.append(
                ValidationIssue(
                    severity="WARNING",
                    code="EMPTY_MATERIAL_SLOTS",
                    object_name=mesh.name,
                    message=f"Found {mesh.empty_material_slots} empty material slot(s).",
                    auto_fixable=True,
                )
            )

        if mesh.non_manifold_edges > 0:
            issues.append(
                ValidationIssue(
                    severity="WARNING",
                    code="NON_MANIFOLD_EDGES",
                    object_name=mesh.name,
                    message=f"Mesh has {mesh.non_manifold_edges} non-manifold edge(s).",
                )
            )

        if sanitize_asset_name(mesh.name) != mesh.name:
            issues.append(
                ValidationIssue(
                    severity="INFO",
                    code="NAME_NOT_CLEAN",
                    object_name=mesh.name,
                    message=(
                        f"Consider renaming to '{sanitize_asset_name(mesh.name)}' "
                        "for clean engine imports."
                    ),
                    auto_fixable=True,
                )
            )

    if total_tris > preset.max_scene_tris:
        issues.append(
            ValidationIssue(
                severity="WARNING",
                code="SCENE_POLY_BUDGET_HIGH",
                object_name="<scene>",
                message=(
                    f"Combined scene triangle count {total_tris:,} exceeds "
                    f"recommended {preset.max_scene_tris:,} budget."
                ),
            )
        )

    return ValidationReport(
        target=preset.name,
        mesh_count=len(meshes),
        total_triangles=total_tris,
        issues=tuple(issues),
    )
