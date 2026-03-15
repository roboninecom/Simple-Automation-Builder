"""MJCF scene generation — room + equipment + work objects → final scene."""

import logging
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.app.models.equipment import EquipmentEntry
from backend.app.models.recommendation import (
    EquipmentPlacement,
    Recommendation,
    WorkObject,
)
from backend.app.models.space import Dimensions, ExistingEquipment, SpaceModel
from backend.app.services.downloader import find_mjcf_in_dir
from backend.app.services.room import generate_room_bodies

__all__ = ["generate_mjcf_scene", "generate_preview_scene", "validate_mjcf"]

logger = logging.getLogger(__name__)


def generate_mjcf_scene(
    space: SpaceModel,
    recommendation: Recommendation,
    model_dirs: dict[str, Path],
    catalog: dict[str, EquipmentEntry],
    output_path: Path,
) -> Path:
    """Build complete MJCF scene: room + equipment + work objects.

    Args:
        space: Room model with reconstruction MJCF.
        recommendation: Automation plan with placements.
        model_dirs: Mapping equipment_id → local model directory.
        catalog: Equipment catalog for type information.
        output_path: Path for output MJCF file.

    Returns:
        Path to the generated MJCF file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    root = _create_base_scene(space)
    worldbody = root.find("worldbody")

    _add_existing_equipment(worldbody, space)
    _add_new_equipment(
        root,
        worldbody,
        recommendation.equipment,
        model_dirs,
        catalog,
        output_path.parent,
    )
    _add_work_objects(worldbody, recommendation.work_objects)
    _add_cameras(root, recommendation.equipment, catalog)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(output_path), encoding="unicode", xml_declaration=False)

    # MuJoCo XML parser doesn't allow comments before root element
    return output_path


def generate_preview_scene(
    space: SpaceModel,
    output_path: Path,
) -> Path:
    """Build preview MJCF: room + existing furniture, no recommendation equipment.

    Args:
        space: Room model with reconstruction and existing equipment.
        output_path: Path for output MJCF file.

    Returns:
        Path to the generated preview MJCF file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    root = _create_base_scene(space)
    worldbody = root.find("worldbody")

    _add_existing_equipment(worldbody, space)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(output_path), encoding="unicode", xml_declaration=False)
    return output_path


def validate_mjcf(scene_path: Path) -> bool:
    """Validate that a MJCF file can be loaded by MuJoCo.

    Args:
        scene_path: Path to MJCF file.

    Returns:
        True if scene loads successfully.
    """
    import mujoco

    try:
        mujoco.MjModel.from_xml_path(str(scene_path))
        return True
    except Exception as exc:
        logger.error("MJCF validation failed: %s", exc)
        return False


def _create_base_scene(space: SpaceModel) -> ET.Element:
    """Create base MJCF structure with room geometry.

    Args:
        space: Room model.

    Returns:
        Root mujoco XML element.
    """
    dims = space.dimensions
    root = ET.Element("mujoco", model="robo9_automate_scene")

    _add_visual_settings(root)

    option = ET.SubElement(root, "option")
    option.set("gravity", "0 0 -9.81")
    option.set("timestep", "0.002")

    ET.SubElement(root, "asset")

    worldbody = ET.SubElement(root, "worldbody")
    _add_lighting(worldbody, dims, space.windows)

    room_bodies = generate_room_bodies(dims, space.doors, space.windows)
    for body in room_bodies:
        worldbody.append(body)

    return root


def _add_visual_settings(root: ET.Element) -> None:
    """Add MuJoCo visual settings for better rendering.

    Args:
        root: Root mujoco XML element.
    """
    visual = ET.SubElement(root, "visual")
    ET.SubElement(visual, "headlight", {
        "ambient": "0.15 0.15 0.15",
        "diffuse": "0.4 0.4 0.4",
    })
    ET.SubElement(visual, "quality", {"shadowsize": "2048"})
    ET.SubElement(visual, "map", {"znear": "0.01", "zfar": "50"})



