"""Parametric room geometry — walls, floor, ceiling with door/window cutouts."""

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from backend.app.models.space import Dimensions, Door, Window

__all__ = ["generate_room_bodies"]

logger = logging.getLogger(__name__)

_WALL_THICKNESS = 0.1
_FLOOR_THICKNESS = 0.02
_WALL_COLOR_VIS = "0.92 0.90 0.87 0.2"
_WALL_COLOR_COL = "0 0 0 0"
_FLOOR_COLOR = "0.72 0.58 0.42 1"
_CEILING_COLOR = "0.96 0.96 0.96 0.3"


@dataclass
class _Opening:
    """A door or window opening in a wall.

    Args:
        center_along_wall: Center position along the wall's length axis.
        width: Opening width in meters.
        bottom: Bottom of opening (0 for doors).
        top: Top of opening in meters.
    """

    center_along_wall: float
    width: float
    bottom: float
    top: float


def generate_room_bodies(
    dims: Dimensions,
    doors: list[Door],
    windows: list[Window],
) -> list[ET.Element]:
    """Generate MuJoCo body elements for an enclosed room.

    Args:
        dims: Room dimensions.
        doors: Doors with wall assignments.
        windows: Windows with wall assignments.

    Returns:
        List of XML body elements (floor, ceiling, 4 walls with cutouts).
    """
    bodies: list[ET.Element] = []
    bodies.append(_make_floor(dims))
    bodies.append(_make_ceiling(dims))

    for wall_name in ("north", "south", "east", "west"):
        wall_doors = [d for d in doors if d.wall == wall_name]
        wall_windows = [w for w in windows if w.wall == wall_name]
        bodies.append(
            _make_wall(wall_name, dims, wall_doors, wall_windows)
        )

    return bodies


def _make_floor(dims: Dimensions) -> ET.Element:
    """Create floor body.

    Args:
        dims: Room dimensions.

    Returns:
        Floor body element.
    """
    body = ET.Element("body", {"name": "room_floor", "pos": "0 0 0"})
    ET.SubElement(
        body,
        "geom",
        {
            "name": "floor",
            "type": "box",
            "size": f"{dims.width_m / 2:.3f} {dims.length_m / 2:.3f} {_FLOOR_THICKNESS}",
            "pos": f"{dims.width_m / 2:.3f} {dims.length_m / 2:.3f} 0",
            "rgba": _FLOOR_COLOR,
            "contype": "1",
            "conaffinity": "1",
        },
    )
    return body


def _make_ceiling(dims: Dimensions) -> ET.Element:
    """Create ceiling body.

    Args:
        dims: Room dimensions.

    Returns:
        Ceiling body element.
    """
    body = ET.Element("body", {"name": "room_ceiling", "pos": "0 0 0"})
    ET.SubElement(
        body,
        "geom",
        {
            "name": "ceiling",
            "type": "box",
            "size": f"{dims.width_m / 2:.3f} {dims.length_m / 2:.3f} {_FLOOR_THICKNESS}",
            "pos": f"{dims.width_m / 2:.3f} {dims.length_m / 2:.3f} {dims.ceiling_m:.3f}",
            "rgba": _CEILING_COLOR,
            "contype": "0",
            "conaffinity": "0",
        },
    )
    return body


def _make_wall(
    wall_name: str,
    dims: Dimensions,
    doors: list[Door],
    windows: list[Window],
) -> ET.Element:
    """Create a wall body with door/window cutouts.

    Args:
        wall_name: Wall identifier (north/south/east/west).
        dims: Room dimensions.
        doors: Doors on this wall.
        windows: Windows on this wall.

    Returns:
        Wall body element with geom segments.
    """
    wall_length = _wall_length(wall_name, dims)
    openings = _collect_openings(
        wall_name, wall_length, dims.ceiling_m, doors, windows,
    )

    body = ET.Element("body", {"name": f"wall_{wall_name}", "pos": "0 0 0"})
    segments = _split_wall_segments(
        wall_name, wall_length, dims.ceiling_m, openings,
    )

    for seg_name, pos, size in segments:
        full_name = f"wall_{wall_name}_{seg_name}"
        world_pos = _wall_local_to_world(wall_name, dims, pos)
        world_size = _wall_local_to_world_size(wall_name, size)
        size_str = f"{world_size[0]:.4f} {world_size[1]:.4f} {world_size[2]:.4f}"
        pos_str = f"{world_pos[0]:.4f} {world_pos[1]:.4f} {world_pos[2]:.4f}"

        # Visual geom — semi-transparent, no collision
        ET.SubElement(body, "geom", {
            "name": f"{full_name}_vis",
            "type": "box",
            "size": size_str,
            "pos": pos_str,
            "rgba": _WALL_COLOR_VIS,
            "contype": "0",
            "conaffinity": "0",
            "group": "1",
        })
        # Collision geom — invisible, physics only
        ET.SubElement(body, "geom", {
            "name": f"{full_name}_col",
            "type": "box",
            "size": size_str,
            "pos": pos_str,
            "rgba": _WALL_COLOR_COL,
            "contype": "1",
            "conaffinity": "1",
            "group": "3",
        })

    return body


def _wall_length(wall_name: str, dims: Dimensions) -> float:
    """Get the length of a wall.

    Args:
        wall_name: Wall identifier.
        dims: Room dimensions.

    Returns:
        Wall length in meters.
    """
    if wall_name in ("north", "south"):
        return dims.width_m
    return dims.length_m


