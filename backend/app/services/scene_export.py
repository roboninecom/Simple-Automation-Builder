"""Export MJCF scene data as JSON for Three.js editor."""

import xml.etree.ElementTree as ET
from pathlib import Path

from backend.app.models.space import SpaceModel

__all__ = ["export_scene_data"]

_ROOM_PREFIXES = ("room_floor", "room_ceiling", "wall_")


def export_scene_data(
    scene_path: Path,
    space: SpaceModel,
) -> dict:
    """Parse MJCF XML and return JSON suitable for Three.js rendering.

    Args:
        scene_path: Path to MJCF scene file.
        space: Room model for metadata.

    Returns:
        Dict with room, bodies, walls, floor, doors, windows.
    """
    tree = ET.parse(str(scene_path))
    root = tree.getroot()
    worldbody = root.find("worldbody")
    if worldbody is None:
        return {"room": {}, "bodies": [], "walls": [], "floor": {}}

    dims = space.dimensions
    bodies = []
    walls = []
    floor_data = {}

    for body in worldbody.findall("body"):
        name = body.get("name", "")

        if name == "room_floor":
            geom = body.find("geom")
            if geom is not None:
                floor_data = _geom_to_dict(geom)
            continue

        if name == "room_ceiling":
            continue

        if name.startswith("wall_"):
            for geom in body.findall("geom"):
                geom_name = geom.get("name", "")
                if geom_name.endswith("_vis"):
                    walls.append(_geom_to_dict(geom))
            continue

        bodies.append(_body_to_dict(body))

    return {
        "room": {
            "width": dims.width_m,
            "length": dims.length_m,
            "ceiling": dims.ceiling_m,
        },
        "bodies": bodies,
        "walls": walls,
        "floor": floor_data,
        "doors": [
            {"position": list(d.position), "width": d.width_m, "wall": d.wall}
            for d in space.doors
        ],
        "windows": [
            {"position": list(w.position), "width": w.width_m, "wall": w.wall}
            for w in space.windows
        ],
    }


def _body_to_dict(body: ET.Element) -> dict:
    """Convert a body element to a dict for Three.js.

    Args:
        body: XML body element.

    Returns:
        Dict with name, position, euler, geoms.
    """
    pos = _parse_vec(body.get("pos", "0 0 0"))
    euler = _parse_vec(body.get("euler", "0 0 0"))

    geoms = []
    for geom in body.findall("geom"):
        geoms.append(_geom_to_dict(geom))

    # Detect category from first geom name pattern
    name = body.get("name", "")
    category = _guess_category(name, geoms)

    return {
        "name": name,
        "category": category,
        "position": pos,
        "euler": euler,
        "geoms": geoms,
    }


def _geom_to_dict(geom: ET.Element) -> dict:
    """Convert a geom element to a dict.

    Args:
        geom: XML geom element.

    Returns:
        Dict with name, type, size, pos, rgba.
    """
    return {
        "name": geom.get("name", ""),
        "type": geom.get("type", "box"),
        "size": _parse_vec(geom.get("size", "0.1 0.1 0.1")),
        "pos": _parse_vec(geom.get("pos", "0 0 0")),
        "rgba": _parse_vec(geom.get("rgba", "0.5 0.5 0.5 1")),
    }


def _parse_vec(s: str) -> list[float]:
    """Parse a space-separated vector string.

    Args:
        s: Vector string.

    Returns:
        List of floats.
    """
    return [float(v) for v in s.split()]


def _guess_category(name: str, geoms: list[dict]) -> str:
    """Guess equipment category from body name.

    Args:
        name: Body name.
        geoms: Body geoms.

    Returns:
        Guessed category string.
    """
    parts = name.lower().split("_")
    known = {
        "desk", "table", "chair", "bed", "wardrobe", "shelf",
        "cabinet", "plant", "monitor", "sofa", "printer",
    }
    for p in parts:
        if p in known:
            return p
    return "equipment"