def _add_lighting(
    worldbody: ET.Element,
    dims: Dimensions,
    windows: list | None = None,
) -> None:
    """Add multi-point lighting: ambient + fill + optional sunlight from windows.

    Args:
        worldbody: Worldbody XML element.
        dims: Room dimensions for positioning.
        windows: Windows for directional sunlight.
    """
    cx = dims.width_m / 2
    cy = dims.length_m / 2

    # Main ambient light from ceiling center
    ET.SubElement(worldbody, "light", {
        "pos": f"{cx:.2f} {cy:.2f} {dims.ceiling_m:.2f}",
        "dir": "0 0 -1",
        "diffuse": "0.6 0.6 0.6",
        "ambient": "0.3 0.3 0.3",
    })
    # Fill light from the side
    ET.SubElement(worldbody, "light", {
        "pos": f"0 {cy:.2f} {dims.ceiling_m * 0.7:.2f}",
        "dir": "1 0 -0.5",
        "diffuse": "0.3 0.3 0.35",
        "specular": "0 0 0",
    })
    # Sunlight from first window direction if any
    if windows:
        w = windows[0]
        sun_dir = {
            "north": "0 -1 -0.5",
            "south": "0 1 -0.5",
            "east": "-1 0 -0.5",
            "west": "1 0 -0.5",
        }.get(w.wall, "0 0 -1")
        ET.SubElement(worldbody, "light", {
            "pos": f"{w.position[0]:.2f} {w.position[1]:.2f} {dims.ceiling_m * 0.8:.2f}",
            "dir": sun_dir,
            "diffuse": "0.4 0.4 0.35",
            "specular": "0.1 0.1 0.1",
        })



_DEFAULT_DIMENSIONS: dict[str, tuple[float, float, float]] = {
    "table": (1.2, 0.6, 0.75),
    "desk": (1.2, 0.6, 0.75),
    "chair": (0.55, 0.55, 0.9),
    "bed": (1.6, 2.0, 0.5),
    "wardrobe": (1.2, 0.6, 2.0),
    "shelf": (0.8, 0.3, 1.8),
    "cabinet": (0.8, 0.4, 0.8),
    "appliance": (0.6, 0.3, 0.3),
    "plant": (0.4, 0.4, 1.0),
    "monitor": (0.6, 0.2, 0.4),
    "printer": (0.4, 0.4, 0.35),
    "sofa": (1.8, 0.85, 0.75),
}

_DEFAULT_COLORS: dict[str, str] = {
    "table": "0.35 0.25 0.15 1",
    "desk": "0.25 0.20 0.15 1",
    "chair": "0.2 0.2 0.2 1",
    "bed": "0.75 0.65 0.4 1",
    "wardrobe": "0.15 0.15 0.15 0.7",
    "shelf": "0.6 0.5 0.35 1",
    "plant": "0.2 0.5 0.2 1",
    "appliance": "0.9 0.9 0.9 1",
    "monitor": "0.1 0.1 0.1 1",
    "cabinet": "0.45 0.35 0.25 1",
    "sofa": "0.4 0.35 0.3 1",
}

_FALLBACK_DIMS = (0.4, 0.4, 0.8)
_FALLBACK_COLOR = "0.5 0.5 0.5 1"


def _add_existing_equipment(
    worldbody: ET.Element,
    space: SpaceModel,
) -> None:
    """Add existing equipment with real dimensions, orientation, and color.

    Args:
        worldbody: Worldbody XML element.
        space: Room model with existing equipment.
    """
    for eq in space.existing_equipment:
        dims = _resolve_dims(eq)
        color = _resolve_color(eq)
        pos_z = _compute_mounting_z(eq, dims, space.dimensions.ceiling_m)
        pos = f"{eq.position[0]:.3f} {eq.position[1]:.3f} {pos_z:.3f}"
        euler = f"0 0 {math.radians(eq.orientation_deg):.4f}"

        body = ET.SubElement(
            worldbody, "body",
            {"name": eq.name, "pos": pos, "euler": euler},
        )

        builder = _COMPOSITE_BUILDERS.get(eq.category)
        if builder:
            builder(body, eq.name, dims, color)
        else:
            _add_simple_box(body, eq.name, dims, color, eq.shape)


def _resolve_dims(
    eq: "ExistingEquipment",
) -> tuple[float, float, float]:
    """Resolve equipment dimensions, using category fallback if needed.

    Args:
        eq: Existing equipment entry.

    Returns:
        (width, depth, height) in meters.
    """
    if eq.dimensions != (0.4, 0.4, 0.8):
        return eq.dimensions
    return _DEFAULT_DIMENSIONS.get(eq.category, _FALLBACK_DIMS)


