"""Tests for spatial anchor computation."""

from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.app.models.space import Dimensions
from backend.app.services.spatial_anchors import (
    ImageAnchors,
    SpatialAnchor,
    _classify_points,
    _grid_sample,
    _project_room_corners,
    _sample_from_region,
    _select_diverse_anchors,
    compute_all_anchors,
    compute_anchors_for_image,
)

_DIMS = Dimensions(width_m=6.0, length_m=4.0, ceiling_m=2.7, area_m2=24.0)


def _make_mock_reconstruction(
    num_images: int = 2,
    num_points: int = 50,
    img_width: int = 1000,
    img_height: int = 800,
) -> MagicMock:
    """Create a mock pycolmap.Reconstruction with projectable points.

    Args:
        num_images: Number of registered images.
        num_points: Number of 3D points.
        img_width: Image width.
        img_height: Image height.

    Returns:
        Mock Reconstruction.
    """
    recon = MagicMock()

    # Camera
    cam = MagicMock()
    cam.width = img_width
    cam.height = img_height
    recon.cameras = {1: cam}

    # Images
    images = {}
    for i in range(1, num_images + 1):
        img = MagicMock()
        img.name = f"IMG_{i:04d}.jpg"
        img.camera_id = 1
        img.has_pose = True
        img.projection_center.return_value = np.array([3.0, 2.0, 1.5])
        img.viewing_direction.return_value = np.array([0.0, 1.0, 0.0])

        def _project(xyz, _img_w=img_width, _img_h=img_height):
            """Simple projection: map xyz to pixel within bounds."""
            px = int(xyz[0] * 100 + _img_w / 2)
            py = int(xyz[1] * 100 + _img_h / 2)
            if 0 <= px < _img_w and 0 <= py < _img_h:
                return np.array([px, py], dtype=float)
            return None

        img.project_point = _project
        images[i] = img
    recon.images = images

    # 3D points spread across room
    points = {}
    rng = np.random.default_rng(42)
    for pid in range(num_points):
        pt = MagicMock()
        x = rng.uniform(0, 6)
        y = rng.uniform(0, 4)
        z = rng.choice([0.0, 0.0, 0.0, 1.3, 2.7])  # mostly floor
        pt.xyz = np.array([x, y, z])
        points[pid] = pt
    recon.points3D = points

    return recon


class TestSpatialAnchorModel:
    """Tests for Pydantic models."""

    def test_anchor_creation(self) -> None:
        a = SpatialAnchor(pixel=(100, 200), world=(1.0, 2.0, 0.0), label="floor")
        assert a.pixel == (100, 200)
        assert a.world == (1.0, 2.0, 0.0)

    def test_image_anchors_creation(self) -> None:
        ia = ImageAnchors(
            image_name="test.jpg",
            image_id=1,
            camera_position=(0.0, 0.0, 1.5),
            viewing_direction=(0.0, 1.0, 0.0),
            anchors=[SpatialAnchor(pixel=(0, 0), world=(0, 0, 0), label="test")],
        )
        assert ia.image_name == "test.jpg"
        assert len(ia.anchors) == 1


class TestClassifyPoints:
    """Tests for point classification by spatial region."""

    def test_floor_point(self) -> None:
        points = [((100, 200), np.array([3.0, 2.0, 0.1]))]
        classified = _classify_points(points, _DIMS)
        assert len(classified["floor"]) == 1
        assert len(classified["interior"]) == 0

    def test_ceiling_point(self) -> None:
        points = [((100, 200), np.array([3.0, 2.0, 2.6]))]
        classified = _classify_points(points, _DIMS)
        assert len(classified["ceiling"]) == 1

    def test_wall_points(self) -> None:
        points = [
            ((10, 100), np.array([0.1, 2.0, 1.0])),   # west wall
            ((900, 100), np.array([5.9, 2.0, 1.0])),   # east wall
            ((500, 10), np.array([3.0, 0.1, 1.0])),    # south wall
            ((500, 700), np.array([3.0, 3.9, 1.0])),   # north wall
        ]
        classified = _classify_points(points, _DIMS)
        assert len(classified["wall_W"]) == 1
        assert len(classified["wall_E"]) == 1
        assert len(classified["wall_S"]) == 1
        assert len(classified["wall_N"]) == 1

    def test_interior_point(self) -> None:
        points = [((500, 400), np.array([3.0, 2.0, 1.0]))]
        classified = _classify_points(points, _DIMS)
        assert len(classified["interior"]) == 1

    def test_empty_input(self) -> None:
        classified = _classify_points([], _DIMS)
        assert all(len(v) == 0 for v in classified.values())


class TestSampleFromRegion:
    """Tests for region sampling."""

    def test_returns_all_when_under_limit(self) -> None:
        points = [
            ((100, 200), np.array([1.0, 2.0, 0.0])),
            ((300, 400), np.array([3.0, 4.0, 0.0])),
        ]
        result = _sample_from_region(points, "floor", max_count=5)
        assert len(result) == 2
        assert all(a.label == "floor" for a in result)

    def test_samples_down_when_over_limit(self) -> None:
        points = [((i * 10, i * 10), np.array([float(i), 0, 0])) for i in range(20)]
        result = _sample_from_region(points, "test", max_count=5)
        assert len(result) == 5

    def test_empty_region(self) -> None:
        result = _sample_from_region([], "floor", max_count=5)
        assert result == []


