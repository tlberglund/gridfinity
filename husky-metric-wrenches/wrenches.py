"""
Gridfinity trays for a set of combination wrenches, stored on edge.

Wrenches are listed in wrenches.csv (wrench,length,handle_width,max_width,
height,handle_thickness; length in cm, everything else in mm). They stand on
their sides, side by side, sorted by size, so each one only takes up its
head thickness across the tray. The handle drops into a snug channel
(handle_thickness + HANDLE_CLEARANCE) cut into a slab whose height reaches
ENGAGE mm up the handle; the heads, which are thicker than the handle, rest
on the open floor with at least HEAD_GAP between neighbours. A perimeter
wall rises LIP_ABOVE past the tallest wrench, capped so the tray never
exceeds MAX_TRAY_HEIGHT. Each wrench's size is embossed on its slab, in
the band between the wrench tips and the wall at the aligned end. The
space left over beyond the wrench tips becomes a storage pocket, cut to
the floor, whose near edge is the lowest straight line that clears every
wrench's head pocket by STORAGE_MARGIN.

If the set is wider than MAX_UNITS grid units it is split greedily into
several trays. STLs, an SVG preview and a trays.md summary go to output/.

Usage:
   ../.venv/bin/python wrenches.py           # build (skips if trays.md exists)
   ../.venv/bin/python wrenches.py --force   # rebuild
   ../.venv/bin/python wrenches.py --plan    # print the plan only, no CAD
"""
import argparse
import csv
import math
import os
import subprocess
import sys
import tempfile
from collections import namedtuple

# ---------------------------------------------------------------- parameters
MAX_TRAY_HEIGHT = 40.0    # hard limit from the drawer, mm
MAX_UNITS = 7             # 7 * 42 - 0.5 = 293.5 mm, fits a 300 mm bed

HANDLE_CLEARANCE = 0.8    # channel is this much wider than the handle (< 1 mm)
HEAD_GAP = 3.0            # minimum clearance between neighbouring wrench heads
HEAD_LEN_FACTOR = 1.5     # head pocket length = this * max_width (not in the CSV)
HEAD_POCKET_EXTRA = HEAD_GAP   # head pocket width = head thickness + this: neighbouring head
                               # pockets meet exactly on the midline between the heads
ENGAGE = 6.0              # channel walls reach this far up the handle's edge
STEP = 3.0                # slab heights and head pocket lengths round up to this grid, so
                          # neighbouring features are flush or step by at least STEP (fillets need it)
FILLET_R = 1.0            # radius on every edge above the base grid (labels excepted)
FILLET_MIN = 0.2          # edges whose neighbouring faces are too small for this get no fillet
LIP_ABOVE = 1.0           # wall top sits this far above the tallest wrench (if the cap allows)
SIDE_MARGIN = 1.5         # floor between the outermost heads and the wall
END_MARGIN = 1.0          # floor between wrench tips and the wall
LABEL_H = 1.0             # raised height of the size numbers
LABEL_FONT = 8.0          # font size of the size numbers (digits come out ~6 mm tall)
STORAGE_MARGIN = 3.0      # slab left between the storage pocket's edge and any wrench pocket
STORAGE_MIN = 10.0        # the pocket ends where less depth than this remains to the far wall

WALL = 2.4                # perimeter wall thickness (room for two 1 mm fillets on top)
FLOOR_T = 1.25            # floor thickness above the base profile

# Gridfinity bin base profile (spec, bottom to top)
PITCH = 42.0
BOT_CHAMFER = 0.8
STRAIGHT = 1.8
TOP_CHAMFER = 2.15
BASE_H = BOT_CHAMFER + STRAIGHT + TOP_CHAMFER   # 4.75
UNIT_TOP = PITCH - 0.5                          # 41.5
UNIT_TOP_R = 3.75

STL_TOL = 0.05            # mesh chord tolerance, mm (fillets make 0.01 a 100 MB file)
STL_ANG = 0.2             # mesh angular tolerance, rad
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(HERE, "wrenches.csv")
DEFAULT_OUT = os.path.join(HERE, "output")