def _resolve_color(
    eq: "ExistingEquipment",
) -> str:
    """Resolve equipment color, using category fallback if needed.

    Args:
        eq: Existing equipment entry.

    Returns:
        RGBA string for MuJoCo.
    """
    if eq.rgba != (0.5, 0.5, 0.5, 1.0):
        r, g, b, a = eq.rgba
        return f"{r:.2f} {g:.2f} {b:.2f} {a:.2f}"
    return _DEFAULT_COLORS.get(eq.category, _FALLBACK_COLOR)


def _compute_mounting_z(
    eq: "ExistingEquipment",
    dims: tuple[float, float, float],
    ceiling_m: float,
) -> float:
    """Compute Z position based on mounting type.

    Args:
        eq: Existing equipment entry.
        dims: (width, depth, height) of the equipment.
        ceiling_m: Room ceiling height.

    Returns:
        Z coordinate for the body center.
    """
    height = dims[2]
    if eq.mounting == "floor":
        return height / 2
    if eq.mounting == "ceiling":
        return ceiling_m - height / 2
    # wall — use specified Z
    return eq.position[2]


def _add_simple_box(
    body: ET.Element,
    name: str,
    dims: tuple[float, float, float],
    color: str,
    shape: str = "box",
) -> None:
    """Add a single box or cylinder geom.

    Args:
        body: Parent body element.
        name: Equipment name for geom naming.
        dims: (width, depth, height).
        color: RGBA string.
        shape: "box" or "cylinder".
    """
    if shape == "cylinder":
        radius = max(dims[0], dims[1]) / 2
        ET.SubElement(body, "geom", {
            "name": f"{name}_geom", "type": "cylinder",
            "size": f"{radius:.3f} {dims[2] / 2:.3f}",
            "rgba": color,
            "contype": "1", "conaffinity": "1",
        })
    else:
        ET.SubElement(body, "geom", {
            "name": f"{name}_geom", "type": "box",
            "size": f"{dims[0] / 2:.3f} {dims[1] / 2:.3f} {dims[2] / 2:.3f}",
            "rgba": color,
            "contype": "1", "conaffinity": "1",
        })


def _build_table(
    body: ET.Element,
    name: str,
    dims: tuple[float, float, float],
    color: str,
) -> None:
    """Build a table: top slab + 4 legs.

    Args:
        body: Parent body element.
        name: Equipment name.
        dims: (width, depth, height).
        color: RGBA string for tabletop.
    """
    w, d, h = dims
    top_thick = 0.03
    leg_r = 0.025

    # Tabletop
    ET.SubElement(body, "geom", {
        "name": f"{name}_top", "type": "box",
        "size": f"{w / 2:.3f} {d / 2:.3f} {top_thick / 2:.3f}",
        "pos": f"0 0 {h - top_thick / 2:.3f}",
        "rgba": color,
        "contype": "1", "conaffinity": "1",
    })
    # Legs
    leg_h = h - top_thick
    offsets = [
        (w / 2 - leg_r, d / 2 - leg_r),
        (-(w / 2 - leg_r), d / 2 - leg_r),
        (w / 2 - leg_r, -(d / 2 - leg_r)),
        (-(w / 2 - leg_r), -(d / 2 - leg_r)),
    ]
    for i, (ox, oy) in enumerate(offsets):
        ET.SubElement(body, "geom", {
            "name": f"{name}_leg{i}", "type": "box",
            "size": f"{leg_r:.3f} {leg_r:.3f} {leg_h / 2:.3f}",
            "pos": f"{ox:.3f} {oy:.3f} {leg_h / 2:.3f}",
            "rgba": "0.7 0.7 0.72 1",
            "contype": "1", "conaffinity": "1",
        })


