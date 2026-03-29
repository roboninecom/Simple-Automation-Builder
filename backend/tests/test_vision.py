"""Tests for Claude Vision scene analysis."""

from pathlib import Path

import numpy as np

from backend.app.models.space import (
    Dimensions,
    ExistingEquipment,
    SceneAnalysis,
    Zone,
)
from backend.app.services.spatial_anchors import ImageAnchors, SpatialAnchor
from backend.app.services.vision import (
    _extract_json,
    _format_analysis_request,
    _format_anchor_section,
    build_space_model,
    validate_analysis,
    validate_positions_against_cloud,
)


class TestExtractJson:
    """Tests for JSON extraction from Claude responses."""

    def test_plain_json(self) -> None:
        text = '{"zones": [], "existing_equipment": [], "doors": [], "windows": []}'
        result = _extract_json(text)
        assert result.startswith("{")

    def test_json_in_code_block(self) -> None:
        text = '```json\n{"zones": []}\n```'
        result = _extract_json(text)
        assert result == '{"zones": []}'

    def test_json_in_generic_code_block(self) -> None:
        text = '```\n{"zones": []}\n```'
        result = _extract_json(text)
        assert result == '{"zones": []}'


class TestBuildSpaceModel:
    """Tests for SpaceModel composition."""

    def test_merge_reconstruction_and_analysis(
        self,
        sample_reconstruction,
    ) -> None:
        analysis = SceneAnalysis(
            zones=[
                Zone(
                    name="main_area",
                    polygon=[(0, 0), (6, 0), (6, 5), (0, 5)],
                    area_m2=30.0,
                )
            ],
            existing_equipment=[
                ExistingEquipment(
                    name="printer_1",
                    category="printer",
                    position=(1.0, 2.0, 0.85),
                    confidence=0.9,
                )
            ],
        )
        space = build_space_model(sample_reconstruction, analysis)

        assert space.dimensions.width_m == 6.0
        assert len(space.zones) == 1
        assert space.zones[0].name == "main_area"
        assert len(space.existing_equipment) == 1
        assert space.reconstruction == sample_reconstruction


class TestValidateAnalysis:
    """Tests for post-validation of scene analysis."""

    def _dims(self) -> Dimensions:
        return Dimensions(width_m=5.0, length_m=4.0, ceiling_m=2.8, area_m2=20.0)

    def test_clamps_position_to_room_bounds(self) -> None:
        analysis = SceneAnalysis(
            existing_equipment=[
                ExistingEquipment(
                    name="desk",
                    category="table",
                    position=(10.0, -1.0, 0.0),
                    confidence=0.9,
                    dimensions=(1.2, 0.6, 0.75),
                ),
            ],
        )
        result = validate_analysis(analysis, self._dims())
        eq = result.existing_equipment[0]
        assert eq.position[0] == 5.0
        assert eq.position[1] == 0.0

    def test_clamps_dimensions_to_min(self) -> None:
        analysis = SceneAnalysis(
            existing_equipment=[
                ExistingEquipment(
                    name="tiny",
                    category="misc",
                    position=(1.0, 1.0, 0.0),
                    confidence=0.8,
                    dimensions=(0.01, 0.02, 0.03),
                ),
            ],
        )
        result = validate_analysis(analysis, self._dims())
        eq = result.existing_equipment[0]
        assert eq.dimensions[0] == 0.05
        assert eq.dimensions[1] == 0.05
        assert eq.dimensions[2] == 0.05

    def test_floor_mounted_z_set_to_half_height(self) -> None:
        """Floor-mounted items get Z = height/2 (body center above floor)."""
        analysis = SceneAnalysis(
            existing_equipment=[
                ExistingEquipment(
                    name="shelf",
                    category="shelf",
                    position=(1.0, 1.0, 0.5),
                    confidence=0.8,
                    mounting="floor",
                    dimensions=(0.8, 0.3, 1.8),
                ),
            ],
        )
        result = validate_analysis(analysis, self._dims())
        # Z = height / 2 = 1.8 / 2 = 0.9
        assert result.existing_equipment[0].position[2] == 0.9

    def test_wall_mounted_keeps_z(self) -> None:
        analysis = SceneAnalysis(
            existing_equipment=[
                ExistingEquipment(
                    name="ac_unit",
                    category="appliance",
                    position=(2.0, 0.0, 2.2),
                    confidence=0.85,
                    mounting="wall",
                ),
            ],
        )
        result = validate_analysis(analysis, self._dims())
        assert result.existing_equipment[0].position[2] == 2.2

    def test_backward_compatible_old_format(self) -> None:
        """Old response without new fields still parses with defaults."""
        analysis = SceneAnalysis(
            existing_equipment=[
                ExistingEquipment(
                    name="item",
                    category="misc",
                    position=(1.0, 1.0, 0.0),
                    confidence=0.7,
                ),
            ],
        )
        result = validate_analysis(analysis, self._dims())
        eq = result.existing_equipment[0]
        assert eq.dimensions == (0.4, 0.4, 0.8)
        assert eq.orientation_deg == 0.0
        assert eq.mounting == "floor"


