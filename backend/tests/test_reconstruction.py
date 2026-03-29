"""Tests for reconstruction and calibration logic."""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from backend.app.models.space import Dimensions, ReferenceCalibration
from backend.app.services.reconstruction import (
    _compute_scale_factor,
    _compute_scale_from_dimensions,
    _scale_dimensions,
    _transform_point_colmap_to_threejs,
    check_reconstruction_deps,
    export_reconstruction_metadata,
    rescale_pointcloud,
    transform_colmap_to_threejs,
)


class TestScaleCalibration:
    """Tests for scale calibration math."""

    def test_scale_factor_identity(self) -> None:
        cal = ReferenceCalibration(
            point_a=(0.0, 0.0, 0.0),
            point_b=(1.0, 0.0, 0.0),
            real_distance_m=1.0,
        )
        factor = _compute_scale_factor(cal)
        assert abs(factor - 1.0) < 1e-6

    def test_scale_factor_double(self) -> None:
        cal = ReferenceCalibration(
            point_a=(0.0, 0.0, 0.0),
            point_b=(1.0, 0.0, 0.0),
            real_distance_m=2.0,
        )
        factor = _compute_scale_factor(cal)
        assert abs(factor - 2.0) < 1e-6

    def test_scale_factor_3d_diagonal(self) -> None:
        cal = ReferenceCalibration(
            point_a=(0.0, 0.0, 0.0),
            point_b=(1.0, 1.0, 1.0),
            real_distance_m=np.sqrt(3.0),
        )
        factor = _compute_scale_factor(cal)
        assert abs(factor - 1.0) < 1e-6

    def test_scale_factor_half(self) -> None:
        cal = ReferenceCalibration(
            point_a=(0.0, 0.0, 0.0),
            point_b=(2.0, 0.0, 0.0),
            real_distance_m=1.0,
        )
        factor = _compute_scale_factor(cal)
        assert abs(factor - 0.5) < 1e-6

    def test_scale_dimensions(self) -> None:
        dims = Dimensions(width_m=10.0, length_m=8.0, ceiling_m=5.0, area_m2=80.0)
        scaled = _scale_dimensions(dims, 0.5)
        assert abs(scaled.width_m - 5.0) < 1e-6
        assert abs(scaled.length_m - 4.0) < 1e-6
        assert abs(scaled.ceiling_m - 2.5) < 1e-6
        assert abs(scaled.area_m2 - 20.0) < 1e-6


class TestScaleFromDimensions:
    """Tests for scale computation from direct room dimensions."""

    def test_identity_scale(self) -> None:
        uncalibrated = Dimensions(width_m=5.0, length_m=4.0, ceiling_m=2.5, area_m2=20.0)
        factor = _compute_scale_from_dimensions(uncalibrated, 5.0, 4.0)
        assert abs(factor - 1.0) < 1e-6

    def test_double_scale(self) -> None:
        uncalibrated = Dimensions(width_m=2.5, length_m=2.0, ceiling_m=1.25, area_m2=5.0)
        factor = _compute_scale_from_dimensions(uncalibrated, 5.0, 4.0)
        assert abs(factor - 2.0) < 1e-6

    def test_average_of_ratios(self) -> None:
        uncalibrated = Dimensions(width_m=2.0, length_m=4.0, ceiling_m=2.0, area_m2=8.0)
        # scale_w = 4.0/2.0 = 2.0, scale_l = 6.0/4.0 = 1.5, avg = 1.75
        factor = _compute_scale_from_dimensions(uncalibrated, 4.0, 6.0)
        assert abs(factor - 1.75) < 1e-6

    def test_fractional_scale(self) -> None:
        uncalibrated = Dimensions(width_m=10.0, length_m=8.0, ceiling_m=5.0, area_m2=80.0)
        factor = _compute_scale_from_dimensions(uncalibrated, 5.0, 4.0)
        assert abs(factor - 0.5) < 1e-6


