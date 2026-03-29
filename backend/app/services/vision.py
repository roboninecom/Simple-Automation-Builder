"""Claude Vision scene analysis — photos → structured SceneAnalysis."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.app.core.claude import ClaudeClient
from backend.app.core.config import get_settings
from backend.app.core.prompts import load_prompt
from backend.app.models.space import (
    Dimensions,
    ExistingEquipment,
    SceneAnalysis,
    SceneReconstruction,
    SpaceModel,
)
from backend.app.services.spatial_anchors import ImageAnchors

__all__ = [
    "analyze_scene",
    "build_space_model",
    "validate_analysis",
    "validate_positions_against_cloud",
]

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2


def _try_compute_anchors(
    reconstruction: SceneReconstruction,
) -> list[ImageAnchors] | None:
    """Attempt to compute spatial anchors from reconstruction data.

    Returns None if metadata or sparse dir is unavailable (backward compat).

    Args:
        reconstruction: Scene reconstruction result.

    Returns:
        List of ImageAnchors or None if data is unavailable.
    """
    if reconstruction.sparse_dir is None or not reconstruction.sparse_dir.exists():
        logger.info("No sparse dir — skipping spatial anchors")
        return None

    try:
        import pycolmap

        from backend.app.services.spatial_anchors import compute_all_anchors

        recon = pycolmap.Reconstruction()
        sparse_subdirs = sorted(reconstruction.sparse_dir.iterdir())
        if not sparse_subdirs:
            logger.warning("Sparse dir empty — skipping spatial anchors")
            return None
        recon.read(str(sparse_subdirs[0]))

        anchors = compute_all_anchors(recon, reconstruction.dimensions)
        logger.info(
            "Computed spatial anchors for %d images (%d total anchors)",
            len(anchors),
            sum(len(ia.anchors) for ia in anchors),
        )
        return anchors if anchors else None
    except Exception:
        logger.warning("Failed to compute spatial anchors", exc_info=True)
        return None


async def analyze_scene(
    client: ClaudeClient,
    photos: list[Path],
    reconstruction: SceneReconstruction,
) -> SceneAnalysis:
    """Analyze room photos + reconstruction data via Claude Vision.

    Args:
        client: Claude API client.
        photos: List of room photo file paths.
        reconstruction: Scene reconstruction result.

    Returns:
        Structured scene analysis with zones, equipment, doors, windows.

    Raises:
        ValueError: If Claude returns unparseable response after retries.
    """
    system_prompt = load_prompt("vision_analysis")
    dims = reconstruction.dimensions
    image_anchors = _try_compute_anchors(reconstruction)
    text = _format_analysis_request(dims, image_anchors)

    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.send_vision_message(
                system=system_prompt,
                images=photos,
                text=text,
                model=get_settings().vision_model,
            )
            analysis = _parse_analysis_response(response)
            validated = validate_analysis(analysis, dims)
            return validate_positions_against_cloud(
                validated, reconstruction.pointcloud_path, dims
            )
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning(
                "Analysis attempt %d/%d failed: %s",
                attempt + 1,
                _MAX_RETRIES + 1,
                exc,
            )

    raise ValueError(
        f"Failed to parse scene analysis after {_MAX_RETRIES + 1} attempts: {last_error}"
    )


def build_space_model(
    reconstruction: SceneReconstruction,
    analysis: SceneAnalysis,
) -> SpaceModel:
    """Merge reconstruction and analysis into a complete SpaceModel.

    Args:
        reconstruction: Scene reconstruction data.
        analysis: Claude Vision analysis results.

    Returns:
        Complete room model for simulation.
    """
    return SpaceModel(
        dimensions=reconstruction.dimensions,
        zones=analysis.zones,
        existing_equipment=analysis.existing_equipment,
        doors=analysis.doors,
        windows=analysis.windows,
        reconstruction=reconstruction,
    )


def validate_analysis(
    analysis: SceneAnalysis,
    dims: Dimensions,
) -> SceneAnalysis:
    """Validate and clamp analysis values to reasonable ranges.

    Args:
        analysis: Parsed scene analysis from Claude.
        dims: Room dimensions for bounds checking.

    Returns:
        Validated SceneAnalysis with clamped values.
    """
    validated_equipment = []
    for eq in analysis.existing_equipment:
        eq_dims = tuple(_clamp(d, 0.05, max(dims.width_m, dims.length_m)) for d in eq.dimensions)
        pos_z = _compute_center_z(eq, eq_dims[2], dims.ceiling_m)
        pos = (
            _clamp(eq.position[0], 0.0, dims.width_m),
            _clamp(eq.position[1], 0.0, dims.length_m),
            pos_z,
        )
        if pos != eq.position or eq_dims != eq.dimensions:
            logger.warning(
                "Clamped equipment '%s': pos %s→%s, dims %s→%s",
                eq.name,
                eq.position,
                pos,
                eq.dimensions,
                eq_dims,
            )
        validated_equipment.append(
            eq.model_copy(
                update={
                    "position": pos,
                    "dimensions": eq_dims,
                }
            )
        )

    return analysis.model_copy(
        update={
            "existing_equipment": validated_equipment,
        }
    )


def _compute_center_z(
    eq: ExistingEquipment,
    height: float,
    ceiling_m: float,
) -> float:
    """Compute body-center Z position based on mounting type.

    Args:
        eq: Equipment entry.
        height: Equipment height in meters.
        ceiling_m: Room ceiling height.

    Returns:
        Z coordinate for the body center.
    """
    if eq.mounting == "floor":
        return height / 2
    if eq.mounting == "ceiling":
        return ceiling_m - height / 2
    return eq.position[2]


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value to a range.

    Args:
        value: Value to clamp.
        min_val: Minimum allowed value.
        max_val: Maximum allowed value.

    Returns:
        Clamped value.
    """
    return max(min_val, min(value, max_val))