Wrench = namedtuple("Wrench", "size length handle_width max_width height handle_thickness")


# ----------------------------------------------------------------- planning
# Pure functions, no CAD. Tested in test_wrenches.py.
# On edge: "across" is the wrench's thickness, "up" is its width.

def outer_size(units):
   return units * PITCH - 0.5


def units_for(inner):
   """Grid units needed so the cavity (outer minus two walls) holds `inner`."""
   return max(1, math.ceil((inner + 2 * WALL + 0.5) / PITCH - 1e-9))


def pitch(a, b):
   """Centre-to-centre spacing so the heads of a and b clear by HEAD_GAP."""
   return (a.height + b.height) / 2 + HEAD_GAP


def channel_width(w):
   return w.handle_thickness + HANDLE_CLEARANCE


def head_width(w):
   return w.height + HEAD_POCKET_EXTRA


def round_up(v, step=STEP):
   return math.ceil(v / step - 1e-9) * step


def head_length(w):
   return round_up(HEAD_LEN_FACTOR * w.max_width)


def standing_height(w):
   """How far the wrench reaches above the floor when on edge."""
   return w.max_width


def handle_lift(w):
   """Gap between the floor and the handle's lower edge (heads are wider)."""
   return (w.max_width - w.handle_width) / 2


def slab_height(w):
   """Channel wall height for this wrench: up the handle by ENGAGE, rounded up to STEP."""
   return round_up(handle_lift(w) + ENGAGE)


def inner_width(ws):
   """Cavity width needed for these wrenches side by side."""
   span = sum(pitch(a, b) for a, b in zip(ws, ws[1:]))
   return span + ws[0].height / 2 + ws[-1].height / 2 + 2 * SIDE_MARGIN


def inner_length(ws):
   return max(w.length for w in ws) + 2 * END_MARGIN


def split_trays(ws, max_units=MAX_UNITS):
   """Greedily pack the sorted wrenches into trays no wider than max_units."""
   trays, cur = [], []
   for w in ws:
      if cur and units_for(inner_width(cur + [w])) > max_units:
         trays.append(cur)
         cur = []
      cur.append(w)
      if units_for(inner_width(cur)) > max_units:
         raise ValueError(f"{w.size} mm wrench alone needs more than {max_units} units")
   trays.append(cur)
   return trays


def storage_pocket(ws, pockets, cavity, margin=STORAGE_MARGIN, minimum=STORAGE_MIN):
   """
   Pocket beyond the wrench tips bounded by a straight line y = a + b*x.
   The line is the lowest one (largest pocket) that stays `margin` away,
   measured perpendicular to the line, from the top corners of every far
   head pocket. The pocket spans the x range where at least `minimum` depth
   remains between the line and the far wall. Returns None if that is empty.
   """
   cx, cy = cavity
   corners = []
   for p in pockets:
      tip = p["y0"] + p["length"]
      corners += [(p["x"] - p["head_width"] / 2, tip), (p["x"] + p["head_width"] / 2, tip)]

   def intercept(b):
      # lowest intercept for this slope that clears every corner by the margin
      return max(y - b * x for x, y in corners) + margin * math.sqrt(1 + b * b)

   # the pocket area is cx*cy/2 - a*cx over a centred cavity, so minimise a
   # over the slope; intercept() is convex in b, so a ternary search finds it
   lo, hi = -10.0, 10.0
   for _ in range(200):
      m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
      if intercept(m1) < intercept(m2):
         hi = m2
      else:
         lo = m1
   b = (lo + hi) / 2
   a = intercept(b)

   def line(x):
      return a + b * x

   # x range with enough depth left
   x0, x1 = -cx / 2, cx / 2
   limit = cy / 2 - minimum
   if abs(b) > 1e-12:
      x_cross = (limit - a) / b
      if b > 0:
         x1 = min(x1, x_cross)
      else:
         x0 = max(x0, x_cross)
   elif a > limit:
      return None
   if x1 - x0 < 1e-6:
      return None
   outline = [(x0, line(x0)), (x1, line(x1)), (x1, cy / 2), (x0, cy / 2)]
   # same shape pushed 5 mm past the walls along the line, so the cavity
   # outline trims it instead of the walls setting its edges
   ex0 = x0 - 5 if x0 <= -cx / 2 + 1e-9 else x0
   ex1 = x1 + 5 if x1 >= cx / 2 - 1e-9 else x1
   cut_outline = [(ex0, line(ex0)), (ex1, line(ex1)), (ex1, cy / 2 + 5), (ex0, cy / 2 + 5)]
   area = (x1 - x0) * cy / 2 - (a * (x1 - x0) + b * (x1 * x1 - x0 * x0) / 2)
   return dict(a=a, b=b, x0=x0, x1=x1, y0=line(x0), y1=line(x1),
               angle=math.degrees(math.atan(b)), outline=outline, cut_outline=cut_outline, area=area)