class TestCoordinateTransform:
    """Tests for COLMAP → Three.js coordinate transform."""

    def test_y_axis_flipped(self) -> None:
        points = np.array([[1.0, 2.0, 3.0]])
        result = transform_colmap_to_threejs(points)
        assert result[0, 0] == 1.0
        assert result[0, 1] == -2.0
        assert result[0, 2] == -3.0

    def test_origin_unchanged(self) -> None:
        points = np.array([[0.0, 0.0, 0.0]])
        result = transform_colmap_to_threejs(points)
        np.testing.assert_array_equal(result, points)

    def test_multiple_points(self) -> None:
        points = np.array(
            [
                [1.0, 2.0, 3.0],
                [-1.0, -2.0, -3.0],
            ]
        )
        result = transform_colmap_to_threejs(points)
        assert result.shape == (2, 3)
        np.testing.assert_array_almost_equal(
            result,
            [[1.0, -2.0, -3.0], [-1.0, 2.0, 3.0]],
        )

    def test_preserves_x(self) -> None:
        points = np.array([[5.0, 0.0, 0.0]])
        result = transform_colmap_to_threejs(points)
        assert result[0, 0] == 5.0


class TestRescalePointcloud:
    """Tests for point cloud rescaling."""

    def test_rescale_doubles_vertices(self, tmp_path: Path) -> None:
        import trimesh

        vertices = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        cloud = trimesh.PointCloud(vertices=vertices)
        ply_path = tmp_path / "test.ply"
        cloud.export(str(ply_path))

        rescale_pointcloud(ply_path, 2.0)

        reloaded = trimesh.load(str(ply_path))
        np.testing.assert_array_almost_equal(
            reloaded.vertices,
            [[2.0, 4.0, 6.0], [8.0, 10.0, 12.0]],
        )

    def test_rescale_halves_vertices(self, tmp_path: Path) -> None:
        import trimesh

        vertices = np.array([[10.0, 20.0, 30.0]])
        cloud = trimesh.PointCloud(vertices=vertices)
        ply_path = tmp_path / "test.ply"
        cloud.export(str(ply_path))

        rescale_pointcloud(ply_path, 0.5)

        reloaded = trimesh.load(str(ply_path))
        np.testing.assert_array_almost_equal(
            reloaded.vertices,
            [[5.0, 10.0, 15.0]],
        )


class TestTransformPointColmapToThreejs:
    """Tests for single-point COLMAP → Three.js transform."""

    def test_flips_y_and_z(self) -> None:
        point = np.array([1.0, 2.0, 3.0])
        result = _transform_point_colmap_to_threejs(point)
        np.testing.assert_array_almost_equal(result, [1.0, -2.0, -3.0])

    def test_origin_unchanged(self) -> None:
        point = np.array([0.0, 0.0, 0.0])
        result = _transform_point_colmap_to_threejs(point)
        np.testing.assert_array_almost_equal(result, [0.0, 0.0, 0.0])


def _make_mock_reconstruction(
    num_cameras: int = 1,
    num_images: int = 3,
    num_points: int = 100,
    photo_names: list[str] | None = None,
) -> MagicMock:
    """Create a mock pycolmap.Reconstruction for testing metadata export.

    Args:
        num_cameras: Number of cameras.
        num_images: Number of registered images.
        num_points: Number of 3D points.
        photo_names: Optional image filenames.

    Returns:
        Mock Reconstruction object.
    """
    recon = MagicMock()

    # Cameras
    cameras = {}
    for i in range(1, num_cameras + 1):
        cam = MagicMock()
        cam.model = "PINHOLE"
        cam.width = 4032
        cam.height = 3024
        cam.focal_length_x = 3456.0
        cam.focal_length_y = 3456.0
        cam.principal_point_x = 2016.0
        cam.principal_point_y = 1512.0
        cameras[i] = cam
    recon.cameras = cameras

    # Images
    images = {}
    names = photo_names or [f"IMG_{i:04d}.jpg" for i in range(1, num_images + 1)]
    for i in range(1, num_images + 1):
        img = MagicMock()
        img.name = names[i - 1] if i <= len(names) else f"IMG_{i:04d}.jpg"
        img.camera_id = 1
        img.has_pose = True

        cfw = MagicMock()
        cfw.matrix.return_value = np.array(
            [[1, 0, 0, float(i)], [0, 1, 0, 0], [0, 0, 1, 0]]
        )
        img.cam_from_world.return_value = cfw
        img.projection_center.return_value = np.array([float(i), 0.0, 1.5])
        img.viewing_direction.return_value = np.array([0.0, 1.0, 0.0])
        images[i] = img
    recon.images = images

    recon.num_points3D.return_value = num_points
    recon.num_reg_images.return_value = num_images

    return recon