def _build_bed(
    body: ET.Element,
    name: str,
    dims: tuple[float, float, float],
    color: str,
) -> None:
    """Build a bed: frame + mattress + headboard.

    Args:
        body: Parent body element.
        name: Equipment name.
        dims: (width, depth, height).
        color: RGBA string for mattress.
    """
    w, d, h = dims
    mattress_h = 0.15
    frame_h = h - mattress_h
    headboard_h = 0.3

    # Frame
    ET.SubElement(body, "geom", {
        "name": f"{name}_frame", "type": "box",
        "size": f"{w / 2:.3f} {d / 2:.3f} {frame_h / 2:.3f}",
        "pos": f"0 0 {frame_h / 2:.3f}",
        "rgba": "0.3 0.22 0.14 1",
        "contype": "1", "conaffinity": "1",
    })
    # Mattress
    ET.SubElement(body, "geom", {
        "name": f"{name}_mattress", "type": "box",
        "size": f"{w / 2:.3f} {d / 2:.3f} {mattress_h / 2:.3f}",
        "pos": f"0 0 {frame_h + mattress_h / 2:.3f}",
        "rgba": color,
        "contype": "1", "conaffinity": "1",
    })
    # Headboard
    ET.SubElement(body, "geom", {
        "name": f"{name}_headboard", "type": "box",
        "size": f"{w / 2:.3f} 0.03 {headboard_h / 2:.3f}",
        "pos": f"0 {-(d / 2 - 0.03):.3f} {h + headboard_h / 2:.3f}",
        "rgba": "0.15 0.12 0.1 1",
        "contype": "1", "conaffinity": "1",
    })


def _build_chair(
    body: ET.Element,
    name: str,
    dims: tuple[float, float, float],
    color: str,
) -> None:
    """Build a chair: base cylinder + seat + backrest.

    Args:
        body: Parent body element.
        name: Equipment name.
        dims: (width, depth, height).
        color: RGBA string.
    """
    w, d, _h = dims
    seat_h = 0.45
    backrest_h = 0.3

    # Base
    ET.SubElement(body, "geom", {
        "name": f"{name}_base", "type": "cylinder",
        "size": f"{max(w, d) / 2 * 0.7:.3f} {seat_h / 2:.3f}",
        "pos": f"0 0 {seat_h / 2:.3f}",
        "rgba": "0.7 0.7 0.72 1",
        "contype": "1", "conaffinity": "1",
    })
    # Seat
    ET.SubElement(body, "geom", {
        "name": f"{name}_seat", "type": "box",
        "size": f"{w / 2:.3f} {d / 2:.3f} 0.03",
        "pos": f"0 0 {seat_h:.3f}",
        "rgba": color,
        "contype": "1", "conaffinity": "1",
    })
    # Backrest
    ET.SubElement(body, "geom", {
        "name": f"{name}_back", "type": "box",
        "size": f"{w / 2:.3f} 0.03 {backrest_h / 2:.3f}",
        "pos": f"0 {-(d / 2 - 0.03):.3f} {seat_h + backrest_h / 2:.3f}",
        "rgba": color,
        "contype": "1", "conaffinity": "1",
    })


_COMPOSITE_BUILDERS = {
    "table": _build_table,
    "desk": _build_table,
    "bed": _build_bed,
    "chair": _build_chair,
}


def _add_new_equipment(
    root: ET.Element,
    worldbody: ET.Element,
    placements: list[EquipmentPlacement],
    model_dirs: dict[str, Path],
    catalog: dict[str, EquipmentEntry],
    scene_dir: Path,
) -> None:
    """Add new equipment from recommendation, dispatching by type.

    Args:
        root: Root mujoco element (for includes).
        worldbody: Worldbody XML element.
        placements: Equipment placements.
        model_dirs: Model directory mapping.
        catalog: Equipment catalog.
        scene_dir: Scene directory for relative paths.
    """
    name_counts: dict[str, int] = {}
    for placement in placements:
        entry = catalog.get(placement.equipment_id)
        if not entry:
            continue

        count = name_counts.get(placement.equipment_id, 0)
        name_counts[placement.equipment_id] = count + 1
        body_name = placement.equipment_id if count == 0 else f"{placement.equipment_id}_{count}"

        if entry.type == "manipulator":
            _add_manipulator_to_scene(
                root,
                worldbody,
                placement,
                body_name,
                model_dirs,
                scene_dir,
            )
        elif entry.type == "conveyor":
            _add_conveyor_to_scene(root, worldbody, placement, body_name, entry)
        elif entry.type == "camera":
            _add_camera_body_to_scene(worldbody, placement, body_name, entry)
        else:
            _add_fixture_to_scene(worldbody, placement, body_name, entry)


