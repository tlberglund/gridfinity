# Gridfinity wrench trays

Generates Gridfinity trays that hold a set of combination wrenches on
edge, side by side, sorted by size, so each one only takes up its head
thickness across the tray. Each handle drops into a snug channel; the
heads rest on open floor with clearance to their neighbours; a wall runs
around the tray 1 mm above the tallest wrench, or as high as the 40 mm
tray limit allows.

## Wrench data

`wrenches.csv` has one row per wrench:

```
wrench,length,handle_width,max_width,height,handle_thickness
10,15.6,10.5,21,12,3.9
```

- `wrench` is the nominal size and the sort key.
- `length` is overall length in **centimetres**; everything else is millimetres.
- `handle_width` is the handle's width in the plane of the wrench. On edge
  it sets how far the handle floats above the floor: `(max_width - handle_width) / 2`.
- `max_width` is the widest point of either head, and so how tall the
  wrench stands on edge.
- `height` is the thickness of the thickest head; it sets the spacing.
- `handle_thickness` is what the channel grips.

## Generating

```
../.venv/bin/python wrenches.py           # build (skips if output/trays.md exists)
../.venv/bin/python wrenches.py --force   # rebuild
../.venv/bin/python wrenches.py --plan    # print the plan only, no CAD
../.venv/bin/python test_wrenches.py      # planning-logic tests
```

Output goes to `output/`: one STL and SVG preview per tray plus `trays.md`
summarising the grid size, height and per-wrench pocket dimensions.

## How the layout works

- Channel width is `handle_thickness + HANDLE_CLEARANCE` (0.8 mm).
- Centre-to-centre spacing between neighbours is the average of their head
  thicknesses (`height`) plus `HEAD_GAP` (3 mm), so heads never touch.
- Head pockets at both ends are `HEAD_LEN_FACTOR` (1.5) times `max_width`
  long. Head length is not in the CSV, so this is an estimate; the pockets
  merge into one open area, so overestimating only shortens the channels.
- Each wrench gets its own slab whose channel walls reach `ENGAGE` (6 mm)
  up the handle's edge, so bigger wrenches get taller walls and every
  head stands proud of its slab for grabbing.
- The perimeter wall is `max_width + LIP_ABOVE` above the floor, capped
  so the tray never exceeds `MAX_TRAY_HEIGHT` (40 mm). `trays.md` lists any
  wrenches that stand above the capped wall.
- If the set is wider than `MAX_UNITS` (7) grid units, wrenches are packed
  greedily into several trays.
- Each wrench's size is embossed `LABEL_H` (1 mm) high on top of its slab,
  in the band between the wrench tips and the wall at the aligned end,
  reading upright from that end. `LABEL_FONT` (8) gives roughly 6 mm digits.
- The space beyond the wrench tips becomes a storage pocket cut to the
  floor. Its near edge is a straight line: the lowest one that stays
  `STORAGE_MARGIN` (3 mm, measured perpendicular to the line) clear of the
  top corners of every wrench's far head pocket, which gives the largest
  pocket a straight edge can. The pocket ends where less than `STORAGE_MIN`
  (10 mm) of depth remains between the line and the far wall.

- Channel wall heights and head pocket lengths are rounded up to a `STEP`
  (3 mm) grid, so neighbouring slabs are either flush or step by at least
  3 mm, and the outermost head pockets run into the side walls. Both keep
  the geometry free of slivers that fillets cannot cross.
- Every edge above the Gridfinity base is rounded with `FILLET_R` (1 mm);
  the size labels are added afterwards and stay sharp. Edges whose
  neighbouring faces are too small for the radius get a smaller one, or
  none below `FILLET_MIN`. The fillet runs in a worker subprocess because
  OpenCascade can crash on awkward edge sets; if it refuses any edges the
  build prints which ones stayed sharp.

All of these are constants at the top of `wrenches.py`.
