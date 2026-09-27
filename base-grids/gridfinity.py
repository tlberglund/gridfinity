"""
Gridfinity baseplates for drawers, split to fit a print bed.

Drawers are listed in drawers.csv (name,width,length,notes). For each one
the script picks the largest grid that fits, splits it into as few plates
as the bed allows, widens the outer plates' borders so the set fills the
drawer, and writes the STLs plus a drawer.md summary to output/<name>/.

Usage:
   .venv/bin/python gridfinity.py                # build every drawer not yet built
   .venv/bin/python gridfinity.py kitchen-top    # build just this drawer (skips if built)
   .venv/bin/python gridfinity.py --force        # rebuild everything
   .venv/bin/python gridfinity.py --plan         # print plans only, no CAD
"""
import argparse
import csv
import math
import os
import sys

# ---------------------------------------------------------------- parameters
BED = 300.0              # printer bed edge, mm (assumed square)
DRAWER_CLEARANCE = 1.0   # total slop per axis, split between the two sides

PITCH = 42.0             # Gridfinity unit

# Baseplate socket profile (Gridfinity spec, top to bottom)
TOP_CHAMFER = 2.15
STRAIGHT = 1.8
BOT_CHAMFER = 0.7
HEIGHT = TOP_CHAMFER + STRAIGHT + BOT_CHAMFER   # 4.65
CELL_TOP = PITCH - 0.5   # 41.5 mm opening at the top of each socket
CELL_TOP_R = 3.75        # corner radius at the top of the socket
OUTER_R = 4.0            # corner radius of the plate outline

STL_TOL = 0.01
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(HERE, "drawers.csv")
DEFAULT_OUT = os.path.join(HERE, "output")


# ----------------------------------------------------------------- planning
# Pure functions, no CAD. Tested in test_gridfinity.py.

def outer_size(units):
   """Outer dimension of a plain plate edge holding this many units."""
   return units * PITCH - 0.5


def split_even(units, n):
   """Divide units into n plates as evenly as possible, largest first."""
   base, rem = divmod(units, n)
   return [base + 1] * rem + [base] * (n - rem)