def storage_edge_y(storage, x):
   """The pocket's near edge at this x (None outside the pocket)."""
   if storage["x0"] - 1e-9 <= x <= storage["x1"] + 1e-9:
      return storage["a"] + storage["b"] * x
   return None


def plan_tray(ws, index):
   """Everything the CAD step needs for one tray. Origin at the tray centre."""
   ux, uy = units_for(inner_width(ws)), units_for(inner_length(ws))
   outer = (outer_size(ux), outer_size(uy))
   cavity = (outer[0] - 2 * WALL, outer[1] - 2 * WALL)

   tallest = max(standing_height(w) for w in ws)
   wanted_lip = tallest + LIP_ABOVE
   lip = min(wanted_lip, MAX_TRAY_HEIGHT - BASE_H - FLOOR_T)
   total = BASE_H + FLOOR_T + lip

   # wrenches centred as a group in x, aligned at one end and centred in y
   span = inner_width(ws) - 2 * SIDE_MARGIN
   x = -span / 2 + ws[0].height / 2
   longest = max(w.length for w in ws)
   y0 = -longest / 2
   xs = []
   for i, w in enumerate(ws):
      if i:
         x += pitch(ws[i - 1], w)
      xs.append(x)
   # each wrench owns a slab out to the midline between its head and the
   # neighbour's head (where the head pockets meet), or to the wall
   bounds = ([-cavity[0] / 2] + [x + w.height / 2 + HEAD_GAP / 2 for x, w in zip(xs, ws[:-1])]
             + [cavity[0] / 2])
   label_y = (-cavity[1] / 2 + y0) / 2      # middle of the band before the wrench tips
   pockets = []
   for i, w in enumerate(ws):
      pockets.append(dict(
         size=w.size, x=xs[i], y0=y0, length=w.length,
         channel_width=channel_width(w), head_width=head_width(w),
         head_length=head_length(w), slab=(bounds[i], bounds[i + 1]),
         slab_height=min(slab_height(w), lip), standing=standing_height(w),
         label=(xs[i], label_y),
         to_wall=("left" if i == 0 else "right" if i == len(ws) - 1 else None),
      ))
   return dict(
      index=index, wrenches=ws, units=(ux, uy), outer=outer, cavity=cavity,
      lip_above_floor=lip, lip_wanted=wanted_lip, total_height=total,
      label_band=y0 + cavity[1] / 2, storage=storage_pocket(ws, pockets, cavity),
      pockets=pockets, file=f"tray{index}_{ws[0].size}-{ws[-1].size}mm_{ux}x{uy}.stl",
   )


def plan_all(ws):
   ws = sorted(ws, key=lambda w: w.size)
   return [plan_tray(t, i + 1) for i, t in enumerate(split_trays(ws))]


