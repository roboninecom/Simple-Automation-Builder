"""Scene layout validation — detect overlaps, out-of-bounds, and other issues."""

import logging
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from backend.app.models.space import SpaceModel

__all__ = [
    "SceneWarning",
    "validate_scene_layout",
    "adjust_scene",
]

logger = logging.getLogger(__name__)


@dataclass
class SceneWarning:
    """A warning about a potential issue in the scene layout.

    Args:
        body_name: Name of the affected body.
        level: Severity level (info, warning, error).
        message: Human-readable description.
    """

    body_name: str
    level: str
    message: str


@dataclass
class _BodyBox:
    """Axis-aligned bounding box for a scene body.

    Args:
        name: Body name.
        x_min: Minimum X coordinate.
        x_max: Maximum X coordinate.
        y_min: Minimum Y coordinate.
        y_max: Maximum Y coordinate.
        z_min: Minimum Z coordinate.
        z_max: Maximum Z coordinate.
    """

    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float


def validate_scene_layout(
    space: SpaceModel,
    scene_path: Path,
) -> list[SceneWarning]:
    """Check scene for common layout issues.

    Args:
        space: Room model with dimensions.
        scene_path: Path to MJCF scene file.

    Returns:
        List of warnings about detected issues.
    """
    warnings: list[SceneWarning] = []
    tree = ET.parse(str(scene_path))
    root = tree.getroot()
    worldbody = root.find("worldbody")
    if worldbody is None:
        return warnings

    dims = space.dimensions
    boxes = _extract_body_boxes(worldbody)

    for box in boxes:
        warnings.extend(_check_bounds(box, dims))
        warnings.extend(_check_size(box))
        warnings.extend(_check_floating(box))

    warnings.extend(_check_overlaps(boxes))
    warnings.extend(_check_door_blocking(boxes, space))

    return warnings


def adjust_scene(
    scene_path: Path,
    adjustments: list[dict],
    output_path: Path,
) -> Path:
    """Apply position/dimension adjustments to a scene.

    Args:
        scene_path: Path to source MJCF file.
        adjustments: List of adjustment dicts with body_name and changes.
        output_path: Path for the adjusted scene file.

    Returns:
        Path to the adjusted scene.
    """
    tree = ET.parse(str(scene_path))
    root = tree.getroot()
    worldbody = root.find("worldbody")
    if worldbody is None:
        return scene_path

    for adj in adjustments:
        body_name = adj.get("body_name", "")
        body = worldbody.find(f".//body[@name='{body_name}']")
        if body is None:
            logger.warning("Body '%s' not found in scene", body_name)
            continue

        if adj.get("remove"):
            parent = _find_parent(worldbody, body)
            if parent is not None:
                parent.remove(body)
            continue

        if "position" in adj:
            pos = adj["position"]
            body.set("pos", f"{pos[0]:.3f} {pos[1]:.3f} {pos[2]:.3f}")

        if "orientation_deg" in adj:
            deg = adj["orientation_deg"]
            body.set("euler", f"0 0 {math.radians(deg):.4f}")

        if "dimensions" in adj:
            new_dims = adj["dimensions"]
            for geom in body.findall("geom"):
                if geom.get("type") == "box":
                    geom.set(
                        "size",
                        f"{new_dims[0]/2:.3f} {new_dims[1]/2:.3f} {new_dims[2]/2:.3f}",
                    )
                    break

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(str(output_path), encoding="unicode", xml_declaration=False)
    return output_path


def _find_parent(
    root: ET.Element,
    target: ET.Element,
) -> ET.Element | None:
    """Find the parent element of a target in the XML tree.

    Args:
        root: Root element to search from.
        target: Element whose parent to find.

    Returns:
        Parent element, or None.
    """
    for parent in root.iter():
        for child in parent:
            if child is target:
                return parent
    return None


def _extract_body_boxes(worldbody: ET.Element) -> list[_BodyBox]:
    """Extract bounding boxes from equipment bodies (skip room geometry).

    Args:
        worldbody: Worldbody XML element.

    Returns:
        List of body bounding boxes.
    """
    skip_prefixes = ("room_", "wall_", "floor", "ceiling")
    boxes: list[_BodyBox] = []

    for body in worldbody.findall("body"):
        name = body.get("name", "")
        if any(name.startswith(p) for p in skip_prefixes):
            continue

        pos_str = body.get("pos", "0 0 0")
        pos = [float(v) for v in pos_str.split()]
        if len(pos) < 3:
            continue

        geom = body.find("geom")
        if geom is None:
            continue

        size_str = geom.get("size", "0.1 0.1 0.1")
        size = [float(v) for v in size_str.split()]
        if len(size) < 3:
            continue

        boxes.append(_BodyBox(
            name=name,
            x_min=pos[0] - size[0],
            x_max=pos[0] + size[0],
            y_min=pos[1] - size[1],
            y_max=pos[1] + size[1],
            z_min=pos[2] - size[2],
            z_max=pos[2] + size[2],
        ))

    return boxes