class TestFormatAnalysisRequest:
    """Tests for analysis request formatting with/without anchors."""

    def _dims(self) -> Dimensions:
        return Dimensions(width_m=5.0, length_m=4.0, ceiling_m=2.8, area_m2=20.0)

    def test_without_anchors_backward_compat(self) -> None:
        text = _format_analysis_request(self._dims())
        assert "Width (X-axis): 5.00m" in text
        assert "Spatial Reference Points" not in text

    def test_with_anchors_includes_section(self) -> None:
        anchors = [
            ImageAnchors(
                image_name="photo1.jpg",
                image_id=1,
                camera_position=(2.5, 2.0, 1.5),
                viewing_direction=(0.0, 1.0, 0.0),
                anchors=[
                    SpatialAnchor(pixel=(100, 200), world=(1.0, 0.5, 0.0), label="floor_point"),
                    SpatialAnchor(pixel=(500, 300), world=(3.0, 2.0, 0.0), label="grid_sample"),
                ],
            )
        ]
        text = _format_analysis_request(self._dims(), image_anchors=anchors)
        assert "Spatial Reference Points" in text
        assert "photo1.jpg" in text
        assert "(100, 200)" in text
        assert "(1.00, 0.50, 0.00)" in text
        assert "floor_point" in text

    def test_with_none_anchors_same_as_without(self) -> None:
        text_none = _format_analysis_request(self._dims(), image_anchors=None)
        text_no_arg = _format_analysis_request(self._dims())
        assert text_none == text_no_arg

    def test_with_empty_anchors_same_as_without(self) -> None:
        text_empty = _format_analysis_request(self._dims(), image_anchors=[])
        text_no_arg = _format_analysis_request(self._dims())
        assert text_empty == text_no_arg


class TestFormatAnchorSection:
    """Tests for anchor section formatting."""

    def test_contains_markdown_table(self) -> None:
        anchors = [
            ImageAnchors(
                image_name="IMG_001.jpg",
                image_id=1,
                camera_position=(1.0, 2.0, 1.5),
                viewing_direction=(0.0, 0.0, -1.0),
                anchors=[
                    SpatialAnchor(pixel=(320, 480), world=(0.0, 0.0, 0.0), label="room_corner_SW_floor"),
                ],
            )
        ]
        text = _format_anchor_section(anchors)
        assert "| Pixel (x,y) |" in text
        assert "| (320, 480) |" in text
        assert "room_corner_SW_floor" in text

    def test_multiple_images(self) -> None:
        anchors = [
            ImageAnchors(
                image_name=f"IMG_{i}.jpg",
                image_id=i,
                camera_position=(0, 0, 0),
                viewing_direction=(0, 1, 0),
                anchors=[SpatialAnchor(pixel=(0, 0), world=(0, 0, 0), label="test")],
            )
            for i in range(3)
        ]
        text = _format_anchor_section(anchors)
        assert "IMG_0.jpg" in text
        assert "IMG_1.jpg" in text
        assert "IMG_2.jpg" in text