def render_markdown(plans):
   out = ["# Wrench trays (wrenches on edge)", ""]
   for p in plans:
      ux, uy = p["units"]
      ox, oy = p["outer"]
      sizes = ", ".join(str(w.size) for w in p["wrenches"])
      out += [
         f"## Tray {p['index']}: {sizes} mm",
         "",
         f"- file: `{p['file']}`",
         f"- grid: {ux} x {uy} units, {ox:.1f} x {oy:.1f} mm footprint",
         f"- height: {p['total_height']:.2f} mm total; wall top {p['lip_above_floor']:.1f} mm above the floor",
         f"- sizes embossed {LABEL_H:.0f} mm high on each slab, {p['label_band']:.1f} mm band before the wrench tips",
      ]
      st = p["storage"]
      if st:
         cy = p["cavity"][1]
         out.append(f"- storage pocket beyond the wrench tips, cut to the floor, with a straight near edge "
                    f"rising at {st['angle']:.1f} deg, {STORAGE_MARGIN:.0f} mm clear of the wrench pockets: "
                    f"{st['x1'] - st['x0']:.1f} mm wide, {cy / 2 - st['y0']:.1f} mm deep at the "
                    f"{p['wrenches'][0].size} mm end tapering to {cy / 2 - st['y1']:.1f} mm, {st['area'] / 100:.0f} cm2")
      if p["lip_wanted"] > p["lip_above_floor"] + 1e-9:
         over = [f"{k['size']} mm (+{k['standing'] - p['lip_above_floor']:.1f})"
                 for k in p["pockets"] if k["standing"] > p["lip_above_floor"]]
         out.append(f"- wall capped by the {MAX_TRAY_HEIGHT:.0f} mm tray limit; "
                    f"{LIP_ABOVE:.0f} mm over the tallest wrench would need "
                    f"{p['lip_wanted'] - p['lip_above_floor']:.1f} mm more. "
                    f"Standing above the wall: {', '.join(over)}")
      else:
         out.append(f"- wall is {LIP_ABOVE:.0f} mm above the tallest wrench")
      out += [
         "",
         "| wrench | channel width | wall height | head pocket | stands | pitch to next |",
         "|-------:|--------------:|------------:|------------:|-------:|--------------:|",
      ]
      ws = p["wrenches"]
      for i, (w, k) in enumerate(zip(ws, p["pockets"])):
         nxt = f"{pitch(w, ws[i + 1]):.2f}" if i + 1 < len(ws) else "-"
         out.append(f"| {w.size} | {k['channel_width']:.1f} | {k['slab_height']:.1f} | "
                    f"{k['head_width']:.1f} x {k['head_length']:.1f} | {k['standing']:.1f} | {nxt} |")
      out.append("")
   return "\n".join(out)


# ---------------------------------------------------------------------- CAD
def _cq():
   import cadquery as cq
   return cq


def rrect_wire(w, d, radius, z):
   cq = _cq()
   sk = cq.Sketch().rect(w, d).vertices().fillet(radius)
   return sk._faces.Faces()[0].outerWire().translate((0, 0, z))


def unit_base():
   """One Gridfinity bin foot, bottom at z=0, top (41.5 square) at z=BASE_H."""
   cq = _cq()
   mid = UNIT_TOP - 2 * TOP_CHAMFER          # 37.2
   mid_r = UNIT_TOP_R - TOP_CHAMFER          # 1.6
   bot = mid - 2 * BOT_CHAMFER               # 35.6
   bot_r = mid_r - BOT_CHAMFER               # 0.8
   wires = [
      rrect_wire(bot, bot, bot_r, 0),
      rrect_wire(mid, mid, mid_r, BOT_CHAMFER),
      rrect_wire(mid, mid, mid_r, BOT_CHAMFER + STRAIGHT),
      rrect_wire(UNIT_TOP, UNIT_TOP, UNIT_TOP_R, BASE_H),
   ]
   return cq.Solid.makeLoft(wires, ruled=True)