def validate_positions_against_cloud(
    analysis: SceneAnalysis,
    pointcloud_path: Path | None,
    dims: Dimensions,
    near_radius: float = 0.5,
    far_radius: float = 1.0,
    near_penalty: float = 0.2,
    far_penalty: float = 0.4,
) -> SceneAnalysis:
    """Cross-check equipment positions against point cloud density.

    For each floor-mounted equipment item, queries nearby points in the
    cloud. If no points exist near the claimed position, confidence is
    reduced — indicating the position may be incorrect.

    Args:
        analysis: Parsed scene analysis.
        pointcloud_path: Path to PLY point cloud file (None to skip).
        dims: Room dimensions.
        near_radius: Radius for "close" point search in meters.
        far_radius: Radius for "far" point search in meters.
        near_penalty: Confidence penalty when no close points found.
        far_penalty: Confidence penalty when no far points found either.

    Returns:
        SceneAnalysis with adjusted confidence scores.
    """
    if pointcloud_path is None or not pointcloud_path.exists():
        return analysis
    if pointcloud_path.stat().st_size == 0:
        return analysis

    try:
        import trimesh
        from scipy.spatial import KDTree

        cloud = trimesh.load(str(pointcloud_path))
        if not hasattr(cloud, "vertices") or len(cloud.vertices) < 3:
            return analysis

        tree = KDTree(cloud.vertices)
    except Exception:
        logger.warning("Failed to load point cloud for validation", exc_info=True)
        return analysis

    updated_equipment = []
    for eq in analysis.existing_equipment:
        if eq.mounting != "floor":
            updated_equipment.append(eq)
            continue

        pos = eq.position
        query_point = [pos[0], pos[1], 0.0]

        near_count = tree.query_ball_point(query_point, near_radius, return_length=True)
        if near_count >= 3:
            updated_equipment.append(eq)
            continue

        far_count = tree.query_ball_point(query_point, far_radius, return_length=True)
        if far_count == 0:
            new_conf = max(0.0, eq.confidence - far_penalty)
            logger.warning(
                "Equipment '%s' at (%.2f, %.2f): no points within %.1fm — "
                "confidence %.2f → %.2f",
                eq.name, pos[0], pos[1], far_radius,
                eq.confidence, new_conf,
            )
            updated_equipment.append(eq.model_copy(update={"confidence": new_conf}))
        else:
            new_conf = max(0.0, eq.confidence - near_penalty)
            logger.info(
                "Equipment '%s' at (%.2f, %.2f): few points within %.1fm — "
                "confidence %.2f → %.2f",
                eq.name, pos[0], pos[1], near_radius,
                eq.confidence, new_conf,
            )
            updated_equipment.append(eq.model_copy(update={"confidence": new_conf}))

    return analysis.model_copy(update={"existing_equipment": updated_equipment})