def _make_ply_with_points(path: Path, vertices: np.ndarray) -> None:
    """Write a minimal PLY point cloud for testing.

    Args:
        path: Output PLY file path.
        vertices: Nx3 numpy array of point positions.
    """
    import trimesh

    cloud = trimesh.PointCloud(vertices=vertices)
    cloud.export(str(path))


class TestValidatePositionsAgainstCloud:
    """Tests for point cloud position validation."""

    def _dims(self) -> Dimensions:
        return Dimensions(width_m=6.0, length_m=4.0, ceiling_m=2.7, area_m2=24.0)

    def test_confidence_stays_when_points_nearby(self, tmp_path: Path) -> None:
        ply = tmp_path / "cloud.ply"
        # Points clustered around (2.0, 1.5, 0.0)
        verts = np.array([
            [1.9, 1.4, 0.0], [2.0, 1.5, 0.1], [2.1, 1.6, 0.0],
            [2.0, 1.5, 0.0], [1.8, 1.5, 0.0],
        ])
        _make_ply_with_points(ply, verts)

        analysis = SceneAnalysis(
            existing_equipment=[
                ExistingEquipment(
                    name="desk", category="table",
                    position=(2.0, 1.5, 0.375), confidence=0.9,
                    mounting="floor", dimensions=(1.2, 0.6, 0.75),
                ),
            ],
        )
        result = validate_positions_against_cloud(analysis, ply, self._dims())
        assert result.existing_equipment[0].confidence == 0.9

    def test_confidence_reduced_when_no_points(self, tmp_path: Path) -> None:
        ply = tmp_path / "cloud.ply"
        # Points far from (5.0, 3.5)
        verts = np.array([[0.0, 0.0, 0.0], [0.1, 0.1, 0.0], [0.2, 0.0, 0.0]])
        _make_ply_with_points(ply, verts)

        analysis = SceneAnalysis(
            existing_equipment=[
                ExistingEquipment(
                    name="desk", category="table",
                    position=(5.0, 3.5, 0.375), confidence=0.9,
                    mounting="floor", dimensions=(1.2, 0.6, 0.75),
                ),
            ],
        )
        result = validate_positions_against_cloud(analysis, ply, self._dims())
        assert result.existing_equipment[0].confidence < 0.9

    def test_wall_mounted_skipped(self, tmp_path: Path) -> None:
        ply = tmp_path / "cloud.ply"
        verts = np.array([[0.0, 0.0, 0.0], [0.1, 0.1, 0.0], [0.2, 0.0, 0.0]])
        _make_ply_with_points(ply, verts)

        analysis = SceneAnalysis(
            existing_equipment=[
                ExistingEquipment(
                    name="ac", category="appliance",
                    position=(5.0, 3.5, 2.2), confidence=0.85,
                    mounting="wall",
                ),
            ],
        )
        result = validate_positions_against_cloud(analysis, ply, self._dims())
        assert result.existing_equipment[0].confidence == 0.85

    def test_none_path_is_noop(self) -> None:
        analysis = SceneAnalysis(
            existing_equipment=[
                ExistingEquipment(
                    name="desk", category="table",
                    position=(2.0, 1.5, 0.375), confidence=0.9,
                    mounting="floor",
                ),
            ],
        )
        result = validate_positions_against_cloud(analysis, None, self._dims())
        assert result.existing_equipment[0].confidence == 0.9

    def test_empty_cloud_is_noop(self, tmp_path: Path) -> None:
        ply = tmp_path / "cloud.ply"
        ply.touch()
        analysis = SceneAnalysis(
            existing_equipment=[
                ExistingEquipment(
                    name="desk", category="table",
                    position=(2.0, 1.5, 0.375), confidence=0.9,
                    mounting="floor",
                ),
            ],
        )
        result = validate_positions_against_cloud(analysis, ply, self._dims())
        assert result.existing_equipment[0].confidence == 0.9