def build_tray(p, with_labels=True):
   cq = _cq()
   ux, uy = p["units"]
   ox, oy = p["outer"]
   cx, cy = p["cavity"]
   floor_top = BASE_H + FLOOR_T
   top = p["total_height"]

   foot = unit_base()
   feet = [foot.translate(((i - (ux - 1) / 2) * PITCH, (j - (uy - 1) / 2) * PITCH, 0))
           for i in range(ux) for j in range(uy)]
   body = cq.Workplane("XY").add(cq.Compound.makeCompound(feet)).combine()

   shell = (cq.Workplane("XY", origin=(0, 0, BASE_H))
            .sketch().rect(ox, oy).vertices().fillet(UNIT_TOP_R).finalize()
            .extrude(top - BASE_H))
   body = body.union(shell)

   cavity_outline = (cq.Workplane("XY", origin=(0, 0, floor_top))
                     .sketch().rect(cx, cy).vertices().fillet(UNIT_TOP_R - WALL).finalize())
   body = body.cut(cavity_outline.extrude(top))

   # one slab per wrench, each as tall as that wrench's channel walls need,
   # clipped to the rounded cavity outline
   slabs = []
   for k in p["pockets"]:
      x0, x1 = k["slab"]
      slabs.append(cq.Solid.makeBox(x1 - x0, cy, k["slab_height"], pnt=cq.Vector(x0, -cy / 2, floor_top)))
   tallest = max(k["slab_height"] for k in p["pockets"])
   platform = slabs[0].fuse(*slabs[1:]).clean().intersect(cavity_outline.extrude(tallest).val())
   body = body.union(platform)

   cut_h = tallest + 1
   boxes = []

   def box(xc, yc, w, l):
      boxes.append(cq.Solid.makeBox(w, l, cut_h, pnt=cq.Vector(xc - w / 2, yc - l / 2, floor_top)))

   for k in p["pockets"]:
      hl = k["head_length"]
      box(k["x"], k["y0"] + k["length"] / 2, k["channel_width"], k["length"])
      # outermost head pockets run into the side wall rather than leaving a sliver of slab
      hx, hw = k["x"], k["head_width"]
      if k["to_wall"] == "left":
         hx, hw = (k["x"] + hw / 2 - cx / 2 - 5) / 2, k["x"] + hw / 2 + cx / 2 + 5
      elif k["to_wall"] == "right":
         hx, hw = (k["x"] - hw / 2 + cx / 2 + 5) / 2, cx / 2 + 5 - (k["x"] - hw / 2)
      box(hx, k["y0"] + hl / 2, hw, hl)
      box(hx, k["y0"] + k["length"] - hl / 2, hw, hl)
   st = p["storage"]
   if st:
      prism = (cq.Workplane("XY", origin=(0, 0, floor_top)).polyline(st["cut_outline"]).close().extrude(cut_h)
               .val().intersect(cavity_outline.extrude(cut_h).val()))
      boxes.append(prism)
   pockets = boxes[0].fuse(*boxes[1:]).clean().intersect(cavity_outline.extrude(cut_h).val())
   body = body.cut(pockets)

   if FILLET_R > 0:
      body = cq.Workplane("XY").add(fillet_above_base(body.val()))

   if with_labels:
      labels = [label_solid(k, floor_top) for k in p["pockets"]]
      body = body.union(cq.Workplane("XY").add(labels))
   return body


def label_solid(k, floor_top):
   """The wrench size as raised text sitting on top of its slab."""
   cq = _cq()
   x, y = k["label"]
   return (cq.Workplane("XY", origin=(x, y, floor_top + k["slab_height"]))
           .text(str(k["size"]), LABEL_FONT, LABEL_H, kind="bold", halign="center", valign="center")
           .val())


