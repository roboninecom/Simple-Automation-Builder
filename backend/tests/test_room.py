"""Tests for parametric room geometry generation."""

from backend.app.models.space import Dimensions, Door, Window
from backend.app.services.room import generate_room_bodies


def _dims() -> Dimensions:
    return Dimensions(width_m=5.0, length_m=4.0, ceiling_m=2.8, area_m2=20.0)


class TestGenerateRoomBodies:
    """Tests for room body generation."""

    def test_no_openings_produces_six_bodies(self) -> None:
        bodies = generate_room_bodies(_dims(), [], [])
        assert len(bodies) == 6  # floor + ceiling + 4 walls

    def test_body_names(self) -> None:
        bodies = generate_room_bodies(_dims(), [], [])
        names = {b.get("name") for b in bodies}
        assert names == {
            "room_floor", "room_ceiling",
            "wall_north", "wall_south", "wall_east", "wall_west",
        }

    def test_floor_has_collision(self) -> None:
        bodies = generate_room_bodies(_dims(), [], [])
        floor = next(b for b in bodies if b.get("name") == "room_floor")
        geom = floor.find("geom")
        assert geom is not None
        assert geom.get("contype") == "1"
        assert geom.get("conaffinity") == "1"

    def test_ceiling_no_collision(self) -> None:
        bodies = generate_room_bodies(_dims(), [], [])
        ceiling = next(b for b in bodies if b.get("name") == "room_ceiling")
        geom = ceiling.find("geom")
        assert geom is not None
        assert geom.get("contype") == "0"

    def test_solid_wall_has_one_geom(self) -> None:
        bodies = generate_room_bodies(_dims(), [], [])
        north = next(b for b in bodies if b.get("name") == "wall_north")
        geoms = north.findall("geom")
        assert len(geoms) == 1
        assert geoms[0].get("name") == "wall_north_solid"


class TestWallWithDoor:
    """Tests for walls with door cutouts."""

    def test_door_splits_wall_into_three_segments(self) -> None:
        door = Door(position=(2.5, 0.0), width_m=0.9, height_m=2.1, wall="south")
        bodies = generate_room_bodies(_dims(), [door], [])
        south = next(b for b in bodies if b.get("name") == "wall_south")
        geoms = south.findall("geom")
        # left, above door, right = 3 segments
        assert len(geoms) == 3

    def test_door_at_edge_no_left_segment(self) -> None:
        door = Door(position=(0.45, 0.0), width_m=0.9, height_m=2.1, wall="south")
        bodies = generate_room_bodies(_dims(), [door], [])
        south = next(b for b in bodies if b.get("name") == "wall_south")
        geoms = south.findall("geom")
        # above + right = 2 segments
        assert len(geoms) == 2


class TestWallWithWindow:
    """Tests for walls with window cutouts."""

    def test_window_splits_wall_into_four_segments(self) -> None:
        window = Window(
            position=(0.0, 2.0), width_m=1.2, height_m=1.2,
            sill_height_m=0.9, wall="west",
        )
        bodies = generate_room_bodies(_dims(), [], [window])
        west = next(b for b in bodies if b.get("name") == "wall_west")
        geoms = west.findall("geom")
        # left, above, below sill, right = 4 segments
        assert len(geoms) == 4

    def test_wall_geoms_have_collision(self) -> None:
        window = Window(
            position=(0.0, 2.0), width_m=1.2, height_m=1.2,
            sill_height_m=0.9, wall="west",
        )
        bodies = generate_room_bodies(_dims(), [], [window])
        west = next(b for b in bodies if b.get("name") == "wall_west")
        for geom in west.findall("geom"):
            assert geom.get("contype") == "1"


class TestWallWithMultipleOpenings:
    """Tests for walls with both doors and windows."""

    def test_door_and_window_on_same_wall(self) -> None:
        door = Door(position=(1.5, 4.0), width_m=0.9, height_m=2.1, wall="north")
        window = Window(
            position=(3.5, 4.0), width_m=1.0, height_m=1.2,
            sill_height_m=0.9, wall="north",
        )
        bodies = generate_room_bodies(_dims(), [door], [window])
        north = next(b for b in bodies if b.get("name") == "wall_north")
        geoms = north.findall("geom")
        # left, above_door, between, above_window, below_window, right
        assert len(geoms) >= 5