def _add_manipulator_to_scene(
    root: ET.Element,
    worldbody: ET.Element,
    placement: EquipmentPlacement,
    body_name: str,
    model_dirs: dict[str, Path],
    _scene_dir: Path,
) -> None:
    """Inline real MJCF model for a manipulator.

    Parses the robot MJCF file, merges top-level sections (compiler,
    default, asset, actuator, etc.) into the scene root, and places
    the robot's body tree inside a positioning wrapper body.

    Args:
        root: Root mujoco element for merging top-level sections.
        worldbody: Worldbody XML element.
        placement: Equipment placement data.
        body_name: Unique body name.
        model_dirs: Model directory mapping.
        scene_dir: Scene directory for relative paths.
    """
    model_dir = model_dirs.get(placement.equipment_id)
    mjcf_file = find_mjcf_in_dir(model_dir) if model_dir else None

    if mjcf_file:
        _inline_robot_model(
            root,
            worldbody,
            mjcf_file,
            placement,
            body_name,
        )
    else:
        _add_fallback_box(worldbody, placement, body_name)


def _inline_robot_model(
    root: ET.Element,
    worldbody: ET.Element,
    mjcf_file: Path,
    placement: EquipmentPlacement,
    body_name: str,
) -> None:
    """Parse robot MJCF and inline it into the scene.

    Merges top-level sections into root and places body tree
    inside a wrapper body at the desired position.

    Args:
        root: Root mujoco element.
        worldbody: Worldbody XML element.
        mjcf_file: Path to robot MJCF file.
        placement: Equipment placement data.
        body_name: Unique body name.
    """
    robot_tree = ET.parse(str(mjcf_file))
    robot_root = robot_tree.getroot()

    _resolve_meshdir(robot_root, mjcf_file.parent)
    _merge_top_level_sections(root, robot_root)

    pos = _format_pos(placement.position)
    euler = f"0 0 {math.radians(placement.orientation_deg):.4f}"
    wrapper = ET.SubElement(
        worldbody,
        "body",
        {"name": body_name, "pos": pos, "euler": euler},
    )

    robot_wb = robot_root.find("worldbody")
    if robot_wb is not None:
        for child in robot_wb:
            if child.tag == "light":
                continue
            wrapper.append(child)

    _ensure_ee_site(wrapper)


def _ensure_ee_site(wrapper: ET.Element) -> None:
    """Add end-effector site to deepest body if none exists.

    Args:
        wrapper: Robot wrapper body element.
    """
    if wrapper.find(".//site") is not None:
        return
    deepest = _find_deepest_body(wrapper)
    if deepest is not None:
        ET.SubElement(
            deepest,
            "site",
            {
                "name": "end_effector",
                "pos": "0 0 0",
                "size": "0.01",
            },
        )


def _find_deepest_body(element: ET.Element) -> ET.Element | None:
    """Find the deepest body in a kinematic chain.

    Args:
        element: Root element to search.

    Returns:
        Deepest body element, or None.
    """
    bodies = list(element.iter("body"))
    return bodies[-1] if bodies else None


def _resolve_meshdir(
    robot_root: ET.Element,
    model_dir: Path,
) -> None:
    """Resolve meshdir so mesh paths are absolute.

    Updates mesh file attributes in asset to use absolute paths
    based on the compiler meshdir setting.

    Args:
        robot_root: Robot MJCF root element.
        model_dir: Directory containing the robot MJCF file.
    """
    compiler = robot_root.find("compiler")
    meshdir = model_dir.resolve()
    if compiler is not None:
        raw = compiler.get("meshdir")
        if raw:
            meshdir = (model_dir / raw).resolve()
        compiler.set("meshdir", str(meshdir).replace("\\", "/"))
    asset = robot_root.find("asset")
    if asset is None:
        return
    for mesh in asset.findall("mesh"):
        file_attr = mesh.get("file")
        if file_attr and not Path(file_attr).is_absolute():
            abs_path = str(meshdir / file_attr).replace("\\", "/")
            mesh.set("file", abs_path)