def fillet_candidates(solid, rmax=FILLET_R, rmin=FILLET_MIN):
   """
   Every non-tangent edge above the base grid, paired with the radius it
   can take: rmax, reduced where a neighbouring face is too small to hold
   it, and dropped below rmin.
   """
   cq = _cq()
   from OCP.TopExp import TopExp
   from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
   from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
   amap = TopTools_IndexedDataMapOfShapeListOfShape()
   TopExp.MapShapesAndAncestors_s(solid.wrapped, TopAbs_EDGE, TopAbs_FACE, amap)
   extent = {}

   def min_extent(f):
      k = f.hashCode()
      if k not in extent:
         bb = f.BoundingBox()
         if f.geomType() == "CYLINDER":
            extent[k] = bb.zlen            # corner rounds: only their height limits a fillet
         else:
            dims = [d for d in (bb.xlen, bb.ylen, bb.zlen) if d > 1e-6]
            extent[k] = min(dims) if dims else 0
      return extent[k]

   top = solid.BoundingBox().zmax
   out = []
   for e in solid.Edges():
      if e.BoundingBox().zmin < BASE_H + 0.01:
         continue
      faces = [cq.Face(f) for f in amap.FindFromKey(e.wrapped)]
      if len(faces) != 2:
         continue
      mid = e.positionAt(0.5)
      n1, n2 = faces[0].normalAt(mid), faces[1].normalAt(mid)
      if abs(n1.dot(n2)) > 0.999:
         continue                         # smooth join, nothing to round
      r = min(rmax, 0.45 * min(min_extent(f) for f in faces))
      if r < rmin:
         continue
      # convex edges (outside corners) first, wall-top ones first of all, so the
      # visible edges are claimed before OCC runs out of patience on inside corners
      convex = not solid.isInside(mid + (n1 + n2).normalized() * 0.05, 1e-4)
      rank = 0 if mid.z > top - 0.01 else 1 if convex else 2
      out.append((rank, round(mid.z, 2), round(mid.x, 2), round(mid.y, 2), e, r))
   out.sort(key=lambda t: t[:4])
   return [(e, r) for *_, e, r in out]


def _try_fillet(solid, pairs):
   cq = _cq()
   from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
   mk = BRepFilletAPI_MakeFillet(solid.wrapped)
   for e, r in pairs:
      mk.Add(r, e.wrapped)
   try:
      mk.Build()
      if not mk.IsDone():
         return None
      res = cq.Shape.cast(mk.Shape())
      return res if res.isValid() else None
   except Exception:
      return None


def _fillet_greedy(solid, pairs, chunk=32):
   """Fillet as many of the edges as OCC will accept together; return (solid, rejected)."""
   res = _try_fillet(solid, pairs)
   if res is not None:
      return res, []
   kept, rejected = [], []

   def grow(part):
      nonlocal kept
      if _try_fillet(solid, kept + part) is not None:
         kept = kept + part
         return
      if len(part) == 1:
         rejected.append(part[0])
         return
      h = len(part) // 2
      grow(part[:h])
      grow(part[h:])

   for i in range(0, len(pairs), chunk):
      grow(pairs[i:i + chunk])
   return (_try_fillet(solid, kept) if kept else solid), rejected


def _fillet_worker(workdir, passes=1):
   """
   Runs in a subprocess: round every edge above the base grid of in.brep,
   writing passN.brep after each pass. OCC refuses some edge combinations
   and occasionally crashes outright, so the parent keeps whatever the last
   completed pass produced.
   """
   cq = _cq()
   solid = cq.Shape.importBrep(os.path.join(workdir, "in.brep"))
   log = open(os.path.join(workdir, "log.txt"), "a")
   n = 0
   for i in range(passes):
      pairs = fillet_candidates(solid)
      if not pairs:
         break
      solid, rejected = _fillet_greedy(solid, pairs)
      n += 1
      solid.exportBrep(os.path.join(workdir, f"pass{n}.brep"))
      log.write(f"fillet pass {n}: {len(pairs) - len(rejected)} edges rounded, {len(rejected)} refused\n")
      log.flush()
      if not rejected:
         return


