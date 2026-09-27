# Gridfinity drawer baseplates

Generates Gridfinity baseplates that fill a drawer edge to edge, split into
pieces that fit a 300 x 300 mm print bed. Drawers are listed in a CSV; each
one gets its own output directory with STLs and a summary.

## Setup

Requires Python 3 and [CadQuery](https://cadquery.readthedocs.io/). A virtual
environment with CadQuery installed already lives in `.venv/`. To recreate it:

```
python3 -m venv .venv
.venv/bin/pip install cadquery
```

## Adding a drawer

Add a row to `drawers.csv`. Dimensions are the drawer's interior in
millimetres.

```
name,width,length,notes
kitchen-top,546,419,left of the stove
```

- `name` becomes the output directory, so keep it filesystem-friendly.
- `width` is left to right, `length` is front to back, as you face the drawer.
- `notes` is optional free text and is copied into the summary.

## Generating

```
.venv/bin/python gridfinity.py              # build every drawer not yet built
.venv/bin/python gridfinity.py kitchen-top  # build only this drawer
.venv/bin/python gridfinity.py --force      # rebuild everything
.venv/bin/python gridfinity.py --plan       # print plans only, no CAD
```

A drawer is considered built when `output/<name>/drawer.md` exists, since
that file is written last. Delete it, or use `--force`, to regenerate. Each
drawer takes a few seconds.

Output for each drawer lands in `output/<name>/`:

- `plate_rowN_colM_WxD.stl`, one per plate. Row 1 is the front of the drawer,
  col 1 is the left. `WxD` is the plate's grid size in units.
- `drawer.md`, a summary with the grid size, border widths, a table of plates
  with footprints, and a top-down layout map. The same text is printed to the
  terminal.

## Printing

Print each plate flat, no supports. Plates are 4.65 mm tall open lattices
with no floor, so they're quick and light on filament. Every plate is sized
to fit the bed, borders included.

Lay them in the drawer per the layout map in `drawer.md`. The outer plates
have widened solid borders so the set fills the drawer with 1 mm of total
play per axis. Interior seams keep the 42 mm pitch, so bins span plates
freely.

## How the plan is chosen

For each axis the script:

1. Subtracts the clearance and fits the largest whole number of 42 mm units.
2. Splits the leftover evenly between the two outer edges as a solid border.
3. Divides the units into the fewest plates whose footprint, including that
   border, fits the bed.

For example, 546 mm becomes 12 units with 20.75 mm borders as 6 + 6, and
419 mm becomes 9 units with 20.25 mm borders as 5 + 4.

## Tuning

Constants at the top of `gridfinity.py`:

- `BED`: print bed edge, assumed square.
- `DRAWER_CLEARANCE`: total slop per axis. Raise it if a set is a tight fit,
  lower it for a snugger fit.
- Socket profile values follow the Gridfinity spec and shouldn't need
  changing.

## Tests

The plate-planning logic is pure Python and has tests:

```
.venv/bin/python test_gridfinity.py
```

## Files

- `gridfinity.py`: planner and CAD generator.
- `drawers.csv`: the list of drawers. Source of truth.
- `test_gridfinity.py`: planning tests.
- `output/`: generated STLs and summaries, one directory per drawer.
