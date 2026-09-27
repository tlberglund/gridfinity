"""Tests for the pure planning logic. Run: .venv/bin/python test_gridfinity.py"""
import gridfinity as g


def test_split_even():
   assert g.split_even(12, 2) == [6, 6]
   assert g.split_even(9, 2) == [5, 4]
   assert g.split_even(20, 3) == [7, 7, 6]


def test_axis_546():
   units, border, splits = g.plan_axis(546)
   assert units == 12                    # 13 would leave only 0.5 mm
   assert abs(border - 20.75) < 1e-9
   assert splits == [6, 6]


def test_axis_419():
   units, border, splits = g.plan_axis(419)
   assert units == 9
   assert abs(border - 20.25) < 1e-9
   assert splits == [5, 4]


def test_axis_single_plate():
   units, border, splits = g.plan_axis(200)
   assert units == 4 and splits == [4]
   assert abs(g.outer_size(4) + 2 * border - 199) < 1e-9


def test_axis_border_pushes_edge_plate_over_bed():
   # 7 units (293.5) fits the bed alone but not with an ~8 mm border on top
   units, border, splits = g.plan_axis(310)
   assert units == 7
   assert len(splits) == 2
   assert g.outer_size(max(splits)) + border <= g.BED


def test_axis_three_plates():
   units, border, splits = g.plan_axis(700)
   assert units == 16 and splits == [6, 5, 5]


def test_axis_too_small():
   try:
      g.plan_axis(30)
   except ValueError:
      return
   assert False, "expected ValueError"


def test_plan_drawer_borders_and_footprints():
   plan = g.plan_drawer("t", 546, 419)
   assert plan["units"] == (12, 9)
   assert [abs(a - b) < 1e-9 for a, b in zip(plan["assembled"], (545, 418))] == [True, True]
   assert len(plan["plates"]) == 4
   fl = next(p for p in plan["plates"] if p["row"] == 1 and p["col"] == 1)
   assert fl["borders"] == {"left": 20.75, "right": 0, "front": 20.25, "back": 0}
   assert [round(v, 2) for v in fl["footprint"]] == [272.25, 229.75]
   br = next(p for p in plan["plates"] if p["row"] == 2 and p["col"] == 2)
   assert br["borders"] == {"left": 0, "right": 20.75, "front": 0, "back": 20.25}
   assert br["units"] == (6, 4)
   for p in plan["plates"]:
      assert max(p["footprint"]) <= g.BED


def test_markdown_mentions_every_plate():
   plan = g.plan_drawer("kitchen", 546, 419, notes="left of stove")
   md = g.render_markdown(plan)
   assert md.startswith("# kitchen")
   assert "left of stove" in md
   for p in plan["plates"]:
      assert p["file"] in md


if __name__ == "__main__":
   tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
   for t in tests:
      t()
      print("ok  ", t.__name__)
   print(f"{len(tests)} passed")