def fillet_above_base(solid):
   """Round every edge above the base grid via the worker; report what stays sharp."""
   cq = _cq()
   workdir = tempfile.mkdtemp(prefix="wrench-fillet-")
   solid.exportBrep(os.path.join(workdir, "in.brep"))
   proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--fillet-worker", workdir],
                         capture_output=True, text=True)
   log_path = os.path.join(workdir, "log.txt")
   if os.path.exists(log_path):
      for line in open(log_path):
         print("   " + line.rstrip())
   if proc.returncode != 0:
      print(f"   fillet worker exited with {proc.returncode}; keeping the last completed pass")
   done = sorted(f for f in os.listdir(workdir) if f.startswith("pass"))
   if not done:
      print("   no fillet pass completed; tray left sharp")
      return solid
   result = cq.Shape.importBrep(os.path.join(workdir, done[-1]))
   if not result.isValid():
      raise RuntimeError("fillet produced an invalid solid")
   left = fillet_candidates(result)
   print(f"   {len(left)} edges above the base remain sharp")
   for e, r in left:
      a, b = e.startPoint(), e.endPoint()
      print(f"      ({a.x:.1f},{a.y:.1f},{a.z:.1f})-({b.x:.1f},{b.y:.1f},{b.z:.1f}) {e.Length():.1f} mm")
   return result


def preview(wp, path):
   cq = _cq()
   cq.exporters.export(wp, path, opt={
      "width": 1400, "height": 900, "marginLeft": 20, "marginTop": 20,
      "projectionDir": (0.6, -1.0, 0.9), "showAxes": False, "showHidden": False,
      "strokeWidth": 0.4,
   })


def build_all(plans, out_dir):
   cq = _cq()
   os.makedirs(out_dir, exist_ok=True)
   for stale in os.listdir(out_dir):
      if stale.endswith((".stl", ".svg")) or stale == "trays.md":
         os.remove(os.path.join(out_dir, stale))
   for p in plans:
      wp = build_tray(p)
      solid = wp.val()
      bb = solid.BoundingBox(tolerance=1e-6)
      ox, oy = p["outer"]
      ok = (solid.isValid() and len(wp.solids().vals()) == 1
            and abs(bb.xlen - ox) < 0.01 and abs(bb.ylen - oy) < 0.01
            and abs(bb.zlen - p["total_height"]) < 0.01)
      print(f"   {p['file']:36s} {bb.xlen:6.2f} x {bb.ylen:6.2f} x {bb.zlen:5.2f} mm  "
            f"{'ok' if ok else 'PROBLEM'}")
      if not ok:
         raise RuntimeError(f"{p['file']} failed geometry check")
      cq.exporters.export(wp, os.path.join(out_dir, p["file"]), tolerance=STL_TOL, angularTolerance=STL_ANG)
      preview(wp, os.path.join(out_dir, p["file"].replace(".stl", ".svg")))


# --------------------------------------------------------------------- main
def read_csv(path):
   ws = []
   with open(path, newline="") as f:
      for r in csv.DictReader(f):
         if not r["wrench"].strip() or r["wrench"].startswith("#"):
            continue
         ws.append(Wrench(int(r["wrench"]), float(r["length"]) * 10, float(r["handle_width"]),
                          float(r["max_width"]), float(r["height"]), float(r["handle_thickness"])))
   return ws


def main(argv=None):
   argv = sys.argv[1:] if argv is None else argv
   if argv[:1] == ["--fillet-worker"]:
      _fillet_worker(argv[1])
      return
   ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
   ap.add_argument("--force", action="store_true", help="rebuild even if output exists")
   ap.add_argument("--plan", action="store_true", help="print the plan only, no CAD")
   ap.add_argument("--csv", default=DEFAULT_CSV)
   ap.add_argument("--out", default=DEFAULT_OUT)
   args = ap.parse_args(argv)

   plans = plan_all(read_csv(args.csv))
   md = render_markdown(plans)
   print(md)
   if args.plan:
      return
   if os.path.exists(os.path.join(args.out, "trays.md")) and not args.force:
      print("already built, skipping (use --force to rebuild)")
      return
   build_all(plans, args.out)
   with open(os.path.join(args.out, "trays.md"), "w") as f:
      f.write(md)
   print(f"wrote {len(plans)} STLs, previews and trays.md to {args.out}")


if __name__ == "__main__":
   main()
