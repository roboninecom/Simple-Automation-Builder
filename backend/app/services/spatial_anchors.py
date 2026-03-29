"""Spatial anchor computation — project 3D points into image pixel coordinates.

For each registered photo, produces a set of reference points mapping
pixel locations to real-world 3D coordinates. Claude Vision uses these
anchors to position detected equipment precisely.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel

from backend.app.models.space import Dimensions
from backend.app.services.reconstruction import _transform_point_colmap_to_threejs

if TYPE_CHECKING:
    import pycolmap

__all__ = [
    "SpatialAnchor",
    "ImageAnchors",
    "compute_all_anchors",
    "compute_anchors_for_image",
]

logger = logging.getLogger(__name__)

_MAX_ANCHORS_PER_IMAGE = 40
_MAX_IMAGES = 10
_GRID_CELLS = 4
_FLOOR_TOLERANCE = 0.3
_WALL_TOLERANCE = 0.3
_CEILING_TOLERANCE = 0.3
_MAX_FLOOR_ANCHORS = 5
_MAX_WALL_ANCHORS_PER_WALL = 3
_MAX_CEILING_ANCHORS = 3


class SpatialAnchor(BaseModel):
    """A single pixel-to-world coordinate mapping.

    Args:
        pixel: Pixel coordinates (x, y) in image space.
        world: World coordinates (x, y, z) in meters (Three.js convention).
        label: Descriptive label for the anchor type.
    """

    pixel: tuple[int, int]
    world: tuple[float, float, float]
    label: str


class ImageAnchors(BaseModel):
    """Spatial anchors for a single registered image.

    Args:
        image_name: Filename of the image.
        image_id: pycolmap image ID.
        camera_position: Camera center in world coordinates (Three.js).
        viewing_direction: Camera viewing direction in world coordinates (Three.js).
        anchors: List of spatial anchor points.
    """

    image_name: str
    image_id: int
    camera_position: tuple[float, float, float]
    viewing_direction: tuple[float, float, float]
    anchors: list[SpatialAnchor]


def compute_all_anchors(
    reconstruction: pycolmap.Reconstruction,
    dims: Dimensions,
) -> list[ImageAnchors]:
    """Compute spatial anchors for all registered images.

    Args:
        reconstruction: pycolmap Reconstruction object.
        dims: Room dimensions for boundary classification.

    Returns:
        List of ImageAnchors, sorted by anchor count (most first), capped at
        _MAX_IMAGES.
    """
    results: list[ImageAnchors] = []
    for img_id, image in reconstruction.images.items():
        if not image.has_pose:
            continue
        anchors = compute_anchors_for_image(reconstruction, img_id, dims)
        if anchors.anchors:
            results.append(anchors)

    results.sort(key=lambda ia: len(ia.anchors), reverse=True)
    return results[:_MAX_IMAGES]


def compute_anchors_for_image(
    reconstruction: pycolmap.Reconstruction,
    image_id: int,
    dims: Dimensions,
) -> ImageAnchors:
    """Compute spatial anchors for a single registered image.

    Projects visible 3D points into image pixel space and selects a diverse
    subset covering floor, walls, ceiling, and interior regions.

    Args:
        reconstruction: pycolmap Reconstruction object.
        image_id: ID of the image to process.
        dims: Room dimensions for point classification.

    Returns:
        ImageAnchors with up to _MAX_ANCHORS_PER_IMAGE anchors.
    """
    image = reconstruction.images[image_id]
    camera = reconstruction.cameras[image.camera_id]

    center_colmap = image.projection_center()
    direction_colmap = image.viewing_direction()
    center = _transform_point_colmap_to_threejs(center_colmap)
    direction = _transform_point_colmap_to_threejs(direction_colmap)

    visible_points = _collect_visible_points(reconstruction, image, camera)
    classified = _classify_points(visible_points, dims)
    selected = _select_diverse_anchors(classified, camera.width, camera.height)

    corner_anchors = _project_room_corners(image, dims)
    selected.extend(corner_anchors)

    selected = selected[:_MAX_ANCHORS_PER_IMAGE]

    return ImageAnchors(
        image_name=image.name,
        image_id=image_id,
        camera_position=tuple(center.tolist()),
        viewing_direction=tuple(direction.tolist()),
        anchors=selected,
    )


def _collect_visible_points(
    reconstruction: pycolmap.Reconstruction,
    image: pycolmap.Image,
    camera: pycolmap.Camera,
) -> list[tuple[tuple[int, int], np.ndarray]]:
    """Collect 3D points visible in an image with their pixel projections.

    Args:
        reconstruction: pycolmap Reconstruction.
        image: The image to project into.
        camera: Camera intrinsics for this image.

    Returns:
        List of (pixel_xy, world_xyz_threejs) tuples for visible points.
    """
    results: list[tuple[tuple[int, int], np.ndarray]] = []

    for point3d in reconstruction.points3D.values():
        pixel = image.project_point(point3d.xyz)
        if pixel is None:
            continue

        px, py = int(round(pixel[0])), int(round(pixel[1]))
        if px < 0 or px >= camera.width or py < 0 or py >= camera.height:
            continue

        world_threejs = _transform_point_colmap_to_threejs(point3d.xyz)
        results.append(((px, py), world_threejs))

    return results


def _classify_points(
    points: list[tuple[tuple[int, int], np.ndarray]],
    dims: Dimensions,
) -> dict[str, list[tuple[tuple[int, int], np.ndarray]]]:
    """Classify projected points by spatial region.

    Args:
        points: List of (pixel, world_xyz) tuples.
        dims: Room dimensions.

    Returns:
        Dict mapping region label to points in that region.
    """
    classified: dict[str, list[tuple[tuple[int, int], np.ndarray]]] = {
        "floor": [],
        "ceiling": [],
        "wall_W": [],
        "wall_E": [],
        "wall_S": [],
        "wall_N": [],
        "interior": [],
    }

    for pixel, world in points:
        x, y, z = float(world[0]), float(world[1]), float(world[2])

        if abs(z) < _FLOOR_TOLERANCE:
            classified["floor"].append((pixel, world))
        elif abs(z - dims.ceiling_m) < _CEILING_TOLERANCE:
            classified["ceiling"].append((pixel, world))
        elif abs(x) < _WALL_TOLERANCE:
            classified["wall_W"].append((pixel, world))
        elif abs(x - dims.width_m) < _WALL_TOLERANCE:
            classified["wall_E"].append((pixel, world))
        elif abs(y) < _WALL_TOLERANCE:
            classified["wall_S"].append((pixel, world))
        elif abs(y - dims.length_m) < _WALL_TOLERANCE:
            classified["wall_N"].append((pixel, world))
        else:
            classified["interior"].append((pixel, world))

    return classified


def _select_diverse_anchors(
    classified: dict[str, list[tuple[tuple[int, int], np.ndarray]]],
    img_width: int,
    img_height: int,
) -> list[SpatialAnchor]:
    """Select a diverse subset of anchors from classified points.

    Picks anchors from each region type, then fills remaining budget with
    grid-sampled interior points for spatial coverage.

    Args:
        classified: Points grouped by region.
        img_width: Image width in pixels.
        img_height: Image height in pixels.

    Returns:
        List of selected SpatialAnchors.
    """
    selected: list[SpatialAnchor] = []

    selected.extend(
        _sample_from_region(classified["floor"], "floor_point", _MAX_FLOOR_ANCHORS)
    )
    selected.extend(
        _sample_from_region(classified["ceiling"], "ceiling_point", _MAX_CEILING_ANCHORS)
    )

    for wall_key in ("wall_W", "wall_E", "wall_S", "wall_N"):
        selected.extend(
            _sample_from_region(
                classified[wall_key], wall_key, _MAX_WALL_ANCHORS_PER_WALL
            )
        )

    remaining_budget = _MAX_ANCHORS_PER_IMAGE - len(selected) - 8  # reserve for corners
    if remaining_budget > 0:
        all_interior = classified["interior"]
        grid_anchors = _grid_sample(all_interior, img_width, img_height, remaining_budget)
        selected.extend(grid_anchors)

    return selected


def _sample_from_region(
    points: list[tuple[tuple[int, int], np.ndarray]],
    label: str,
    max_count: int,
) -> list[SpatialAnchor]:
    """Sample points from a region with spatial diversity.

    Args:
        points: Available points in the region.
        label: Label to assign to anchors.
        max_count: Maximum number to select.

    Returns:
        List of SpatialAnchors.
    """
    if not points:
        return []

    if len(points) <= max_count:
        return [
            SpatialAnchor(
                pixel=px,
                world=tuple(w.tolist()),
                label=label,
            )
            for px, w in points
        ]

    indices = np.linspace(0, len(points) - 1, max_count, dtype=int)
    return [
        SpatialAnchor(
            pixel=points[i][0],
            world=tuple(points[i][1].tolist()),
            label=label,
        )
        for i in indices
    ]


def _grid_sample(
    points: list[tuple[tuple[int, int], np.ndarray]],
    img_width: int,
    img_height: int,
    max_count: int,
) -> list[SpatialAnchor]:
    """Sample points using a grid for spatial coverage.

    Divides the image into a grid and picks the point closest to each
    cell center.

    Args:
        points: Available interior points.
        img_width: Image width in pixels.
        img_height: Image height in pixels.
        max_count: Maximum anchors to return.

    Returns:
        Grid-sampled SpatialAnchors.
    """
    if not points:
        return []

    cell_w = img_width / _GRID_CELLS
    cell_h = img_height / _GRID_CELLS
    selected: list[SpatialAnchor] = []

    for row in range(_GRID_CELLS):
        for col in range(_GRID_CELLS):
            center_x = (col + 0.5) * cell_w
            center_y = (row + 0.5) * cell_h

            best_dist = float("inf")
            best_point = None
            for px, w in points:
                dist = (px[0] - center_x) ** 2 + (px[1] - center_y) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_point = (px, w)

            if best_point is not None:
                selected.append(
                    SpatialAnchor(
                        pixel=best_point[0],
                        world=tuple(best_point[1].tolist()),
                        label="grid_sample",
                    )
                )

            if len(selected) >= max_count:
                return selected

    return selected


def _project_room_corners(
    image: pycolmap.Image,
    dims: Dimensions,
) -> list[SpatialAnchor]:
    """Project room bounding box corners into the image.

    Args:
        image: The image to project into.
        dims: Room dimensions.

    Returns:
        SpatialAnchors for visible room corners.
    """
    corners_threejs = [
        (np.array([0.0, 0.0, 0.0]), "room_corner_SW_floor"),
        (np.array([dims.width_m, 0.0, 0.0]), "room_corner_SE_floor"),
        (np.array([0.0, dims.length_m, 0.0]), "room_corner_NW_floor"),
        (np.array([dims.width_m, dims.length_m, 0.0]), "room_corner_NE_floor"),
        (np.array([0.0, 0.0, dims.ceiling_m]), "room_corner_SW_ceiling"),
        (np.array([dims.width_m, 0.0, dims.ceiling_m]), "room_corner_SE_ceiling"),
        (np.array([0.0, dims.length_m, dims.ceiling_m]), "room_corner_NW_ceiling"),
        (np.array([dims.width_m, dims.length_m, dims.ceiling_m]), "room_corner_NE_ceiling"),
    ]

    anchors: list[SpatialAnchor] = []
    for corner_threejs, label in corners_threejs:
        corner_colmap = np.array(
            [corner_threejs[0], -corner_threejs[1], -corner_threejs[2]]
        )
        pixel = image.project_point(corner_colmap)
        if pixel is None:
            continue

        px, py = int(round(pixel[0])), int(round(pixel[1]))
        anchors.append(
            SpatialAnchor(
                pixel=(px, py),
                world=tuple(corner_threejs.tolist()),
                label=label,
            )
        )

    return anchors