class TestExportReconstructionMetadata:
    """Tests for camera/image metadata export."""

    def test_exports_camera_intrinsics(self, tmp_path: Path) -> None:
        recon = _make_mock_reconstruction(num_cameras=1, num_images=2)
        out = tmp_path / "meta.json"
        meta = export_reconstruction_metadata(recon, out)

        assert "1" in meta["cameras"]
        cam = meta["cameras"]["1"]
        assert cam["width"] == 4032
        assert cam["height"] == 3024
        assert cam["focal_length_x"] == 3456.0
        assert cam["model"] == "PINHOLE"

    def test_exports_image_poses(self, tmp_path: Path) -> None:
        recon = _make_mock_reconstruction(num_images=3)
        out = tmp_path / "meta.json"
        meta = export_reconstruction_metadata(recon, out)

        assert len(meta["images"]) == 3
        img = meta["images"]["1"]
        assert img["name"] == "IMG_0001.jpg"
        assert img["camera_id"] == 1
        assert len(img["cam_from_world"]) == 3  # 3x4 matrix
        assert len(img["cam_from_world"][0]) == 4

    def test_coordinate_transform_applied(self, tmp_path: Path) -> None:
        recon = _make_mock_reconstruction(num_images=1)
        # projection_center returns [1.0, 0.0, 1.5] in COLMAP
        out = tmp_path / "meta.json"
        meta = export_reconstruction_metadata(recon, out)

        center = meta["images"]["1"]["projection_center"]
        # Y and Z should be negated
        assert center[0] == 1.0
        assert center[1] == 0.0  # -0.0 == 0.0
        assert center[2] == -1.5

    def test_writes_valid_json_file(self, tmp_path: Path) -> None:
        import json as json_mod

        recon = _make_mock_reconstruction()
        out = tmp_path / "meta.json"
        export_reconstruction_metadata(recon, out)

        assert out.exists()
        data = json_mod.loads(out.read_text(encoding="utf-8"))
        assert "cameras" in data
        assert "images" in data
        assert "num_points3D" in data

    def test_statistics_correct(self, tmp_path: Path) -> None:
        recon = _make_mock_reconstruction(num_images=5, num_points=999)
        out = tmp_path / "meta.json"
        meta = export_reconstruction_metadata(recon, out)

        assert meta["num_points3D"] == 999
        assert meta["num_registered_images"] == 5

    def test_registered_image_mapping(self, tmp_path: Path) -> None:
        names = ["photo_A.jpg", "photo_B.jpg", "photo_C.jpg"]
        recon = _make_mock_reconstruction(num_images=3, photo_names=names)
        out = tmp_path / "meta.json"
        meta = export_reconstruction_metadata(recon, out, photo_names=names)

        assert meta["registered_images"] == {
            "photo_A.jpg": "1",
            "photo_B.jpg": "2",
            "photo_C.jpg": "3",
        }
        assert meta["unregistered_images"] == []

    def test_unregistered_images_tracked(self, tmp_path: Path) -> None:
        registered = ["photo_A.jpg", "photo_C.jpg"]
        all_photos = ["photo_A.jpg", "photo_B.jpg", "photo_C.jpg", "photo_D.jpg"]
        recon = _make_mock_reconstruction(num_images=2, photo_names=registered)
        out = tmp_path / "meta.json"
        meta = export_reconstruction_metadata(recon, out, photo_names=all_photos)

        assert "photo_B.jpg" in meta["unregistered_images"]
        assert "photo_D.jpg" in meta["unregistered_images"]
        assert len(meta["unregistered_images"]) == 2

    def test_skips_images_without_pose(self, tmp_path: Path) -> None:
        recon = _make_mock_reconstruction(num_images=2)
        # Make image 2 have no pose
        recon.images[2].has_pose = False
        out = tmp_path / "meta.json"
        meta = export_reconstruction_metadata(recon, out)

        assert len(meta["images"]) == 1
        assert "1" in meta["images"]

    def test_no_photo_names_gives_empty_unregistered(self, tmp_path: Path) -> None:
        recon = _make_mock_reconstruction(num_images=2)
        out = tmp_path / "meta.json"
        meta = export_reconstruction_metadata(recon, out, photo_names=None)

        assert meta["unregistered_images"] == []


class TestDepsCheck:
    """Tests for dependency checking."""

    def test_check_returns_dict(self) -> None:
        deps = check_reconstruction_deps()
        assert isinstance(deps, dict)
        assert "pycolmap" in deps
        assert "mujoco" in deps
        assert "trimesh" in deps
        assert "numpy" in deps

    def test_pycolmap_available(self) -> None:
        deps = check_reconstruction_deps()
        assert deps["pycolmap"] is True
