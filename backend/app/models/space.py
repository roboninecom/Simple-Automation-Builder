"""Space and scene models for room capture and reconstruction."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "DimensionCalibration",
    "Dimensions",
    "Door",
    "ExistingEquipment",
    "ReferenceCalibration",
    "SceneAnalysis",
    "SceneReconstruction",
    "SpaceModel",
    "Window",
    "Zone",
]


class ReferenceCalibration(BaseModel):
    """Calibration of reconstruction scale using a known real-world measurement.

    Args:
        point_a: First point in mesh coordinates.
        point_b: Second point in mesh coordinates.
        real_distance_m: Real-world distance between the two points in meters.
    """

    point_a: tuple[float, float, float]
    point_b: tuple[float, float, float]
    real_distance_m: float = Field(gt=0)


class DimensionCalibration(BaseModel):
    """Calibration via direct room dimensions input.

    Args:
        width_m: Real room width in meters.
        length_m: Real room length in meters.
        ceiling_m: Real ceiling height in meters.
    """

    width_m: float = Field(gt=0)
    length_m: float = Field(gt=0)
    ceiling_m: float = Field(default=2.7, gt=0)


class Dimensions(BaseModel):
    """Room dimensions derived from calibrated reconstruction.

    Args:
        width_m: Room width in meters.
        length_m: Room length in meters.
        ceiling_m: Ceiling height in meters.
        area_m2: Floor area in square meters.
    """

    width_m: float = Field(gt=0)
    length_m: float = Field(gt=0)
    ceiling_m: float = Field(gt=0)
    area_m2: float = Field(gt=0)


class Zone(BaseModel):
    """Functional zone within the room.

    Args:
        name: Zone name (e.g. "workstation_1", "storage").
        polygon: 2D contour of the zone in meters (list of (x, y) points).
        area_m2: Zone area in square meters.
    """

    name: str
    polygon: list[tuple[float, float]]
    area_m2: float = Field(gt=0)


class Door(BaseModel):
    """Door detected in the room.

    Args:
        position: 2D position (x, y) in meters.
        width_m: Door width in meters.
        height_m: Door height in meters.
        wall: Which wall the door is on.
    """

    position: tuple[float, float]
    width_m: float = Field(gt=0)
    height_m: float = Field(default=2.1, gt=0)
    wall: Literal["north", "south", "east", "west"] = "south"


class Window(BaseModel):
    """Window detected in the room.

    Args:
        position: 2D position (x, y) in meters.
        width_m: Window width in meters.
        height_m: Window height in meters.
        sill_height_m: Height from floor to bottom of window in meters.
        wall: Which wall the window is on.
    """

    position: tuple[float, float]
    width_m: float = Field(gt=0)
    height_m: float = Field(default=1.2, gt=0)
    sill_height_m: float = Field(default=0.9, ge=0)
    wall: Literal["north", "south", "east", "west"] = "west"


class ExistingEquipment(BaseModel):
    """Equipment already present in the room, detected by Claude Vision.

    Args:
        name: Equipment name (e.g. "3d_printer_1", "workbench").
        category: Equipment category (e.g. "printer", "table").
        position: 3D position (x, y, z) in meters.
        confidence: Detection confidence score (0.0 to 1.0).
        dimensions: Width, depth, height in meters.
        orientation_deg: Rotation around Z-axis in degrees (0 = aligned with X).
        rgba: Approximate color from photo (r, g, b, a), normalized 0-1.
        mounting: Where the item is attached.
        shape: Geometric primitive for rendering.
    """

    name: str
    category: str
    position: tuple[float, float, float]
    confidence: float = Field(ge=0.0, le=1.0)
    dimensions: tuple[float, float, float] = (0.4, 0.4, 0.8)
    orientation_deg: float = 0.0
    rgba: tuple[float, float, float, float] = (0.5, 0.5, 0.5, 1.0)
    mounting: Literal["floor", "wall", "ceiling"] = "floor"
    shape: Literal["box", "cylinder"] = "box"


class SceneReconstruction(BaseModel):
    """Result of pycolmap scene reconstruction.

    Args:
        mesh_path: Path to the reconstructed mesh file.
        mjcf_path: Path to the MJCF scene file (base for adding equipment).
        pointcloud_path: Path to the point cloud file.
        dimensions: Room dimensions from the calibrated mesh.
        metadata_path: Path to reconstruction metadata JSON (camera poses, intrinsics).
        sparse_dir: Path to sparse reconstruction directory (for pycolmap reload).
    """

    mesh_path: Path
    mjcf_path: Path
    pointcloud_path: Path
    dimensions: Dimensions
    metadata_path: Path | None = None
    sparse_dir: Path | None = None


class SceneAnalysis(BaseModel):
    """Result of Claude Vision scene analysis.

    Args:
        zones: Functional zones detected in the room.
        existing_equipment: Equipment already present.
        doors: Doors detected.
        windows: Windows detected.
    """

    zones: list[Zone] = Field(default_factory=list)
    existing_equipment: list[ExistingEquipment] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)


class SpaceModel(BaseModel):
    """Complete room model for simulation — merges reconstruction and analysis.

    Args:
        dimensions: Room dimensions.
        zones: Functional zones.
        existing_equipment: Equipment already in the room.
        doors: Doors.
        windows: Windows.
        reconstruction: Reference to scene reconstruction data.
    """

    dimensions: Dimensions
    zones: list[Zone] = Field(default_factory=list)
    existing_equipment: list[ExistingEquipment] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    reconstruction: SceneReconstruction