class TestGridSample:
    """Tests for grid-based sampling."""

    def test_produces_diverse_points(self) -> None:
        points = [
            ((100, 100), np.array([1, 1, 1])),
            ((900, 100), np.array([5, 1, 1])),
            ((100, 700), np.array([1, 3, 1])),
            ((900, 700), np.array([5, 3, 1])),
            ((500, 400), np.array([3, 2, 1])),
        ]
        result = _grid_sample(points, 1000, 800, max_count=16)
        assert len(result) > 0
        assert all(a.label == "grid_sample" for a in result)

    def test_respects_max_count(self) -> None:
        points = [((i * 50, i * 50), np.array([float(i), 0, 0])) for i in range(20)]
        result = _grid_sample(points, 1000, 800, max_count=3)
        assert len(result) <= 3

    def test_empty_input(self) -> None:
        result = _grid_sample([], 1000, 800, max_count=10)
        assert result == []


class TestSelectDiverseAnchors:
    """Tests for diverse anchor selection."""

    def test_includes_multiple_regions(self) -> None:
        classified = {
            "floor": [((100, 700), np.array([1, 1, 0.0]))],
            "ceiling": [((100, 100), np.array([1, 1, 2.7]))],
            "wall_W": [((10, 400), np.array([0.0, 2, 1]))],
            "wall_E": [((990, 400), np.array([6.0, 2, 1]))],
            "wall_S": [],
            "wall_N": [],
            "interior": [((500, 400), np.array([3, 2, 1]))],
        }
        result = _select_diverse_anchors(classified, 1000, 800)
        labels = {a.label for a in result}
        assert "floor_point" in labels
        assert "ceiling_point" in labels
        assert "wall_W" in labels


class TestProjectRoomCorners:
    """Tests for room corner projection."""

    def test_projects_visible_corners(self) -> None:
        image = MagicMock()

        def _project(xyz):
            return np.array([500.0, 400.0])

        image.project_point = _project
        dims = Dimensions(width_m=5.0, length_m=4.0, ceiling_m=2.5, area_m2=20.0)
        result = _project_room_corners(image, dims)
        assert len(result) == 8  # all corners visible
        labels = {a.label for a in result}
        assert "room_corner_SW_floor" in labels
        assert "room_corner_NE_ceiling" in labels

    def test_skips_corners_behind_camera(self) -> None:
        image = MagicMock()
        image.project_point.return_value = None  # all behind camera
        dims = Dimensions(width_m=5.0, length_m=4.0, ceiling_m=2.5, area_m2=20.0)
        result = _project_room_corners(image, dims)
        assert len(result) == 0

    def test_corner_world_coords_are_threejs(self) -> None:
        image = MagicMock()
        image.project_point = lambda xyz: np.array([100.0, 200.0])
        dims = Dimensions(width_m=5.0, length_m=4.0, ceiling_m=2.5, area_m2=20.0)
        result = _project_room_corners(image, dims)
        floor_sw = next(a for a in result if a.label == "room_corner_SW_floor")
        assert floor_sw.world == (0.0, 0.0, 0.0)
        ceiling_ne = next(a for a in result if a.label == "room_corner_NE_ceiling")
        assert ceiling_ne.world == (5.0, 4.0, 2.5)


class TestComputeAnchorsForImage:
    """Tests for single-image anchor computation."""

    def test_returns_image_anchors(self) -> None:
        recon = _make_mock_reconstruction(num_images=1, num_points=30)
        result = compute_anchors_for_image(recon, 1, _DIMS)
        assert isinstance(result, ImageAnchors)
        assert result.image_name == "IMG_0001.jpg"
        assert result.image_id == 1

    def test_anchors_within_bounds(self) -> None:
        recon = _make_mock_reconstruction(num_images=1, num_points=50)
        result = compute_anchors_for_image(recon, 1, _DIMS)
        cam = recon.cameras[1]
        for anchor in result.anchors:
            assert 0 <= anchor.pixel[0] < cam.width or anchor.label.startswith("room_corner")
            assert 0 <= anchor.pixel[1] < cam.height or anchor.label.startswith("room_corner")

    def test_capped_at_max_anchors(self) -> None:
        recon = _make_mock_reconstruction(num_images=1, num_points=500)
        result = compute_anchors_for_image(recon, 1, _DIMS)
        assert len(result.anchors) <= 40


class TestComputeAllAnchors:
    """Tests for multi-image anchor computation."""

    def test_returns_list_of_image_anchors(self) -> None:
        recon = _make_mock_reconstruction(num_images=3, num_points=30)
        results = compute_all_anchors(recon, _DIMS)
        assert isinstance(results, list)
        assert all(isinstance(r, ImageAnchors) for r in results)

    def test_skips_images_without_pose(self) -> None:
        recon = _make_mock_reconstruction(num_images=3, num_points=30)
        recon.images[2].has_pose = False
        results = compute_all_anchors(recon, _DIMS)
        names = {r.image_name for r in results}
        assert "IMG_0002.jpg" not in names

    def test_capped_at_max_images(self) -> None:
        recon = _make_mock_reconstruction(num_images=15, num_points=30)
        results = compute_all_anchors(recon, _DIMS)
        assert len(results) <= 10

    def test_sorted_by_anchor_count(self) -> None:
        recon = _make_mock_reconstruction(num_images=3, num_points=30)
        results = compute_all_anchors(recon, _DIMS)
        if len(results) >= 2:
            assert len(results[0].anchors) >= len(results[1].anchors)
