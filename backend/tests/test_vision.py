"""Tests for Claude Vision scene analysis."""

from backend.app.models.space import (
    Dimensions,
    ExistingEquipment,
    SceneAnalysis,
    Zone,
)
from backend.app.services.vision import (
    _extract_json,
    build_space_model,
    validate_analysis,
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

    def test_floor_mounted_z_forced_to_zero(self) -> None:
        analysis = SceneAnalysis(
            existing_equipment=[
                ExistingEquipment(
                    name="shelf",
                    category="shelf",
                    position=(1.0, 1.0, 0.5),
                    confidence=0.8,
                    mounting="floor",
                ),
            ],
        )
        result = validate_analysis(analysis, self._dims())
        assert result.existing_equipment[0].position[2] == 0.0

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