_MERGEABLE_SECTIONS = [
    "compiler",
    "option",
    "size",
    "default",
    "asset",
    "tendon",
    "equality",
    "actuator",
    "sensor",
    "keyframe",
    "contact",
]


def _merge_top_level_sections(
    scene_root: ET.Element,
    robot_root: ET.Element,
) -> None:
    """Merge robot top-level MJCF sections into the scene root.

    For container sections (asset, actuator, etc.), children are
    appended. For singleton sections (compiler, option), they are
    added only if not already present.

    Args:
        scene_root: Scene mujoco root element.
        robot_root: Robot mujoco root element.
    """
    singleton_tags = {"compiler", "option", "size"}
    for tag in _MERGEABLE_SECTIONS:
        robot_section = robot_root.find(tag)
        if robot_section is None:
            continue
        scene_section = scene_root.find(tag)
        if tag in singleton_tags:
            if scene_section is None:
                scene_root.insert(0, robot_section)
        elif scene_section is None:
            scene_root.append(robot_section)
        else:
            _append_unique_children(scene_section, robot_section)


def _add_conveyor_to_scene(
    root: ET.Element,
    worldbody: ET.Element,
    placement: EquipmentPlacement,
    body_name: str,
    entry: EquipmentEntry,
) -> None:
    """Add parametric conveyor with belt surface, rollers, and frame.

    Args:
        root: Root mujoco element.
        worldbody: Worldbody XML element.
        placement: Equipment placement data.
        body_name: Unique body name.
        entry: Equipment catalog entry.
    """
    specs = entry.specs
    length = float(specs.get("length_m", 0.5))
    width = float(specs.get("width_m", 0.15))
    height = float(specs.get("height_m", 0.85))

    pos = _format_pos(placement.position)
    euler = f"0 0 {math.radians(placement.orientation_deg):.4f}"
    body = ET.SubElement(
        worldbody,
        "body",
        {"name": body_name, "pos": pos, "euler": euler},
    )

    half_l = length / 2
    half_w = width / 2

    # Belt surface (high friction)
    ET.SubElement(
        body,
        "geom",
        {
            "name": f"{body_name}_belt",
            "type": "box",
            "size": f"{half_l:.3f} {half_w:.3f} 0.005",
            "pos": f"0 0 {height:.3f}",
            "friction": "1 0.005 0.0001",
            "rgba": "0.3 0.3 0.3 1",
        },
    )

    # Support frame
    ET.SubElement(
        body,
        "geom",
        {
            "name": f"{body_name}_frame",
            "type": "box",
            "size": f"{half_l:.3f} {half_w + 0.01:.3f} {height / 2:.3f}",
            "pos": f"0 0 {height / 2:.3f}",
            "rgba": "0.4 0.4 0.5 1",
        },
    )

    # End rollers
    for side, x_off in [("left", -half_l), ("right", half_l)]:
        ET.SubElement(
            body,
            "geom",
            {
                "name": f"{body_name}_roller_{side}",
                "type": "cylinder",
                "size": f"0.02 {half_w:.3f}",
                "pos": f"{x_off:.3f} 0 {height:.3f}",
                "euler": "1.5708 0 0",
                "rgba": "0.5 0.5 0.5 1",
            },
        )

    # Ensure actuator section exists (for Phase 4 belt velocity)
    actuator = root.find("actuator")
    if actuator is None:
        ET.SubElement(root, "actuator")


def _add_camera_body_to_scene(
    worldbody: ET.Element,
    placement: EquipmentPlacement,
    body_name: str,
    entry: EquipmentEntry,
) -> None:
    """Add camera housing body.

    Args:
        worldbody: Worldbody XML element.
        placement: Equipment placement data.
        body_name: Unique body name.
        entry: Equipment catalog entry.
    """
    height = float(entry.specs.get("mounting_height_m", 1.5))
    body = ET.SubElement(
        worldbody,
        "body",
        {
            "name": body_name,
            "pos": f"{placement.position[0]:.3f} {placement.position[1]:.3f} {height:.3f}",
        },
    )
    ET.SubElement(
        body,
        "geom",
        {
            "name": f"{body_name}_housing",
            "type": "box",
            "size": "0.03 0.03 0.02",
            "rgba": "0.15 0.15 0.15 1",
        },
    )