def _check_bounds(
    box: _BodyBox,
    dims: "Dimensions",
) -> list[SceneWarning]:
    """Check if equipment is within room bounds.

    Args:
        box: Body bounding box.
        dims: Room dimensions.

    Returns:
        Warnings for out-of-bounds bodies.
    """
    from backend.app.models.space import Dimensions  # noqa: F811

    warnings: list[SceneWarning] = []
    margin = 0.05
    if box.x_min < -margin or box.x_max > dims.width_m + margin:
        warnings.append(SceneWarning(
            body_name=box.name, level="warning",
            message=f"Outside room X bounds (0–{dims.width_m:.1f}m)",
        ))
    if box.y_min < -margin or box.y_max > dims.length_m + margin:
        warnings.append(SceneWarning(
            body_name=box.name, level="warning",
            message=f"Outside room Y bounds (0–{dims.length_m:.1f}m)",
        ))
    return warnings


def _check_size(box: _BodyBox) -> list[SceneWarning]:
    """Check for suspiciously sized equipment.

    Args:
        box: Body bounding box.

    Returns:
        Warnings for bodies with extreme dimensions.
    """
    warnings: list[SceneWarning] = []
    for dim_name, size in [
        ("width", box.x_max - box.x_min),
        ("depth", box.y_max - box.y_min),
        ("height", box.z_max - box.z_min),
    ]:
        if size < 0.05:
            warnings.append(SceneWarning(
                body_name=box.name, level="info",
                message=f"Very small {dim_name}: {size:.2f}m",
            ))
        if size > 4.0:
            warnings.append(SceneWarning(
                body_name=box.name, level="warning",
                message=f"Very large {dim_name}: {size:.2f}m",
            ))
    return warnings


def _check_floating(box: _BodyBox) -> list[SceneWarning]:
    """Check if floor-level equipment is floating above floor.

    Args:
        box: Body bounding box.

    Returns:
        Warnings for floating bodies.
    """
    if box.z_min > 0.1:
        return [SceneWarning(
            body_name=box.name, level="info",
            message=f"Floating {box.z_min:.2f}m above floor",
        )]
    return []


def _check_overlaps(boxes: list[_BodyBox]) -> list[SceneWarning]:
    """Check for overlapping equipment bounding boxes.

    Args:
        boxes: List of body bounding boxes.

    Returns:
        Warnings for overlapping pairs.
    """
    warnings: list[SceneWarning] = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if _boxes_overlap(a, b):
                warnings.append(SceneWarning(
                    body_name=a.name, level="warning",
                    message=f"Overlaps with '{b.name}'",
                ))
    return warnings


def _boxes_overlap(a: _BodyBox, b: _BodyBox) -> bool:
    """Check if two axis-aligned bounding boxes overlap.

    Args:
        a: First bounding box.
        b: Second bounding box.

    Returns:
        True if the boxes overlap in all three axes.
    """
    return (
        a.x_min < b.x_max and a.x_max > b.x_min
        and a.y_min < b.y_max and a.y_max > b.y_min
        and a.z_min < b.z_max and a.z_max > b.z_min
    )


def _check_door_blocking(
    boxes: list[_BodyBox],
    space: SpaceModel,
) -> list[SceneWarning]:
    """Check if equipment blocks door openings.

    Args:
        boxes: Equipment bounding boxes.
        space: Room model with doors.

    Returns:
        Warnings for equipment blocking doors.
    """
    warnings: list[SceneWarning] = []
    clearance = 0.5

    for door in space.doors:
        dx, dy = door.position
        half_w = door.width_m / 2

        for box in boxes:
            if door.wall in ("north", "south"):
                if box.x_min < dx + half_w and box.x_max > dx - half_w:
                    dist = abs(box.y_min) if door.wall == "south" else abs(
                        box.y_max - space.dimensions.length_m
                    )
                    if dist < clearance:
                        warnings.append(SceneWarning(
                            body_name=box.name, level="warning",
                            message=f"Blocking {door.wall} door",
                        ))
            else:
                if box.y_min < dy + half_w and box.y_max > dy - half_w:
                    dist = abs(box.x_min) if door.wall == "west" else abs(
                        box.x_max - space.dimensions.width_m
                    )
                    if dist < clearance:
                        warnings.append(SceneWarning(
                            body_name=box.name, level="warning",
                            message=f"Blocking {door.wall} door",
                        ))

    return warnings