def plan_axis(drawer, bed=BED, clearance=DRAWER_CLEARANCE):
   """
   For one axis of a drawer, return (units, border, splits):
   total grid units, extra solid border on each outer edge, and the units
   per plate from one end to the other.
   """
   usable = drawer - clearance
   units = int((usable + 0.5) // PITCH)
   if units < 1:
      raise ValueError(f"{drawer} mm is too small for a single {PITCH} mm unit")
   border = (usable - outer_size(units)) / 2
   n = 1
   while True:
      splits = split_even(units, n)
      if 0 in splits:
         raise ValueError(f"cannot split {units} units to fit a {bed} mm bed")
      edge_extra = 2 * border if n == 1 else border
      if outer_size(max(splits)) + edge_extra <= bed:
         return units, border, splits
      n += 1


def plan_drawer(name, width, length, notes="", bed=BED, clearance=DRAWER_CLEARANCE):
   """Full plan for a drawer: grid, borders, and one entry per plate."""
   ux, bx, sx = plan_axis(width, bed, clearance)
   uy, by, sy = plan_axis(length, bed, clearance)
   plates = []
   for j, py in enumerate(sy):            # rows, front to back
      for i, px in enumerate(sx):         # columns, left to right
         left = bx if i == 0 else 0
         right = bx if i == len(sx) - 1 else 0
         front = by if j == 0 else 0
         back = by if j == len(sy) - 1 else 0
         plates.append({
            "file": f"plate_row{j + 1}_col{i + 1}_{px}x{py}.stl",
            "row": j + 1, "col": i + 1,
            "units": (px, py),
            "borders": {"left": left, "right": right, "front": front, "back": back},
            "footprint": (outer_size(px) + left + right, outer_size(py) + front + back),
         })
   return {
      "name": name, "width": width, "length": length, "notes": notes,
      "units": (ux, uy), "border": (bx, by), "splits": (sx, sy),
      "assembled": (outer_size(ux) + 2 * bx, outer_size(uy) + 2 * by),
      "clearance": clearance, "bed": bed, "plates": plates,
   }


def render_markdown(plan):
   ux, uy = plan["units"]
   ax, ay = plan["assembled"]
   bx, by = plan["border"]
   sx, sy = plan["splits"]
   lines = [
      f"# {plan['name']}",
      "",
      f"Drawer: {plan['width']:g} x {plan['length']:g} mm (width x length)",
   ]
   if plan["notes"]:
      lines.append(f"Notes: {plan['notes']}")
   lines += [
      "",
      f"- Grid: {ux} x {uy} units ({ux * uy} cells)",
      f"- Assembled size: {ax:.1f} x {ay:.1f} mm, {plan['clearance']:g} mm total clearance per axis",
      f"- Border on outer edges: {bx:.2f} mm left/right, {by:.2f} mm front/back",
      f"- Plates: {len(plan['plates'])} ({len(sx)} across x {len(sy)} deep), bed {plan['bed']:g} mm",
      "",
      "| File | Position | Units | Footprint (mm) |",
      "|---|---|---|---|",
   ]
   for p in plan["plates"]:
      fx, fy = p["footprint"]
      lines.append(f"| {p['file']} | row {p['row']} col {p['col']} | "
                   f"{p['units'][0]}x{p['units'][1]} | {fx:.2f} x {fy:.2f} |")
   lines += ["", "Layout, viewed from above (row 1 is the front, col 1 is the left):", "", "```"]
   for j in range(len(sy) - 1, -1, -1):
      row = [p for p in plan["plates"] if p["row"] == j + 1]
      lines.append("  ".join(f"[r{p['row']}c{p['col']} {p['units'][0]}x{p['units'][1]}]" for p in row))
   lines += ["```", "", "Print each plate flat, no supports, 4.65 mm tall open lattice.", ""]
   return "\n".join(lines)


# ---------------------------------------------------------------------- CAD
def _cq():
   import cadquery as cq
   return cq


def rrect_wire(width, radius, z):
   """Square wire of the given width with filleted corners at height z."""
   cq = _cq()
   sk = cq.Sketch().rect(width, width).vertices().fillet(radius)
   return sk._faces.Faces()[0].outerWire().translate((0, 0, z))


def socket():
   """One Gridfinity socket as a solid, bottom at z=0, top at z=HEIGHT."""
   cq = _cq()
   mid = CELL_TOP - 2 * TOP_CHAMFER          # 37.2
   mid_r = CELL_TOP_R - TOP_CHAMFER          # 1.5
   bot = mid - 2 * BOT_CHAMFER               # 35.8
   bot_r = mid_r - BOT_CHAMFER               # 0.8
   wires = [
      rrect_wire(bot, bot_r, 0),
      rrect_wire(mid, mid_r, BOT_CHAMFER),
      rrect_wire(mid, mid_r, BOT_CHAMFER + STRAIGHT),
      rrect_wire(CELL_TOP, CELL_TOP_R, HEIGHT),
   ]
   return cq.Solid.makeLoft(wires, ruled=True)


def baseplate(units_x, units_y, left=0, right=0, front=0, back=0):
   """
   Open-bottom lattice baseplate. The grid of sockets is centered on the
   origin; left/right/front/back add extra solid border on that side.
   """
   cq = _cq()
   grid_w, grid_d = outer_size(units_x), outer_size(units_y)
   length, width = grid_w + left + right, grid_d + front + back
   plate = (
      cq.Workplane("XY")
      .center((right - left) / 2, (back - front) / 2)
      .sketch().rect(length, width).vertices().fillet(OUTER_R).finalize()
      .extrude(HEIGHT)
   )
   sock = socket()
   cells = []
   for i in range(units_x):
      for j in range(units_y):
         x = (i - (units_x - 1) / 2) * PITCH
         y = (j - (units_y - 1) / 2) * PITCH
         cells.append(sock.translate((x, y, 0)))
   return plate.cut(cq.Compound.makeCompound(cells))


def build_drawer(plan, out_dir):
   cq = _cq()
   os.makedirs(out_dir, exist_ok=True)
   for stale in os.listdir(out_dir):
      if stale.endswith(".stl") or stale == "drawer.md":
         os.remove(os.path.join(out_dir, stale))
   for p in plan["plates"]:
      wp = baseplate(*p["units"], **p["borders"])
      solid = wp.val()
      bb = solid.BoundingBox(tolerance=1e-6)   # measure before export: meshing pads the box
      path = os.path.join(out_dir, p["file"])
      cq.exporters.export(wp, path, tolerance=STL_TOL, angularTolerance=0.05)
      fx, fy = p["footprint"]
      ok = (solid.isValid() and len(wp.solids().vals()) == 1
            and abs(bb.xlen - fx) < 0.01 and abs(bb.ylen - fy) < 0.01)
      print(f"   {p['file']:28s} {bb.xlen:7.2f} x {bb.ylen:7.2f} mm  {'ok' if ok else 'PROBLEM'}")
      if not ok:
         raise RuntimeError(f"{p['file']} failed geometry check")


# --------------------------------------------------------------------- main
def read_csv(path):
   with open(path, newline="") as f:
      rows = list(csv.DictReader(f))
   drawers = []
   for r in rows:
      name = r["name"].strip()
      if not name or name.startswith("#"):
         continue
      drawers.append((name, float(r["width"]), float(r["length"]), (r.get("notes") or "").strip()))
   return drawers


def is_built(out_dir):
   """drawer.md is written last, so its presence means the build finished."""
   return os.path.exists(os.path.join(out_dir, "drawer.md"))


def main(argv=None):
   ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
   ap.add_argument("names", nargs="*", help="drawer names to build (default: all)")
   ap.add_argument("--force", action="store_true", help="rebuild drawers that already have STLs")
   ap.add_argument("--plan", action="store_true", help="print plans and drawer.md, no CAD")
   ap.add_argument("--csv", default=DEFAULT_CSV)
   ap.add_argument("--out", default=DEFAULT_OUT)
   args = ap.parse_args(argv)

   drawers = read_csv(args.csv)
   if args.names:
      known = {d[0] for d in drawers}
      missing = [n for n in args.names if n not in known]
      if missing:
         sys.exit(f"not in {args.csv}: {', '.join(missing)}")
      drawers = [d for d in drawers if d[0] in args.names]

   for name, width, length, notes in drawers:
      out_dir = os.path.join(args.out, name)
      if is_built(out_dir) and not args.force and not args.plan:
         print(f"== {name}: already built, skipping (use --force to rebuild)")
         continue
      plan = plan_drawer(name, width, length, notes)
      md = render_markdown(plan)
      print(md)
      if args.plan:
         continue
      build_drawer(plan, out_dir)
      with open(os.path.join(out_dir, "drawer.md"), "w") as f:
         f.write(md)
      print(f"   wrote {len(plan['plates'])} STLs and drawer.md to {out_dir}\n")


if __name__ == "__main__":
   main()