def _add_fixture_to_scene(
    worldbody: ET.Element,
    placement: EquipmentPlacement,
    body_name: str,
    entry: EquipmentEntry,
) -> None:
    """Add fixture as static box geom.

    Args:
        worldbody: Worldbody XML element.
        placement: Equipment placement data.
        body_name: Unique body name.
        entry: Equipment catalog entry.
    """
    pos = _format_pos(placement.position)
    euler = f"0 0 {math.radians(placement.orientation_deg):.4f}"
    body = ET.SubElement(
        worldbody,
        "body",
        {"name": body_name, "pos": pos, "euler": euler},
    )
    size = _equipment_half_size(entry)
    ET.SubElement(
        body,
        "geom",
        {
            "name": f"{body_name}_geom",
            "type": "box",
            "size": f"{size[0]:.3f} {size[1]:.3f} {size[2]:.3f}",
            "rgba": _equipment_color(entry.type),
        },
    )


def _add_fallback_box(
    worldbody: ET.Element,
    placement: EquipmentPlacement,
    body_name: str,
) -> None:
    """Add a generic fallback box when no model is available.

    Args:
        worldbody: Worldbody XML element.
        placement: Equipment placement data.
        body_name: Unique body name.
    """
    pos = _format_pos(placement.position)
    euler = f"0 0 {math.radians(placement.orientation_deg):.4f}"
    body = ET.SubElement(
        worldbody,
        "body",
        {"name": body_name, "pos": pos, "euler": euler},
    )
    ET.SubElement(
        body,
        "geom",
        {
            "name": f"{body_name}_geom",
            "type": "box",
            "size": "0.15 0.15 0.15",
            "rgba": "0.8 0.2 0.2 1",
        },
    )


def _add_work_objects(
    worldbody: ET.Element,
    work_objects: list[WorkObject],
) -> None:
    """Add dynamic work objects for manipulation.

    Args:
        worldbody: Worldbody XML element.
        work_objects: Objects from recommendation.
    """
    for obj in work_objects:
        for i in range(obj.count):
            name = f"{obj.name}_{i}"
            pos = _format_pos(obj.position)

            body = ET.SubElement(
                worldbody,
                "body",
                {
                    "name": name,
                    "pos": pos,
                },
            )
            ET.SubElement(body, "freejoint", {"name": f"{name}_joint"})

            geom_attrs = {
                "name": f"{name}_geom",
                "type": obj.shape,
                "mass": f"{obj.mass_kg:.4f}",
                "rgba": "0.2 0.6 0.2 1",
            }
            if obj.shape == "box":
                geom_attrs["size"] = (
                    f"{obj.size[0] / 2:.4f} {obj.size[1] / 2:.4f} {obj.size[2] / 2:.4f}"
                )
            elif obj.shape == "cylinder":
                geom_attrs["size"] = f"{obj.size[0]:.4f} {obj.size[1] / 2:.4f}"
            elif obj.shape == "sphere":
                geom_attrs["size"] = f"{obj.size[0]:.4f}"

            ET.SubElement(body, "geom", geom_attrs)


def _add_cameras(
    root: ET.Element,
    placements: list[EquipmentPlacement],
    catalog: dict[str, EquipmentEntry],
) -> None:
    """Add MuJoCo camera elements for camera-type equipment.

    Args:
        root: Root mujoco element.
        placements: Equipment placements.
        catalog: Equipment catalog.
    """
    worldbody = root.find("worldbody")
    for placement in placements:
        entry = catalog.get(placement.equipment_id)
        if not entry or entry.type != "camera":
            continue

        fov = entry.specs.get("fov_deg", 60)
        height = entry.specs.get("mounting_height_m", 1.5)
        pos = f"{placement.position[0]:.3f} {placement.position[1]:.3f} {float(height):.3f}"
        ET.SubElement(
            worldbody,
            "camera",
            {
                "name": placement.equipment_id,
                "pos": pos,
                "zaxis": "0 0 -1",
                "fovy": str(int(fov)),
            },
        )


def _append_unique_children(
    scene_section: ET.Element,
    robot_section: ET.Element,
) -> None:
    """Append children from robot section, skipping duplicates.

    Deduplicates by tag + class/name attribute to prevent
    repeated default class errors on scene rebuild.

    Args:
        scene_section: Existing scene section element.
        robot_section: Robot section to merge from.
    """
    existing_keys = _collect_child_keys(scene_section)
    for child in robot_section:
        key = _child_key(child)
        if key not in existing_keys:
            scene_section.append(child)
            existing_keys.add(key)