def _format_analysis_request(
    dims: Dimensions,
    image_anchors: list[ImageAnchors] | None = None,
) -> str:
    """Format the text portion of the vision analysis request.

    Args:
        dims: Room dimensions from reconstruction.
        image_anchors: Optional spatial anchors per image for precise positioning.

    Returns:
        Formatted request text.
    """
    text = (
        f"Room dimensions from 3D reconstruction:\n"
        f"  Width (X-axis): {dims.width_m:.2f}m\n"
        f"  Length (Y-axis): {dims.length_m:.2f}m\n"
        f"  Ceiling height: {dims.ceiling_m:.2f}m\n"
        f"  Area: {dims.area_m2:.2f}m²\n\n"
        f"Wall reference:\n"
        f"  North wall: Y = {dims.length_m:.2f}\n"
        f"  South wall: Y = 0\n"
        f"  East wall: X = {dims.width_m:.2f}\n"
        f"  West wall: X = 0\n\n"
    )

    if image_anchors:
        text += _format_anchor_section(image_anchors)

    text += (
        "Analyze these photos and return a JSON with:\n"
        "1. Functional zones (name, polygon, area)\n"
        "2. Existing equipment with estimated dimensions [w, d, h], "
        "orientation_deg, rgba color, mounting type, shape\n"
        "3. Doors with wall assignment and height\n"
        "4. Windows with wall assignment, height, and sill_height_m\n\n"
        "Return ONLY valid JSON matching the schema in the system prompt."
    )
    return text


def _format_anchor_section(image_anchors: list[ImageAnchors]) -> str:
    """Format spatial anchor data as text for the vision request.

    Args:
        image_anchors: Anchor data per image.

    Returns:
        Formatted markdown section describing anchors.
    """
    lines = [
        "## Spatial Reference Points\n",
        "Each photo below has spatial anchor points that map pixel locations "
        "to real-world 3D coordinates (meters). Use these to determine "
        "precise positions of detected equipment.\n",
    ]

    for ia in image_anchors:
        lines.append(f"### {ia.image_name}")
        cx, cy, cz = ia.camera_position
        dx, dy, dz = ia.viewing_direction
        lines.append(
            f"Camera at ({cx:.2f}, {cy:.2f}, {cz:.2f}), "
            f"looking toward ({dx:.2f}, {dy:.2f}, {dz:.2f})"
        )
        lines.append("| Pixel (x,y) | World (x,y,z) | Label |")
        lines.append("|-------------|---------------|-------|")
        for a in ia.anchors:
            px, py = a.pixel
            wx, wy, wz = a.world
            lines.append(f"| ({px}, {py}) | ({wx:.2f}, {wy:.2f}, {wz:.2f}) | {a.label} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def _parse_analysis_response(response: str) -> SceneAnalysis:
    """Parse Claude's response into a SceneAnalysis model.

    Args:
        response: Raw response text from Claude.

    Returns:
        Parsed SceneAnalysis.

    Raises:
        ValueError: If response cannot be parsed.
    """
    json_str = _extract_json(response)
    return SceneAnalysis.model_validate_json(json_str)


def _extract_json(text: str) -> str:
    """Extract JSON from text, handling markdown code blocks.

    Args:
        text: Raw text that may contain JSON in code blocks.

    Returns:
        Extracted JSON string.
    """
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        return text[start:end].strip()
    if "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        return text[start:end].strip()
    return text.strip()