def _opening_center_along_wall(
    wall_name: str,
    position: tuple[float, float],
) -> float:
    """Get opening center position along a wall's length axis.

    Args:
        wall_name: Wall identifier.
        position: 2D position (x, y) of the opening.

    Returns:
        Position along wall length.
    """
    if wall_name in ("north", "south"):
        return position[0]
    return position[1]


def _collect_openings(
    wall_name: str,
    wall_length: float,
    ceiling: float,
    doors: list[Door],
    windows: list[Window],
) -> list[_Opening]:
    """Collect and validate all openings for a wall.

    Args:
        wall_name: Wall identifier.
        wall_length: Total wall length.
        ceiling: Ceiling height.
        doors: Doors on this wall.
        windows: Windows on this wall.

    Returns:
        Sorted list of openings along the wall.
    """
    openings: list[_Opening] = []

    for door in doors:
        center = _opening_center_along_wall(wall_name, door.position)
        half_w = door.width_m / 2
        if center - half_w < 0 or center + half_w > wall_length:
            logger.warning(
                "Door on %s wall exceeds wall bounds, clamping", wall_name,
            )
            center = max(half_w, min(center, wall_length - half_w))
        openings.append(_Opening(
            center_along_wall=center,
            width=door.width_m,
            bottom=0.0,
            top=min(door.height_m, ceiling),
        ))

    for window in windows:
        center = _opening_center_along_wall(wall_name, window.position)
        half_w = window.width_m / 2
        if center - half_w < 0 or center + half_w > wall_length:
            logger.warning(
                "Window on %s wall exceeds wall bounds, clamping", wall_name,
            )
            center = max(half_w, min(center, wall_length - half_w))
        openings.append(_Opening(
            center_along_wall=center,
            width=window.width_m,
            bottom=window.sill_height_m,
            top=min(window.sill_height_m + window.height_m, ceiling),
        ))

    openings.sort(key=lambda o: o.center_along_wall)
    return openings


def _split_wall_segments(
    wall_name: str,
    wall_length: float,
    ceiling: float,
    openings: list[_Opening],
) -> list[tuple[str, tuple[float, float, float], tuple[float, float, float]]]:
    """Split a wall into solid segments around openings.

    Each segment is (name, local_pos, half_size) where local coordinates are:
    - x = along wall length
    - y = wall thickness
    - z = vertical

    Args:
        wall_name: Wall identifier (for naming).
        wall_length: Total wall length.
        ceiling: Ceiling height.
        openings: Sorted openings along the wall.

    Returns:
        List of (segment_name, center_pos, half_size) tuples.
    """
    half_t = _WALL_THICKNESS / 2

    if not openings:
        return [
            (
                "solid",
                (wall_length / 2, 0.0, ceiling / 2),
                (wall_length / 2, half_t, ceiling / 2),
            )
        ]

    segments: list[tuple[str, tuple[float, float, float], tuple[float, float, float]]] = []
    cursor = 0.0

    for idx, opening in enumerate(openings):
        left_edge = opening.center_along_wall - opening.width / 2
        right_edge = opening.center_along_wall + opening.width / 2

        # Left solid segment
        if left_edge > cursor + 0.001:
            seg_width = left_edge - cursor
            segments.append((
                f"seg{idx}_left",
                (cursor + seg_width / 2, 0.0, ceiling / 2),
                (seg_width / 2, half_t, ceiling / 2),
            ))

        # Above opening (always present)
        if opening.top < ceiling - 0.001:
            above_h = ceiling - opening.top
            segments.append((
                f"seg{idx}_above",
                (opening.center_along_wall, 0.0, opening.top + above_h / 2),
                (opening.width / 2, half_t, above_h / 2),
            ))

        # Below opening (only for windows with sill > 0)
        if opening.bottom > 0.001:
            segments.append((
                f"seg{idx}_below",
                (opening.center_along_wall, 0.0, opening.bottom / 2),
                (opening.width / 2, half_t, opening.bottom / 2),
            ))

        cursor = right_edge

    # Right solid segment after last opening
    if cursor < wall_length - 0.001:
        seg_width = wall_length - cursor
        segments.append((
            f"seg{len(openings)}_right",
            (cursor + seg_width / 2, 0.0, ceiling / 2),
            (seg_width / 2, half_t, ceiling / 2),
        ))

    return segments


def _wall_local_to_world(
    wall_name: str,
    dims: Dimensions,
    local_pos: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Convert wall-local position to world coordinates.

    Args:
        wall_name: Wall identifier.
        dims: Room dimensions.
        local_pos: (along_wall, thickness_offset, z) in wall-local frame.

    Returns:
        (x, y, z) in world coordinates.
    """
    along, _thick, z = local_pos
    if wall_name == "south":
        return (along, 0.0, z)
    if wall_name == "north":
        return (along, dims.length_m, z)
    if wall_name == "west":
        return (0.0, along, z)
    # east
    return (dims.width_m, along, z)


def _wall_local_to_world_size(
    wall_name: str,
    local_size: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Convert wall-local half-sizes to world-axis half-sizes.

    Args:
        wall_name: Wall identifier.
        local_size: (half_along, half_thick, half_z).

    Returns:
        (half_x, half_y, half_z) in world axes.
    """
    half_along, half_thick, half_z = local_size
    if wall_name in ("north", "south"):
        return (half_along, half_thick, half_z)
    return (half_thick, half_along, half_z)
