"""Tests for the pure planning logic. Run: ../.venv/bin/python test_wrenches.py"""
import wrenches as w


def mk(size, length_cm, hw, mw, h, ht):
   return w.Wrench(size, length_cm * 10, hw, mw, h, ht)


SMALL = mk(7, 12.7, 7.1, 16, 8, 3.7)
MID = mk(8, 13.8, 8, 18, 8, 3.7)
BIG = mk(19, 24.7, 17, 40, 15.4, 6.9)


def test_pitch_keeps_heads_apart():
   # on edge the heads meet thickness to thickness: half of each plus the gap
   assert abs(w.pitch(SMALL, MID) - (4 + 4 + w.HEAD_GAP)) < 1e-9


def test_channel_is_snug_on_handle_thickness():
   assert 0 < w.channel_width(SMALL) - SMALL.handle_thickness <= 1.0


def test_slab_reaches_up_the_handle():
   # 19 mm: head is 40 wide, handle 17, so the handle's edge floats 11.5 up
   assert abs(w.handle_lift(BIG) - 11.5) < 1e-9
   assert w.slab_height(BIG) >= 11.5 + w.ENGAGE
   assert w.slab_height(BIG) < 11.5 + w.ENGAGE + w.STEP
   assert abs(w.slab_height(BIG) / w.STEP - round(w.slab_height(BIG) / w.STEP)) < 1e-9
   # and the head still stands proud of the channel walls
   assert w.standing_height(BIG) > w.slab_height(BIG)
   assert w.standing_height(SMALL) > w.slab_height(SMALL)


def test_features_sit_on_the_step_grid():
   for x in (SMALL, MID, BIG):
      for v in (w.slab_height(x), w.head_length(x)):
         assert abs(v / w.STEP - round(v / w.STEP)) < 1e-9
   assert w.head_length(BIG) >= w.HEAD_LEN_FACTOR * BIG.max_width


def test_outermost_head_pockets_reach_the_wall():
   plan = w.plan_tray([SMALL, MID, BIG], 1)
   assert [k["to_wall"] for k in plan["pockets"]] == ["left", None, "right"]


def test_units_for_inner_size():
   assert w.units_for(41.5 - 2 * w.WALL) == 1
   assert w.units_for(41.5 - 2 * w.WALL + 0.1) == 2


def test_lip_one_mm_above_tallest_when_it_fits():
   plan = w.plan_tray([SMALL, MID], 1)
   assert abs(plan["lip_above_floor"] - (MID.max_width + w.LIP_ABOVE)) < 1e-9
   assert plan["total_height"] <= w.MAX_TRAY_HEIGHT


def test_lip_capped_by_tray_limit():
   plan = w.plan_tray([SMALL, MID, BIG], 1)
   assert abs(plan["total_height"] - w.MAX_TRAY_HEIGHT) < 1e-9
   assert plan["lip_wanted"] > plan["lip_above_floor"]
   assert all(k["slab_height"] <= plan["lip_above_floor"] for k in plan["pockets"])


def test_pockets_fit_inside_cavity():
   plan = w.plan_tray([SMALL, MID, BIG], 1)
   cx, cy = plan["cavity"]
   for p in plan["pockets"]:
      assert p["x"] - p["head_width"] / 2 >= -cx / 2 - 1e-9
      assert p["x"] + p["head_width"] / 2 <= cx / 2 + 1e-9
      assert p["y0"] >= -cy / 2 - 1e-9
      assert p["y0"] + p["length"] <= cy / 2 + 1e-9


def test_slabs_tile_the_cavity_and_contain_their_channel():
   plan = w.plan_tray([SMALL, MID, BIG], 1)
   cx, _ = plan["cavity"]
   ks = plan["pockets"]
   assert abs(ks[0]["slab"][0] + cx / 2) < 1e-9
   assert abs(ks[-1]["slab"][1] - cx / 2) < 1e-9
   for a, b in zip(ks, ks[1:]):
      assert abs(a["slab"][1] - b["slab"][0]) < 1e-9
   for k in ks:
      assert k["slab"][0] < k["x"] - k["channel_width"] / 2
      assert k["slab"][1] > k["x"] + k["channel_width"] / 2
   # head pockets end exactly on the slab boundaries, so no slivers of slab remain
   for a, b in zip(ks, ks[1:]):
      assert abs((a["x"] + a["head_width"] / 2) - a["slab"][1]) < 1e-9
      assert abs((b["x"] - b["head_width"] / 2) - b["slab"][0]) < 1e-9