def _child_key(element: ET.Element) -> tuple[str, ...]:
    """Create a unique key for an XML element.

    Uses tag + name + class + file to distinguish elements.
    File is needed for mesh elements without name attributes.

    Args:
        element: XML element.

    Returns:
        Tuple key for deduplication.
    """
    return (
        element.tag,
        element.get("name", ""),
        element.get("class", ""),
        element.get("file", ""),
    )


def _collect_child_keys(section: ET.Element) -> set[tuple[str, ...]]:
    """Collect unique keys for children of a section.

    Args:
        section: XML element.

    Returns:
        Set of (tag, name, class) keys.
    """
    return {_child_key(c) for c in section}


def _format_pos(position: tuple[float, float, float]) -> str:
    """Format 3D position for MJCF attribute.

    Args:
        position: (x, y, z) tuple.

    Returns:
        Space-separated string.
    """
    return f"{position[0]:.3f} {position[1]:.3f} {position[2]:.3f}"


def _has_mjcf(model_dir: Path) -> bool:
    """Check if directory contains MJCF files.

    Args:
        model_dir: Directory to check.

    Returns:
        True if .xml files exist.
    """
    return any(model_dir.glob("*.xml"))


def _find_mjcf(model_dir: Path) -> Path:
    """Find the main MJCF file in a model directory.

    Args:
        model_dir: Model directory.

    Returns:
        Path to main MJCF file.
    """
    xmls = sorted(model_dir.glob("*.xml"))
    for xml in xmls:
        if xml.stem not in ("scene",):
            return xml
    return xmls[0]


def _inline_include(
    _root: ET.Element,
    body: ET.Element,
    mjcf_file: Path,
    _scene_dir: Path,
) -> None:
    """Include external MJCF model into scene.

    Args:
        root: Root mujoco element.
        body: Parent body element.
        mjcf_file: Path to external MJCF.
        scene_dir: Scene directory for relative paths.
    """
    body.set("childclass", mjcf_file.stem)
    ET.SubElement(
        body,
        "include",
        {
            "file": str(mjcf_file),
        },
    )


def _equipment_half_size(
    entry: EquipmentEntry,
) -> tuple[float, float, float]:
    """Get equipment half-sizes for box geom.

    Args:
        entry: Equipment entry.

    Returns:
        (half_x, half_y, half_z) in meters.
    """
    specs = entry.specs
    if "length_m" in specs and "width_m" in specs:
        return (
            float(specs["length_m"]) / 2,
            float(specs["width_m"]) / 2,
            float(specs.get("height_m", 0.85)) / 2,
        )
    if entry.type == "manipulator":
        reach = float(specs.get("reach_m", 0.5))
        return (0.15, 0.15, reach / 2)
    return (0.15, 0.15, 0.15)


def _equipment_color(eq_type: str) -> str:
    """Get RGBA color string by equipment type.

    Args:
        eq_type: Equipment type.

    Returns:
        RGBA string for MuJoCo.
    """
    colors = {
        "manipulator": "0.8 0.2 0.2 1",
        "conveyor": "0.2 0.2 0.8 1",
        "camera": "0.2 0.8 0.2 1",
        "fixture": "0.6 0.6 0.6 1",
    }
    return colors.get(eq_type, "0.5 0.5 0.5 1")


def _is_valid_mesh(mesh_path: Path) -> bool:
    """Check if mesh file exists and can be loaded by MuJoCo.

    Args:
        mesh_path: Path to mesh file.

    Returns:
        True if mesh is usable.
    """
    if not mesh_path.exists():
        return False
    if mesh_path.stat().st_size < 10000:
        return False
    try:
        import mujoco

        path_str = str(mesh_path).replace(chr(92), "/")
        test_xml = (
            f'<mujoco><asset><mesh name="t" file="{path_str}"/></asset>'
            f'<worldbody><geom type="mesh" mesh="t"/></worldbody></mujoco>'
        )
        mujoco.MjModel.from_xml_string(test_xml)
        return True
    except Exception:
        return False
