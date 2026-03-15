"""Tests for MJCF scene export to Three.js JSON."""

from pathlib import Path

from backend.app.models.space import (
    Dimensions,
    Door,
    ExistingEquipment,
    SceneReconstruction,
    SpaceModel,
    Window,
)
from backend.app.services.scene import generate_preview_scene
from backend.app.services.scene_export import export_scene_data


def _make_space(tmp_path: Path) -> SpaceModel:
    mesh = tmp_path / "mesh.obj"
    mjcf = tmp_path / "scene.xml"
    pc = tmp_path / "pc.ply"
    mesh.touch()
    mjcf.touch()
    pc.touch()
    dims = Dimensions(width_m=5.0, length_m=4.0, ceiling_m=2.8, area_m2=20.0)
    return SpaceModel(
        dimensions=dims,
        existing_equipment=[
            ExistingEquipment(
                name="desk_1", category="desk",
                position=(2.0, 1.5, 0.0), confidence=0.9,
                dimensions=(1.2, 0.6, 0.75),
                rgba=(0.25, 0.2, 0.15, 1.0),
            ),
            ExistingEquipment(
                name="wardrobe_1", category="wardrobe",
                position=(0.5, 3.0, 0.0), confidence=0.85,
                dimensions=(1.0, 0.5, 2.0),
            ),
        ],
        doors=[Door(position=(3.0, 4.0), width_m=0.9, wall="north")],
        windows=[Window(position=(0.0, 2.0), width_m=1.2, wall="west")],
        reconstruction=SceneReconstruction(
            mesh_path=mesh, mjcf_path=mjcf,
            pointcloud_path=pc, dimensions=dims,
        ),
    )


class TestGeneratePreviewScene:
    """Tests for preview scene generation."""

    def test_creates_valid_xml(self, tmp_path) -> None:
        space = _make_space(tmp_path)
        output = tmp_path / "scenes" / "preview.xml"
        result = generate_preview_scene(space, output)
        assert result.exists()
        assert result.stat().st_size > 100

    def test_contains_existing_equipment(self, tmp_path) -> None:
        space = _make_space(tmp_path)
        output = tmp_path / "scenes" / "preview.xml"
        generate_preview_scene(space, output)
        content = output.read_text()
        assert "desk_1" in content
        assert "wardrobe_1" in content

    def test_contains_walls(self, tmp_path) -> None:
        space = _make_space(tmp_path)
        output = tmp_path / "scenes" / "preview.xml"
        generate_preview_scene(space, output)
        content = output.read_text()
        assert "wall_north" in content
        assert "wall_south" in content

    def test_no_recommendation_equipment(self, tmp_path) -> None:
        space = _make_space(tmp_path)
        output = tmp_path / "scenes" / "preview.xml"
        generate_preview_scene(space, output)
        content = output.read_text()
        # No robot or conveyor bodies
        assert "franka" not in content
        assert "conveyor" not in content


class TestExportSceneData:
    """Tests for scene data export to JSON."""

    def test_export_returns_room_dimensions(self, tmp_path) -> None:
        space = _make_space(tmp_path)
        output = tmp_path / "scenes" / "preview.xml"
        generate_preview_scene(space, output)
        data = export_scene_data(output, space)
        assert data["room"]["width"] == 5.0
        assert data["room"]["length"] == 4.0

    def test_export_returns_bodies(self, tmp_path) -> None:
        space = _make_space(tmp_path)
        output = tmp_path / "scenes" / "preview.xml"
        generate_preview_scene(space, output)
        data = export_scene_data(output, space)
        names = {b["name"] for b in data["bodies"]}
        assert "desk_1" in names
        assert "wardrobe_1" in names

    def test_export_returns_walls(self, tmp_path) -> None:
        space = _make_space(tmp_path)
        output = tmp_path / "scenes" / "preview.xml"
        generate_preview_scene(space, output)
        data = export_scene_data(output, space)
        assert len(data["walls"]) > 0
        # All walls should be vis geoms
        for wall in data["walls"]:
            assert wall["name"].endswith("_vis")

    def test_export_returns_floor(self, tmp_path) -> None:
        space = _make_space(tmp_path)
        output = tmp_path / "scenes" / "preview.xml"
        generate_preview_scene(space, output)
        data = export_scene_data(output, space)
        assert data["floor"]["name"] == "floor"

    def test_export_returns_doors_and_windows(self, tmp_path) -> None:
        space = _make_space(tmp_path)
        output = tmp_path / "scenes" / "preview.xml"
        generate_preview_scene(space, output)
        data = export_scene_data(output, space)
        assert len(data["doors"]) == 1
        assert data["doors"][0]["wall"] == "north"
        assert len(data["windows"]) == 1
        assert data["windows"][0]["wall"] == "west"

    def test_body_has_geoms_with_size_and_color(self, tmp_path) -> None:
        space = _make_space(tmp_path)
        output = tmp_path / "scenes" / "preview.xml"
        generate_preview_scene(space, output)
        data = export_scene_data(output, space)
        desk = next(b for b in data["bodies"] if b["name"] == "desk_1")
        assert len(desk["geoms"]) > 0
        geom = desk["geoms"][0]
        assert len(geom["size"]) >= 2
        assert len(geom["rgba"]) == 4
