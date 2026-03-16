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
            "room_floor",
            "room_ceiling",
            "wall_north",
            "wall_south",
            "wall_east",
            "wall_west",
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


class TestWallDualGeoms:
    """Tests for wall visual + collision geom pairs."""

    def test_solid_wall_has_two_geoms(self) -> None:
        bodies = generate_room_bodies(_dims(), [], [])
        north = next(b for b in bodies if b.get("name") == "wall_north")
        geoms = north.findall("geom")
        assert len(geoms) == 2  # vis + col

    def test_vis_geom_is_transparent_no_collision(self) -> None:
        bodies = generate_room_bodies(_dims(), [], [])
        north = next(b for b in bodies if b.get("name") == "wall_north")
        vis = north.find("geom[@name='wall_north_solid_vis']")
        assert vis is not None
        assert vis.get("contype") == "0"
        assert vis.get("conaffinity") == "0"
        assert "0.2" in vis.get("rgba", "")

    def test_col_geom_is_invisible_with_collision(self) -> None:
        bodies = generate_room_bodies(_dims(), [], [])
        north = next(b for b in bodies if b.get("name") == "wall_north")
        col = north.find("geom[@name='wall_north_solid_col']")
        assert col is not None
        assert col.get("contype") == "1"
        assert col.get("conaffinity") == "1"
        assert col.get("rgba") == "0 0 0 0"
        assert col.get("group") == "3"

    def test_vis_and_col_same_size_and_pos(self) -> None:
        bodies = generate_room_bodies(_dims(), [], [])
        north = next(b for b in bodies if b.get("name") == "wall_north")
        vis = north.find("geom[@name='wall_north_solid_vis']")
        col = north.find("geom[@name='wall_north_solid_col']")
        assert vis.get("size") == col.get("size")
        assert vis.get("pos") == col.get("pos")


class TestWallWithDoor:
    """Tests for walls with door cutouts."""

    def test_door_splits_wall_into_three_segment_pairs(self) -> None:
        door = Door(position=(2.5, 0.0), width_m=0.9, height_m=2.1, wall="south")
        bodies = generate_room_bodies(_dims(), [door], [])
        south = next(b for b in bodies if b.get("name") == "wall_south")
        geoms = south.findall("geom")
        # 3 segments × 2 geoms each = 6
        assert len(geoms) == 6

    def test_door_at_edge_no_left_segment(self) -> None:
        door = Door(position=(0.45, 0.0), width_m=0.9, height_m=2.1, wall="south")
        bodies = generate_room_bodies(_dims(), [door], [])
        south = next(b for b in bodies if b.get("name") == "wall_south")
        geoms = south.findall("geom")
        # 2 segments × 2 geoms each = 4
        assert len(geoms) == 4


class TestWallWithWindow:
    """Tests for walls with window cutouts."""

    def test_window_splits_wall_into_four_segment_pairs(self) -> None:
        window = Window(
            position=(0.0, 2.0),
            width_m=1.2,
            height_m=1.2,
            sill_height_m=0.9,
            wall="west",
        )
        bodies = generate_room_bodies(_dims(), [], [window])
        west = next(b for b in bodies if b.get("name") == "wall_west")
        geoms = west.findall("geom")
        # 4 segments × 2 geoms each = 8
        assert len(geoms) == 8

    def test_all_col_geoms_have_collision(self) -> None:
        window = Window(
            position=(0.0, 2.0),
            width_m=1.2,
            height_m=1.2,
            sill_height_m=0.9,
            wall="west",
        )
        bodies = generate_room_bodies(_dims(), [], [window])
        west = next(b for b in bodies if b.get("name") == "wall_west")
        col_geoms = [g for g in west.findall("geom") if g.get("name", "").endswith("_col")]
        assert len(col_geoms) == 4
        for geom in col_geoms:
            assert geom.get("contype") == "1"

    def test_all_vis_geoms_no_collision(self) -> None:
        window = Window(
            position=(0.0, 2.0),
            width_m=1.2,
            height_m=1.2,
            sill_height_m=0.9,
            wall="west",
        )
        bodies = generate_room_bodies(_dims(), [], [window])
        west = next(b for b in bodies if b.get("name") == "wall_west")
        vis_geoms = [g for g in west.findall("geom") if g.get("name", "").endswith("_vis")]
        assert len(vis_geoms) == 4
        for geom in vis_geoms:
            assert geom.get("contype") == "0"


class TestWallWithMultipleOpenings:
    """Tests for walls with both doors and windows."""

    def test_door_and_window_on_same_wall(self) -> None:
        door = Door(position=(1.5, 4.0), width_m=0.9, height_m=2.1, wall="north")
        window = Window(
            position=(3.5, 4.0),
            width_m=1.0,
            height_m=1.2,
            sill_height_m=0.9,
            wall="north",
        )
        bodies = generate_room_bodies(_dims(), [door], [window])
        north = next(b for b in bodies if b.get("name") == "wall_north")
        geoms = north.findall("geom")
        # ≥5 segments × 2 geoms each = ≥10
        assert len(geoms) >= 10
