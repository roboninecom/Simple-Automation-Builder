"""Tests for scene layout validation and adjustment."""

import xml.etree.ElementTree as ET

from backend.app.models.space import SpaceModel
from backend.app.services.scene_validation import (
    adjust_scene,
    validate_scene_layout,
)


def _make_scene_xml(bodies_xml: str) -> str:
    return f"""<mujoco>
  <worldbody>
    {bodies_xml}
  </worldbody>
</mujoco>"""


def _make_space(
    width: float = 5.0,
    length: float = 4.0,
    doors: list | None = None,
) -> SpaceModel:
    from pathlib import Path

    from backend.app.models.space import Dimensions, SceneReconstruction

    tmp = Path("/tmp/test")
    return SpaceModel(
        dimensions=Dimensions(
            width_m=width, length_m=length, ceiling_m=2.8,
            area_m2=width * length,
        ),
        doors=doors or [],
        reconstruction=SceneReconstruction(
            mesh_path=tmp / "mesh.obj",
            mjcf_path=tmp / "scene.xml",
            pointcloud_path=tmp / "pc.ply",
            dimensions=Dimensions(
                width_m=width, length_m=length, ceiling_m=2.8,
                area_m2=width * length,
            ),
        ),
    )


class TestValidateSceneLayout:
    """Tests for scene validation heuristics."""

    def test_equipment_outside_bounds(self, tmp_path) -> None:
        scene = tmp_path / "scene.xml"
        scene.write_text(_make_scene_xml(
            '<body name="desk_1" pos="10 2 0.4">'
            '  <geom name="desk_1_geom" type="box" size="0.6 0.3 0.4"/>'
            '</body>'
        ))
        warnings = validate_scene_layout(_make_space(), scene)
        names = [w.body_name for w in warnings if "bounds" in w.message.lower()]
        assert "desk_1" in names

    def test_equipment_inside_bounds_no_warning(self, tmp_path) -> None:
        scene = tmp_path / "scene.xml"
        scene.write_text(_make_scene_xml(
            '<body name="desk_1" pos="2.5 2.0 0.4">'
            '  <geom name="desk_1_geom" type="box" size="0.6 0.3 0.4"/>'
            '</body>'
        ))
        warnings = validate_scene_layout(_make_space(), scene)
        bound_warnings = [w for w in warnings if "bounds" in w.message.lower()]
        assert len(bound_warnings) == 0

    def test_overlapping_equipment(self, tmp_path) -> None:
        scene = tmp_path / "scene.xml"
        scene.write_text(_make_scene_xml(
            '<body name="a" pos="2.0 2.0 0.4">'
            '  <geom name="a_geom" type="box" size="0.5 0.5 0.5"/>'
            '</body>'
            '<body name="b" pos="2.2 2.0 0.4">'
            '  <geom name="b_geom" type="box" size="0.5 0.5 0.5"/>'
            '</body>'
        ))
        warnings = validate_scene_layout(_make_space(), scene)
        overlap_warnings = [w for w in warnings if "overlap" in w.message.lower()]
        assert len(overlap_warnings) >= 1

    def test_very_large_equipment(self, tmp_path) -> None:
        scene = tmp_path / "scene.xml"
        scene.write_text(_make_scene_xml(
            '<body name="huge" pos="2.5 2.0 2.5">'
            '  <geom name="huge_geom" type="box" size="0.5 0.5 2.5"/>'
            '</body>'
        ))
        warnings = validate_scene_layout(_make_space(), scene)
        size_warnings = [w for w in warnings if "large" in w.message.lower()]
        assert len(size_warnings) >= 1

    def test_floating_equipment(self, tmp_path) -> None:
        scene = tmp_path / "scene.xml"
        scene.write_text(_make_scene_xml(
            '<body name="floating" pos="2.0 2.0 1.5">'
            '  <geom name="floating_geom" type="box" size="0.2 0.2 0.1"/>'
            '</body>'
        ))
        warnings = validate_scene_layout(_make_space(), scene)
        float_warnings = [w for w in warnings if "floating" in w.message.lower()]
        assert len(float_warnings) >= 1

    def test_skips_room_geometry(self, tmp_path) -> None:
        scene = tmp_path / "scene.xml"
        scene.write_text(_make_scene_xml(
            '<body name="room_floor" pos="2.5 2.0 0">'
            '  <geom name="floor" type="box" size="2.5 2.0 0.02"/>'
            '</body>'
            '<body name="wall_north" pos="2.5 4.0 1.4">'
            '  <geom name="wall_north_solid" type="box" size="2.5 0.05 1.4"/>'
            '</body>'
        ))
        warnings = validate_scene_layout(_make_space(), scene)
        assert len(warnings) == 0


class TestAdjustScene:
    """Tests for scene adjustment."""

    def test_adjust_position(self, tmp_path) -> None:
        scene = tmp_path / "scene.xml"
        scene.write_text(_make_scene_xml(
            '<body name="desk" pos="1.0 1.0 0.4">'
            '  <geom name="desk_geom" type="box" size="0.6 0.3 0.4"/>'
            '</body>'
        ))
        output = tmp_path / "adjusted.xml"
        adjust_scene(scene, [{"body_name": "desk", "position": [3.0, 2.0, 0.4]}], output)

        tree = ET.parse(str(output))
        body = tree.find(".//body[@name='desk']")
        assert body is not None
        assert "3.000" in body.get("pos", "")

    def test_remove_body(self, tmp_path) -> None:
        scene = tmp_path / "scene.xml"
        scene.write_text(_make_scene_xml(
            '<body name="keep" pos="1 1 0.4">'
            '  <geom name="keep_g" type="box" size="0.2 0.2 0.2"/>'
            '</body>'
            '<body name="remove_me" pos="2 2 0.4">'
            '  <geom name="rm_g" type="box" size="0.2 0.2 0.2"/>'
            '</body>'
        ))
        output = tmp_path / "adjusted.xml"
        adjust_scene(scene, [{"body_name": "remove_me", "remove": True}], output)

        tree = ET.parse(str(output))
        assert tree.find(".//body[@name='remove_me']") is None
        assert tree.find(".//body[@name='keep']") is not None

    def test_adjust_dimensions(self, tmp_path) -> None:
        scene = tmp_path / "scene.xml"
        scene.write_text(_make_scene_xml(
            '<body name="desk" pos="1 1 0.4">'
            '  <geom name="desk_geom" type="box" size="0.6 0.3 0.4"/>'
            '</body>'
        ))
        output = tmp_path / "adjusted.xml"
        adjust_scene(
            scene,
            [{"body_name": "desk", "dimensions": [2.0, 1.0, 0.8]}],
            output,
        )

        tree = ET.parse(str(output))
        geom = tree.find(".//body[@name='desk']/geom")
        assert geom is not None
        assert "1.000" in geom.get("size", "")  # half of 2.0