def test_labels_sit_in_the_band_before_the_tips():
   plan = w.plan_tray([SMALL, MID, BIG], 1)
   _, cy = plan["cavity"]
   assert plan["label_band"] > 10          # enough room for ~6 mm digits
   for k in plan["pockets"]:
      lx, ly = k["label"]
      assert lx == k["x"]
      assert -cy / 2 < ly < k["y0"]
      assert k["slab"][0] < lx < k["slab"][1]


def _corner_clearances(plan):
   st = plan["storage"]
   a, b = st["a"], st["b"]
   out = []
   for k in plan["pockets"]:
      tip = k["y0"] + k["length"]
      for x in (k["x"] - k["head_width"] / 2, k["x"] + k["head_width"] / 2):
         out.append((a + b * x - tip) / (1 + b * b) ** 0.5)     # signed perpendicular distance
   return out


def test_storage_edge_clears_every_head_pocket():
   ws = [SMALL, MID, mk(12, 17.3, 11.5, 26, 12, 4.6), BIG]
   plan = w.plan_tray(ws, 1)
   assert plan["storage"] is not None
   assert min(_corner_clearances(plan)) >= w.STORAGE_MARGIN - 1e-6


def test_storage_edge_is_as_low_as_the_margin_allows():
   ws = [SMALL, MID, mk(12, 17.3, 11.5, 26, 12, 4.6), BIG]
   plan = w.plan_tray(ws, 1)
   # at least one corner is exactly at the margin, or the line would be too high
   assert abs(min(_corner_clearances(plan)) - w.STORAGE_MARGIN) < 1e-4
   st = plan["storage"]
   assert st["b"] > 0                        # rises toward the longer wrenches
   # the edge really is straight: outline is line end, line end, wall, wall
   (x0, y0), (x1, y1), (x1b, yt), (x0b, yt2) = st["outline"]
   assert abs(y0 - (st["a"] + st["b"] * x0)) < 1e-9 and abs(y1 - (st["a"] + st["b"] * x1)) < 1e-9
   assert x1b == x1 and x0b == x0 and yt == yt2 == plan["cavity"][1] / 2


def test_storage_edge_y_matches_line():
   ws = [SMALL, MID, BIG]
   plan = w.plan_tray(ws, 1)
   st = plan["storage"]
   xm = (st["x0"] + st["x1"]) / 2
   assert abs(w.storage_edge_y(st, xm) - (st["a"] + st["b"] * xm)) < 1e-9
   assert w.storage_edge_y(st, st["x1"] + 1) is None


def test_storage_ends_where_depth_runs_out():
   ws = [SMALL, MID, mk(12, 17.3, 11.5, 26, 12, 4.6), BIG]
   plan = w.plan_tray(ws, 1)
   st = plan["storage"]
   _, cy = plan["cavity"]
   assert cy / 2 - st["y1"] >= w.STORAGE_MIN - 1e-9
   if st["x1"] < plan["cavity"][0] / 2 - 1e-9:
      assert abs((cy / 2 - st["y1"]) - w.STORAGE_MIN) < 1e-9


def test_no_storage_pocket_when_nothing_fits():
   plan = w.plan_tray([BIG, mk(20, 24.7, 17, 40, 15.4, 6.9)], 1)
   st = plan["storage"]
   _, cy = plan["cavity"]
   depth = cy / 2 - (plan["pockets"][0]["y0"] + BIG.length + w.STORAGE_MARGIN)
   assert (st is None) == (depth < w.STORAGE_MIN)


def test_pockets_are_spaced_by_pitch():
   plan = w.plan_tray([SMALL, MID, BIG], 1)
   xs = [p["x"] for p in plan["pockets"]]
   assert abs((xs[1] - xs[0]) - w.pitch(SMALL, MID)) < 1e-9
   assert abs((xs[2] - xs[1]) - w.pitch(MID, BIG)) < 1e-9


def test_split_respects_max_units():
   ws = [mk(s, 20, 10, 40, 40, 5) for s in range(8)]    # 8 wrenches, 43 mm pitch
   trays = w.split_trays(ws, max_units=7)
   assert sum(len(t) for t in trays) == 8
   assert [x.size for t in trays for x in t] == list(range(8))
   for t in trays:
      assert w.units_for(w.inner_width(t)) <= 7


def test_split_single_when_it_fits():
   assert w.split_trays([SMALL, MID], max_units=7) == [[SMALL, MID]]


if __name__ == "__main__":
   import sys
   fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
   failed = 0
   for fn in fns:
      try:
         fn()
         print(f"ok   {fn.__name__}")
      except Exception as e:
         failed += 1
         print(f"FAIL {fn.__name__}: {e!r}")
   sys.exit(1 if failed else 0)
