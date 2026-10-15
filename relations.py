"""
relations.py — the illus/2 constraint calculus, evaluated against an SVG and the spec it carries.

Every relation has the signature  rel(ctx, *args) -> (ok: bool, measured: str, expected: str)
and knows nothing about any subject: the subject lives in the spec's params/derived/model, which ctx exposes.
"""
import math, re
from textmetrics import text_width, text_box
import xml.etree.ElementTree as ET

SVG = "{http://www.w3.org/2000/svg}"
NUM = r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"

# ----------------------------------------------------------------------------- geometry helpers
def tag(el): return el.tag.replace(SVG, "")
def f(el, a, d=0.0):
    v = el.get(a); return float(v) if v not in (None, "") else d
def norm(v): return math.hypot(v[0], v[1])
def V(a, b): return (b[0] - a[0], b[1] - a[1])
def unit(v): n = norm(v); return (v[0] / n, v[1] / n) if n else (0.0, 0.0)
def dot(a, b): return a[0] * b[0] + a[1] * b[1]
def cross(a, b): return a[0] * b[1] - a[1] * b[0]
def dist_pt_seg(p, a, b):
    ab = V(a, b); ap = V(a, p); l2 = ab[0] ** 2 + ab[1] ** 2
    t = max(0.0, min(1.0, dot(ap, ab) / l2)) if l2 else 0.0
    return math.hypot(p[0] - a[0] - t * ab[0], p[1] - a[1] - t * ab[1])
def dist_pt_polyline(p, pts):
    return min(dist_pt_seg(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1)) if len(pts) > 1 else norm(V(p, pts[0]))
def inside_poly(p, poly, eps=1e-6):
    s = [cross(V(poly[i], poly[(i + 1) % len(poly)]), V(poly[i], p)) for i in range(len(poly))]
    return all(x > eps for x in s) or all(x < -eps for x in s)
def segs_intersect(a, b, c, d):
    def x2(o, p, q): return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    return x2(c, d, a) * x2(c, d, b) < 0 and x2(a, b, c) * x2(a, b, d) < 0

def arc_center(p0, p1, r, fa, fs):
    hx, hy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    r = max(r, math.hypot(hx, hy)); den = hx * hx + hy * hy
    k2 = (r * r * r * r - r * r * hy * hy - r * r * hx * hx) / (r * r * den) if den else 0.0
    k = math.sqrt(max(k2, 0.0)) * (1 if fa != fs else -1)
    return (k * hy + (p0[0] + p1[0]) / 2, -k * hx + (p0[1] + p1[1]) / 2), r

def parse_path(d):
    """Sample an SVG path into page points. M L H V Q C T S A Z, absolute and relative."""
    toks = re.findall(r"[MmLlHhVvQqCcTtSsAaZz]|" + NUM, d)
    pts, cur, start, cmd, i, last_ctrl = [], (0.0, 0.0), (0.0, 0.0), None, 0, None
    def num():
        nonlocal i; v = float(toks[i]); i += 1; return v
    while i < len(toks):
        if re.match(r"[A-Za-z]", toks[i]): cmd = toks[i]; i += 1
        rel, c = cmd.islower(), cmd.upper()
        if c == "Z":
            cur = start; pts.append(cur); continue
        if c == "M":
            x, y = num(), num(); cur = (cur[0] + x, cur[1] + y) if rel else (x, y); start = cur; pts.append(cur); cmd = "l" if rel else "L"; continue
        if c == "L":
            x, y = num(), num(); cur = (cur[0] + x, cur[1] + y) if rel else (x, y); pts.append(cur); continue
        if c == "H":
            x = num(); cur = (cur[0] + x if rel else x, cur[1]); pts.append(cur); continue
        if c == "V":
            y = num(); cur = (cur[0], cur[1] + y if rel else y); pts.append(cur); continue
        if c in ("Q", "T"):
            if c == "Q":
                cx, cy, x, y = num(), num(), num(), num()
                if rel: cx, cy, x, y = cur[0] + cx, cur[1] + cy, cur[0] + x, cur[1] + y
            else:
                x, y = num(), num()
                if rel: x, y = cur[0] + x, cur[1] + y
                cx, cy = (2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1]) if last_ctrl else cur
            p0 = cur
            for k in range(1, 81):
                s = k / 80; u = 1 - s
                pts.append((u * u * p0[0] + 2 * u * s * cx + s * s * x, u * u * p0[1] + 2 * u * s * cy + s * s * y))
            last_ctrl, cur = (cx, cy), (x, y); continue
        if c in ("C", "S"):
            if c == "C":
                x1, y1, x2, y2, x, y = (num() for _ in range(6))
                if rel: x1, y1, x2, y2, x, y = cur[0] + x1, cur[1] + y1, cur[0] + x2, cur[1] + y2, cur[0] + x, cur[1] + y
            else:
                x2, y2, x, y = (num() for _ in range(4))
                if rel: x2, y2, x, y = cur[0] + x2, cur[1] + y2, cur[0] + x, cur[1] + y
                x1, y1 = (2 * cur[0] - last_ctrl[0], 2 * cur[1] - last_ctrl[1]) if last_ctrl else cur
            p0 = cur
            for k in range(1, 81):
                s = k / 80; u = 1 - s
                pts.append((u**3 * p0[0] + 3 * u * u * s * x1 + 3 * u * s * s * x2 + s**3 * x,
                            u**3 * p0[1] + 3 * u * u * s * y1 + 3 * u * s * s * y2 + s**3 * y))
            last_ctrl, cur = (x2, y2), (x, y); continue
        if c == "A":
            rx, ry, rot, fa, fs, x, y = (num() for _ in range(7))
            if rel: x, y = cur[0] + x, cur[1] + y
            p0, p1 = cur, (x, y); c0, r = arc_center(p0, p1, max(rx, ry), int(fa), int(fs))
            a0 = math.atan2(p0[1] - c0[1], p0[0] - c0[0]); a1 = math.atan2(p1[1] - c0[1], p1[0] - c0[0]); da = a1 - a0
            if fs == 1 and da < 0: da += 2 * math.pi
            if fs == 0 and da > 0: da -= 2 * math.pi
            for k in range(1, 61):
                a = a0 + da * k / 60; pts.append((c0[0] + r * math.cos(a), c0[1] + r * math.sin(a)))
            cur = p1; continue
        raise ValueError(f"unsupported path command {cmd}")
    return pts

def shape_points(el):
    t = tag(el)
    if t == "path": return parse_path(el.get("d", ""))
    if t in ("polyline", "polygon"): return [tuple(map(float, m)) for m in re.findall(rf"({NUM})[\s,]+({NUM})", el.get("points", ""))]
    if t == "line": return [(f(el, "x1"), f(el, "y1")), (f(el, "x2"), f(el, "y2"))]
    if t == "rect":
        x, y, w, h = f(el, "x"), f(el, "y"), f(el, "width"), f(el, "height"); return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    if t == "circle":
        cx, cy, r = f(el, "cx"), f(el, "cy"), f(el, "r"); return [(cx + r, cy), (cx, cy + r), (cx - r, cy), (cx, cy - r), (cx + r, cy)]
    if t == "ellipse":
        cx, cy, rx, ry = f(el, "cx"), f(el, "cy"), f(el, "rx"), f(el, "ry"); return [(cx + rx, cy), (cx, cy + ry), (cx - rx, cy), (cx, cy - ry), (cx + rx, cy)]
    return []
SHAPES = ("path", "polyline", "polygon", "line", "rect", "circle", "ellipse")

# ----------------------------------------------------------------------------- the evaluation context
class Ctx:
    def __init__(self, root, spec, run_dir):
        self.root, self.spec, self.run_dir = root, spec, run_dir
        self.in_defs = set()
        for d_ in root.iter():
            if tag(d_) == "defs": self.in_defs.update(id(x) for x in d_.iter())
        vb = root.get("viewBox"); self.vb = [float(v) for v in vb.split()] if vb else None
        self.env = self._env()
        pr = (spec.get("projection") or {}).get("resolved") or {}
        self.scale = float(pr.get("scale", 0) or 0); self.origin = pr.get("origin") or [0, 0]
        self.scale_x = float(pr.get("scale_x") or self.scale or 0); self.scale_y = float(pr.get("scale_y") or self.scale or 0)
        self.cam = (spec.get("projection") or {}).get("resolved_camera")
        self.y_up = bool((spec.get("projection") or {}).get("y_up", True))
    # expressions
    def _env(self):
        env = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
        env.update({"rad": math.radians, "deg": math.degrees, "min": min, "max": max, "abs": abs, "sqrt": math.sqrt})
        for k, v in (self.spec.get("params") or {}).items():
            val = v.get("value") if isinstance(v, dict) else v
            if isinstance(val, (int, float)): env[k] = float(val)
        derived = self.spec.get("derived") or {}
        for _ in range(len(derived) + 1):               # resolve in dependency order
            for k, ex in derived.items():
                if k in env: continue
                try: env[k] = float(eval(str(ex), {"__builtins__": {}}, env))
                except Exception: pass
        return env
    def ev(self, expr, extra=None):
        env = dict(self.env)
        if extra: env.update(extra)
        if isinstance(expr, (int, float)): return float(expr)
        return eval(str(expr), {"__builtins__": {}}, env)
    def ev_with(self, overrides):
        """Re-evaluate params + derived with some params overridden (for minimality searches)."""
        saved = dict(self.env)
        env = {k: v for k, v in saved.items() if k not in (self.spec.get("derived") or {})}
        env.update(overrides)
        derived = self.spec.get("derived") or {}
        for _ in range(len(derived) + 1):
            for k, ex in derived.items():
                if k in env: continue
                try: env[k] = float(eval(str(ex), {"__builtins__": {}}, env))
                except Exception: pass
        return env
    # projection
    def W2P(self, x, y): return (self.origin[0] + self.scale_x * x, self.origin[1] - self.scale_y * y if self.y_up else self.origin[1] + self.scale_y * y)
    def P2W(self, px, py): return ((px - self.origin[0]) / self.scale_x, (self.origin[1] - py) / self.scale_y if self.y_up else (py - self.origin[1]) / self.scale_y)
    def P3(self, x, y, z):
        """Page point of a world point through the resolved cabinet camera."""
        import math as _m
        a = _m.radians(self.cam["alpha"]); k = self.cam["k"]
        return (self.origin[0] + self.scale * (x + k * z * _m.cos(a)), self.origin[1] - self.scale * (y + k * z * _m.sin(a)))
    # objects
    def group(self, oid):
        g = self.root.find(f".//*[@id='{oid}']")
        return g
    def shapes(self, oid):
        g = self.group(oid)
        return [el for el in (g.iter() if g is not None else []) if tag(el) in SHAPES and id(el) not in self.in_defs]
    def point(self, oid, name="centre"):
        """A named point: data-p-<name> on the group, else the natural point of its first shape."""
        g = self.group(oid)
        if g is None: return None
        v = g.get(f"data-p-{name}")
        if v: return tuple(float(t) for t in v.split(","))
        sh = self.shapes(oid)
        if not sh: return None
        s = sh[0]; t = tag(s)
        if t == "circle": return (f(s, "cx"), f(s, "cy"))
        if t == "line":
            if name == "start": return (f(s, "x1"), f(s, "y1"))
            if name in ("tip", "end"): return (f(s, "x2"), f(s, "y2"))
            return ((f(s, "x1") + f(s, "x2")) / 2, (f(s, "y1") + f(s, "y2")) / 2)
        pts = shape_points(s)
        if name == "start": return pts[0]
        if name in ("tip", "end"): return pts[-1]
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    def ref(self, r):
        """Resolve a point reference: 'obj', 'obj.point', 'mol:atom:3', 'mol:bond:2-3', or 'x,y' page."""
        if re.fullmatch(rf"{NUM},{NUM}", r): return tuple(float(t) for t in r.split(","))
        if ":atom:" in r:                      # mol:atom:<idx> or mol:atom:<element> (when unique)
            oid, _, key = r.split(":"); A = self.atoms(oid)
            if key.isdigit(): a = A.get(int(key)); return a["pos"] if a else None
            hits = [a for a in A.values() if a["el"] == key]; return hits[0]["pos"] if len(hits) == 1 else None
        if ":bond:" in r:                      # mol:bond:<i>-<j>, which must be a drawn bond
            oid, _, ij = r.split(":"); i, j = (int(t) for t in ij.split("-")); A = self.atoms(oid)
            if not any({b["i"], b["j"]} == {i, j} for b in self.bonds(oid)): return None
            return ((A[i]["pos"][0] + A[j]["pos"][0]) / 2, (A[i]["pos"][1] + A[j]["pos"][1]) / 2) if i in A and j in A else None
        if "." in r:
            oid, name = r.split(".", 1); return self.point(oid, name)
        return self.point(r)
    # chemistry
    def atoms(self, oid):
        g = self.group(oid); out = {}
        for el in (g.iter() if g is not None else []):
            if el.get("data-atom") is not None and el.get("data-idx") is not None:
                pos = el.get("data-pos")
                if pos: p = tuple(float(t) for t in pos.split(","))
                elif tag(el) == "circle": p = (f(el, "cx"), f(el, "cy"))
                else: p = (f(el, "x"), f(el, "y"))
                out[int(el.get("data-idx"))] = {"el": el.get("data-atom"), "pos": p, "charge": int(el.get("data-charge") or 0)}
        return out
    def bonds(self, oid):
        g = self.group(oid); out = []
        for el in (g.iter() if g is not None else []):
            b = el.get("data-bond")
            if b:
                i, j = (int(t) for t in b.split("-"))
                out.append({"i": i, "j": j, "order": int(el.get("data-order") or 1), "stereo": el.get("data-stereo") or "none"})
        return out
    def labels(self):
        lab = self.group("labels")
        return [t for t in (lab.iter() if lab is not None else []) if tag(t) == "text"]
    def label_box(self, t):
        x, y = f(t, "x"), f(t, "y"); fs_ = f(t, "font-size", 14.0); txt = "".join(t.itertext())
        w = text_width(txt, fs_); h = 1.1 * fs_; anc = t.get("text-anchor", "start")
        if (t.get("transform") or "").startswith("rotate"):          # rotated title: box turned 90°
            return (x - h / 2, y - w / 2, x + h / 2, y + w / 2)
        return text_box(x, y, txt, fs_, anc)

# ----------------------------------------------------------------------------- relations
def _pt_check(ctx, p, x_expr, y_expr, tol=1.5):
    ex = ctx.W2P(ctx.ev(x_expr), ctx.ev(y_expr)); err = norm(V(p, ex)) if p else None
    return (err is not None and err < tol), f"off by {err:.2f} px" if err is not None else "no point", f"({ex[0]:.1f}, {ex[1]:.1f}) px"

def point_at(ctx, obj, x_expr, y_expr, tol=1.5, point="centre"):
    return _pt_check(ctx, ctx.point(obj, point), x_expr, y_expr, float(tol))
def starts_at(ctx, obj, x_expr, y_expr, tol=1.5): return _pt_check(ctx, ctx.point(obj, "start"), x_expr, y_expr, float(tol))
def ends_at(ctx, obj, x_expr, y_expr, tol=1.5): return _pt_check(ctx, ctx.point(obj, "tip"), x_expr, y_expr, float(tol))

def on_curve(ctx, obj, curve_obj, tol=1.5):
    p = ctx.point(obj); pts = []
    for s in ctx.shapes(curve_obj): pts += shape_points(s)
    if not p or len(pts) < 2: return False, "missing point or curve", "point on curve"
    d = dist_pt_polyline(p, pts); return d < tol, f"{d:.2f} px from the curve", f"< {tol} px"

def direction(ctx, obj, angle_expr, tol=0.2):
    a, b = ctx.point(obj, "start"), ctx.point(obj, "tip")
    if not a or not b: return False, "no start/tip", "a line"
    ang = math.degrees(math.atan2(-(b[1] - a[1]) if ctx.y_up else (b[1] - a[1]), b[0] - a[0])); want = float(ctx.ev(angle_expr))
    d = abs((ang - want + 180) % 360 - 180); return d < tol, f"{ang:.2f}°", f"{want:g}°"

def length_px(ctx, obj, lo, hi):
    a, b = ctx.point(obj, "start"), ctx.point(obj, "tip"); L = norm(V(a, b)) if a and b else None
    return (L is not None and float(lo) <= L <= float(hi)), f"{L:.1f} px" if L else "no line", f"{lo}–{hi} px"

def _lines(ctx, obj, vertical):
    out = []
    for s in ctx.shapes(obj):
        t = tag(s)
        if t == "line":
            if vertical and abs(f(s, "x1") - f(s, "x2")) < 0.5: out.append((f(s, "x1"), abs(f(s, "y1") - f(s, "y2")), sorted((f(s, "y1"), f(s, "y2")))))
            if not vertical and abs(f(s, "y1") - f(s, "y2")) < 0.5: out.append((f(s, "y1"), abs(f(s, "x1") - f(s, "x2")), sorted((f(s, "x1"), f(s, "x2")))))
        if t == "rect":
            x, y, w, h = f(s, "x"), f(s, "y"), f(s, "width"), f(s, "height")
            if vertical: out += [(x, h, [y, y + h]), (x + w, h, [y, y + h])]
            else: out += [(y, w, [x, x + w]), (y + h, w, [x, x + w])]
    return out

def vertical_at(ctx, obj, x_expr, tol=1.0):
    want = ctx.W2P(ctx.ev(x_expr), 0)[0]; c = _lines(ctx, obj, True)
    if not c: return False, "no vertical line or rect edge", f"x = {want:.1f}"
    best = min(c, key=lambda e: abs(e[0] - want)); return abs(best[0] - want) < tol, f"x = {best[0]:.2f}", f"x = {want:.2f}"
def horizontal_at(ctx, obj, y_expr, tol=1.0):
    want = ctx.W2P(0, ctx.ev(y_expr))[1]; c = _lines(ctx, obj, False)
    if not c: return False, "no horizontal line or rect edge", f"y = {want:.1f}"
    best = max(c, key=lambda e: e[1]); return abs(best[0] - want) < tol, f"y = {best[0]:.2f}", f"y = {want:.2f}"
def spans_x(ctx, obj, x0_expr, x1_expr, tol=1.0):
    a, b = sorted((ctx.W2P(ctx.ev(x0_expr), 0)[0], ctx.W2P(ctx.ev(x1_expr), 0)[0])); c = _lines(ctx, obj, False)
    if not c: return False, "no horizontal line", f"spanning {a:.1f}–{b:.1f}"
    best = max(c, key=lambda e: e[1]); lo, hi = best[2]
    return lo <= a + tol and hi >= b - tol, f"spans {lo:.1f}–{hi:.1f}", f"at least {a:.1f}–{b:.1f}"
def spans_y(ctx, obj, y0_expr, y1_expr, tol=1.0):
    a, b = sorted((ctx.W2P(0, ctx.ev(y0_expr))[1], ctx.W2P(0, ctx.ev(y1_expr))[1])); c = _lines(ctx, obj, True)
    if not c: return False, "no vertical line", f"spanning {a:.1f}–{b:.1f}"
    best = max(c, key=lambda e: e[1]); lo, hi = best[2]
    return lo <= a + tol and hi >= b - tol, f"spans {lo:.1f}–{hi:.1f}", f"at least {a:.1f}–{b:.1f}"

def arc(ctx, obj, centre_obj, from_expr, to_expr, tol_deg=0.3):
    c_want = ctx.ref(centre_obj)
    paths = [s for s in ctx.shapes(obj) if tag(s) == "path" and re.search(r"[Aa]", s.get("d", ""))]
    if not paths or not c_want: return False, "no arc path or centre", "an A-command path centred on the vertex"
    nums = [float(n) for n in re.findall(NUM, paths[0].get("d"))]
    try: x0, y0, rx, ry, rot, fa, fs, x1, y1 = nums[:9]
    except Exception: return False, "arc not of the form M x y A r r 0 fa fs x y", "that form"
    c0, r = arc_center((x0, y0), (x1, y1), max(rx, ry), int(fa), int(fs))
    def ang(p): return math.degrees(math.atan2(-(p[1] - c0[1]) if ctx.y_up else (p[1] - c0[1]), p[0] - c0[0]))
    a0, a1 = ang((x0, y0)), ang((x1, y1)); w0, w1 = float(ctx.ev(from_expr)), float(ctx.ev(to_expr))
    ok = norm(V(c0, c_want)) < 1.0 and ((abs(a0 - w0) < tol_deg and abs(a1 - w1) < tol_deg) or (abs(a0 - w1) < tol_deg and abs(a1 - w0) < tol_deg))
    return ok, f"centre off by {norm(V(c0, c_want)):.2f} px, {a0:.1f}° → {a1:.1f}°, r = {r:.1f}", f"{w0:g}° → {w1:g}° about the vertex"

def perpendicular(ctx, a, b, tol=0.2):
    da, db = V(ctx.point(a, "start"), ctx.point(a, "tip")), V(ctx.point(b, "start"), ctx.point(b, "tip"))
    ang = math.degrees(math.acos(min(1, abs(dot(unit(da), unit(db)))))); return abs(ang - 90) < tol, f"{ang:.2f}°", "90°"
def parallel(ctx, a, b, tol=0.2):
    da, db = V(ctx.point(a, "start"), ctx.point(a, "tip")), V(ctx.point(b, "start"), ctx.point(b, "tip"))
    ang = math.degrees(math.asin(min(1, abs(cross(unit(da), unit(db)))))); return ang < tol, f"{ang:.2f}°", "0°"

def curve_follows(ctx, obj, tol=2.0):
    od = (ctx.spec.get("objects") or {}).get(obj) or {}
    pieces = od.get("pieces") or []
    drawn = []
    for s in ctx.shapes(obj): drawn += shape_points(s)
    if not pieces or len(drawn) < 2: return False, f"{len(pieces)} pieces in spec, {len(drawn)} drawn points", "pieces and a drawn curve"
    want = []
    for pc in pieces:
        t0, t1 = float(ctx.ev(pc["t"][0])), float(ctx.ev(pc["t"][1])); var = pc.get("var", "t")
        for k in range(301):
            t = t0 + (t1 - t0) * k / 300
            want.append(ctx.W2P(float(ctx.ev(pc["x"], {var: t})), float(ctx.ev(pc["y"], {var: t}))))
    d1 = max(dist_pt_polyline(p, want) for p in drawn); d2 = max(dist_pt_polyline(p, drawn) for p in want[::5])
    e0, e1 = norm(V(drawn[0], want[0])), norm(V(drawn[-1], want[-1]))
    ok = d1 < tol and d2 < tol and e0 < 1.5 and e1 < 1.5
    return ok, f"drawn→model {d1:.2f} px, model→drawn {d2:.2f} px, ends off {e0:.2f}/{e1:.2f} px", f"< {tol} px, ends < 1.5 px"

def inside(ctx, obj, region, tol=0.0):
    rs = ctx.shapes(region); poly = shape_points(rs[0]) if rs else []
    pts = []
    for s in ctx.shapes(obj): pts += shape_points(s)
    if len(poly) < 3 or not pts: return False, "missing region or object", "object inside region"
    out = sum(1 for p in pts if not inside_poly(p, poly)); return out == 0, f"{out} of {len(pts)} points outside", "0 outside"
def spans(ctx, obj, region_a, region_b):
    pts = []
    for s in ctx.shapes(obj): pts += shape_points(s)
    def touches(region):
        rs = ctx.shapes(region); poly = shape_points(rs[0]) if rs else []
        return len(poly) > 2 and (any(inside_poly(p, poly) for p in pts) or any(segs_intersect(pts[i], pts[i + 1], poly[j], poly[(j + 1) % len(poly)]) for i in range(len(pts) - 1) for j in range(len(poly))))
    ta, tb = touches(region_a), touches(region_b); return ta and tb, f"touches {region_a}: {ta}, {region_b}: {tb}", "both"

def feasible(ctx, *exprs):
    vals = [(e, bool(ctx.ev(e))) for e in exprs]; bad = [e for e, v in vals if not v]
    return not bad, f"false: {bad}" if bad else "all hold", "all hold"
def minimal(ctx, param, *exprs):
    p = (ctx.spec.get("params") or {}).get(param) or {}; dom = str(p.get("domain", "")); val = p.get("value")
    m = re.match(r"integers\s+(-?\d+)\.\.(-?\d+)", dom)
    if not m or not isinstance(val, (int, float)): return False, f"domain '{dom}', value {val}", "an integer domain and a found value"
    lo, hi = int(m.group(1)), int(m.group(2)); first = None
    for cand in range(lo, hi + 1):
        env = ctx.ev_with({param: float(cand)})
        try: ok = all(bool(eval(str(e), {"__builtins__": {}}, env)) for e in exprs)
        except Exception: ok = False
        if ok: first = cand; break
    return first is not None and abs(first - float(val)) < 1e-9, f"found {val}; first satisfying in {lo}..{hi} is {first}", "equal"
def infeasible_claim(ctx, param, *exprs):
    """The model claims no value of `param` in its domain satisfies the expressions; verify by search."""
    p = (ctx.spec.get("params") or {}).get(param) or {}; dom = str(p.get("domain", ""))
    m = re.match(r"integers\s+(-?\d+)\.\.(-?\d+)", dom)
    if not m: return False, f"domain '{dom}'", "an integer domain"
    lo, hi = int(m.group(1)), int(m.group(2)); hits = []
    for cand in range(lo, hi + 1):
        env = ctx.ev_with({param: float(cand)})
        try:
            if all(bool(eval(str(e), {"__builtins__": {}}, env)) for e in exprs): hits.append(cand)
        except Exception: pass
    return not hits, f"satisfying values: {hits[:5] or 'none'}", "none"

def molecule(ctx, obj, smiles):
    try:
        from rdkit import Chem
    except Exception as e:
        return False, f"rdkit unavailable: {e}", "rdkit"
    A, B = ctx.atoms(obj), ctx.bonds(obj)
    if not A or (len(A) > 1 and not B): return False, f"{len(A)} atoms, {len(B)} bonds found in {obj}", "atoms with data-atom/data-idx and bonds with data-bond"
    idx = sorted(A); order = {a: n + 1 for n, a in enumerate(idx)}
    s = ctx.scale or 40.0
    lines = ["", "  illus/2", "", f"{len(idx):3d}{len(B):3d}  0  0  0  0  0  0  0  0999 V2000"]
    for a in idx:
        x, y = A[a]["pos"]; lines.append(f"{x / s:10.4f}{-y / s:10.4f}{0.0:10.4f} {A[a]['el']:<3} 0  0  0  0  0  0  0  0  0  0  0  0")
    for b in B:
        st = {"wedge": 1, "hash": 6}.get(b["stereo"], 0)
        lines.append(f"{order[b['i']]:3d}{order[b['j']]:3d}{b['order']:3d}{st:3d}")
    chg = [(order[a], A[a]["charge"]) for a in idx if A[a]["charge"]]
    for n, c in chg: lines.append(f"M  CHG  1 {n:3d} {c:3d}")
    lines.append("M  END")
    try:
        mol = Chem.MolFromMolBlock("\n".join(lines), sanitize=True, removeHs=False)
        if mol is None: return False, "molblock from the drawing did not parse", "a valid molecule"
        Chem.AssignChiralTypesFromBondDirs(mol); Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
        drawn = Chem.MolToSmiles(Chem.RemoveHs(mol)); want = Chem.MolToSmiles(Chem.MolFromSmiles(smiles))
        cip = Chem.FindMolChiralCenters(mol, includeUnassigned=True, useLegacyImplementation=False)
        return drawn == want, f"drawn parses as {drawn}, centres {cip}", f"{want}"
    except Exception as e:
        return False, f"rdkit error: {e}", smiles

def graph(ctx, obj, edges):
    """edges: list of [from, to, kind]; drawn arrows carry data-edge='from->to' and data-kind."""
    want = {(e[0], e[1], e[2] if len(e) > 2 else "") for e in edges}
    g = ctx.group(obj); have = set()
    for el in (g.iter() if g is not None else []):
        e = el.get("data-edge")
        if e and "->" in e:
            a, b = e.split("->", 1); have.add((a.strip(), b.strip(), el.get("data-kind") or ""))
    return have == want, f"drawn edges {sorted(have)}", f"{sorted(want)}"

def arrow(ctx, obj, from_ref, to_ref, tol=14.0):
    a, b = ctx.point(obj, "start"), ctx.point(obj, "tip"); pa, pb = ctx.ref(from_ref), ctx.ref(to_ref)
    if not all((a, b, pa, pb)): return False, f"missing: start {a}, tip {b}, from {pa}, to {pb}", "all four points"
    da, db = norm(V(a, pa)), norm(V(b, pb))
    return da < tol and db < tol, f"start {da:.1f} px from {from_ref}, tip {db:.1f} px from {to_ref}", f"both < {tol:g} px"

def labels_clear(ctx, max_px=60.0):
    texts = ctx.labels(); boxes, far, hits = [], [], []
    segs, samples = [], []
    lab = ctx.group("labels"); lab_ids = {id(x) for x in (lab.iter() if lab is not None else [])}
    for el in ctx.root.iter():
        if id(el) in ctx.in_defs or tag(el) not in SHAPES or id(el) in lab_ids: continue
        if el.get("data-leader") or el.get("data-flow"): continue
        if tag(el) == "rect" and ctx.vb and f(el, "width") >= ctx.vb[2] - 1: continue
        pts = shape_points(el)
        if tag(el) in ("path", "polyline", "polygon"): samples += pts
        else: segs += [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    for t in texts:
        box = ctx.label_box(t); name = t.get("data-for") or "".join(t.itertext())[:10]
        try: ax, ay = (float(v) for v in t.get("data-anchor").split(","))
        except Exception: far.append(name + "(no anchor)"); continue
        cx_, cy_ = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        if norm((cx_ - ax, cy_ - ay)) > float(max_px): far.append(name)
        rect = [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])]
        def ins(p): return box[0] < p[0] < box[2] and box[1] < p[1] < box[3]
        if any(ins(a) or ins(b) or any(segs_intersect(a, b, rect[i], rect[(i + 1) % 4]) for i in range(4)) for a, b in segs): hits.append(name + "×line")
        if any(ins(p) for p in samples): hits.append(name + "×curve")
        for ob in boxes:
            if not (box[2] < ob[0] or ob[2] < box[0] or box[3] < ob[1] or ob[3] < box[1]): hits.append(name + "×label")
        boxes.append(box)
    return not far and not hits, f"{len(texts)} labels; far: {far or 'none'}; crossings: {hits or 'none'}", "none; none"

def labels_match_spec(ctx, tol_px=2.0):
    """Every label in spec.labels is drawn exactly once (data-for + text) and obeys its place rule:
    side = the 90° cone from the anchor its box centre lies in (above/below/left/right; 'rotated' = turned 90°),
    max_px = the disk around the anchor its box centre lies in. No drawn label is outside the spec."""
    want = ctx.spec.get("labels") or []; texts = ctx.labels(); problems = []; used = set()
    for L in want:
        says = L.get("says") if isinstance(L.get("says"), str) else None
        if says is None: continue   # computed captions (says as parts) are checked by their own relations
        hits = [t for t in texts if t.get("data-for") == L.get("for") and "".join(t.itertext()).strip() == says.strip()]
        if len(hits) != 1: problems.append(f"'{says}' for {L.get('for')}: drawn {len(hits)}×"); continue
        t = hits[0]; used.add(id(t)); place = L.get("place") or {}; side = place.get("side"); mx = place.get("max_px")
        box = ctx.label_box(t); cx_, cy_ = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        try: ax, ay = (float(v) for v in t.get("data-anchor").split(","))
        except Exception: problems.append(f"'{says}': no anchor"); continue
        rotated = (t.get("transform") or "").startswith("rotate"); dx, dy = cx_ - ax, cy_ - ay
        ok_side = {"above": -dy > abs(dx), "below": dy > abs(dx), "left": -dx > abs(dy), "right": dx > abs(dy), "rotated": rotated, None: True}.get(side, True)
        if not ok_side: problems.append(f"'{says}' not {side} its anchor")
        if mx is not None and norm((cx_ - ax, cy_ - ay)) > float(mx) + float(tol_px): problems.append(f"'{says}' {norm((cx_ - ax, cy_ - ay)):.0f} px from its anchor > {mx}")
    extra = [("".join(t.itertext()).strip()) for t in texts if id(t) not in used and any(isinstance(L.get("says"), str) for L in want)]
    extra = [e for e in extra if e not in {("".join(t.itertext()).strip()) for t in texts if id(t) in used}]
    if extra and all(isinstance(L.get("says"), str) for L in want): problems.append(f"drawn but not in the spec: {extra}")
    return not problems, f"{len(want)} spec labels; {problems or 'all drawn as specified'}", "each drawn once, on its side, within max_px"

def vessels_clear(ctx, obj, gap_px=10.0, end_px=24.0):
    """Distinct edges of a graph group (paths with data-edge) keep gap_px between their centrelines and never cross,
    except within end_px of their own ends, where they converge on the organs they join."""
    g = ctx.group(obj)
    paths = [el for el in (g.iter() if g is not None else []) if el.get("data-edge")]
    polys = []
    for el in paths:
        pts = shape_points(el)
        if len(pts) < 2: continue
        L = [0.0]
        for i in range(1, len(pts)): L.append(L[-1] + norm(V(pts[i - 1], pts[i])))
        inner = [p for p, s in zip(pts, L) if end_px <= s <= L[-1] - end_px]   # away from both ends
        polys.append((el.get("data-edge"), pts, inner))
    bad = []; worst = None
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            na, pa, ia = polys[i]; nb, pb, ib = polys[j]
            if len(ia) < 2 or len(ib) < 2: continue
            d = min([dist_pt_polyline(p, ib) for p in ia] + [dist_pt_polyline(p, ia) for p in ib] + [1e9])
            if any(segs_intersect(ia[k], ia[k + 1], ib[m], ib[m + 1]) for k in range(len(ia) - 1) for m in range(len(ib) - 1)): d = 0.0
            if worst is None or d < worst[0]: worst = (d, na, nb)
            if d < float(gap_px): bad.append(f"{na} / {nb}: {d:.1f} px")
    return not bad, f"{len(polys)} edges; closest pair {worst[1]} / {worst[2]} at {worst[0]:.1f} px" if worst else "fewer than two edges", f"every pair ≥ {gap_px:g} px apart away from their ends"

def anchors_apart(ctx, symbol_obj, k=2.0):
    """A symbol's anchors that vessels attach to are at least k × the attached vessel width apart from each other,
    so that converging vessels stay distinguishable up to the organ (the ends vessels_clear deliberately ignores)."""
    g = ctx.group(symbol_obj)
    if g is None: return False, f"no group {symbol_obj}", "a symbol group"
    anchors = {a[7:]: tuple(float(v) for v in val.split(",")) for a, val in g.attrib.items() if a.startswith("data-p-") and a != "data-p-centre"}
    used = {}   # anchor name -> widest vessel attached there
    for el in ctx.root.iter():
        if not el.get("data-edge"): continue
        grp = el; parent = {c: p for p in ctx.root.iter() for c in p}
        while grp is not None and not grp.get("data-p-start"): grp = parent.get(grp)
        if grp is None: continue
        w = f(el, "stroke-width", 1.0)
        for end in ("start", "tip"):
            p = tuple(float(v) for v in grp.get(f"data-p-{end}").split(","))
            for name, a in anchors.items():
                if norm(V(p, a)) < 1.5: used[name] = max(used.get(name, 0.0), w)
    names = sorted(used); worst = None
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            d = norm(V(anchors[names[i]], anchors[names[j]])); need = float(k) * max(used[names[i]], used[names[j]])
            if worst is None or d - need < worst[0] - worst[3]: worst = (d, names[i], names[j], need)
    if worst is None: return True, f"{len(used)} anchors in use; no pair to compare", "pairs ≥ k × vessel width apart"
    return worst[0] >= worst[3], f"{len(used)} anchors in use; closest pair {worst[1]}–{worst[2]} {worst[0]:.1f} px apart, need ≥ {worst[3]:.1f} ({k:g} × {worst[3] / float(k):g} px vessels)", f"every used pair ≥ {k:g} × attached vessel width"

def in_frame(ctx, margin_px=12.0):
    vb = ctx.vb
    if not vb: return False, "no viewBox", "a viewBox"
    pts = []
    for el in ctx.root.iter():
        if id(el) in ctx.in_defs or tag(el) not in SHAPES: continue
        if tag(el) == "rect" and f(el, "width") >= vb[2] - 1: continue
        pts += shape_points(el)
    for t in ctx.labels():
        b = ctx.label_box(t); pts += [(b[0], b[1]), (b[2], b[3])]
    m = float(margin_px); out = [p for p in pts if not (vb[0] + m <= p[0] <= vb[2] - m and vb[1] + m <= p[1] <= vb[3] - m)]
    return not out, f"{len(pts)} points, {len(out)} outside the {m:g} px margin", "0 outside"

def uniform_scale(ctx):
    pr = (ctx.spec.get("projection") or {}).get("resolved") or {}
    ok = (isinstance(pr.get("scale"), (int, float)) and pr.get("scale") > 0 or (pr.get("scale_x") and pr.get("scale_y"))) and isinstance(pr.get("origin"), list)
    return ok, f"resolved scale {pr.get('scale') or (pr.get('scale_x'), pr.get('scale_y'))}, origin {pr.get('origin')}", "one positive scale (or a plot's two) and an origin"

def ids_present(ctx):
    """An object id ending in '_' names a set: at least one group with that prefix must exist."""
    def present(k):
        if k.endswith("_"): return any((el.get("id") or "").startswith(k) and tag(el) == "g" for el in ctx.root.iter())
        return ctx.group(k) is not None
    missing = [k for k in (ctx.spec.get("objects") or {}) if not present(k)]
    return not missing and ctx.group("labels") is not None, f"missing groups: {missing or 'none'}; labels group: {ctx.group('labels') is not None}", "none; present"

def portable_text(ctx):
    bad = []
    for t in ctx.root.iter():
        if tag(t) in ("text", "tspan"):
            fs_ = t.get("font-size", "")
            if "%" in fs_ or "em" in fs_: bad.append(f"{t.get('data-for') or tag(t)}: font-size {fs_}")
            if t.get("baseline-shift"): bad.append(f"{t.get('data-for') or tag(t)}: baseline-shift")
            if tag(t) == "tspan" and t.text and t.text.startswith(" "): bad.append("tspan starting with a space")
    return not bad, f"{bad or 'none'}", "none"

def no_transforms(ctx):
    tr = [el.get("id") or tag(el) for el in ctx.root.iter() if el.get("transform") and id(el) not in ctx.in_defs and not (tag(el) == "text" and el.get("transform", "").startswith("rotate"))]
    rel = [el.get("id") or "path" for el in ctx.root.iter() if tag(el) == "path" and id(el) not in ctx.in_defs and re.search(r"[a-y]", re.sub(r"[eE]", "", el.get("d", "")))]
    return not tr and not rel, f"transforms: {tr or 'none'}; relative path commands: {rel or 'none'}", "none"

def left_of(ctx, a, b, gap_px=0.0):
    pa, pb = ctx.point(a), ctx.point(b)
    if not pa or not pb: return False, "missing centre", "both centres"
    return pa[0] + float(gap_px) < pb[0], f"{a} at x={pa[0]:.1f}, {b} at x={pb[0]:.1f}", f"{a} left of {b}" + (f" by ≥ {gap_px} px" if gap_px else "")

def uniform_bonds(ctx, obj, tol=0.06):
    A, B = ctx.atoms(obj), ctx.bonds(obj)
    if not B: return False, "no bonds", "bonds"
    Ls = sorted(norm(V(A[b["i"]]["pos"], A[b["j"]]["pos"])) for b in B if b["i"] in A and b["j"] in A)
    med = Ls[len(Ls) // 2]; worst = max(abs(L - med) / med for L in Ls)
    return worst <= float(tol), f"bond lengths {min(Ls):.1f}–{max(Ls):.1f} px, worst deviation {worst * 100:.1f}%", f"≤ {float(tol) * 100:g}% of the median"

def _world3(ctx, oid):
    g = ctx.group(oid); v = g.get("data-world") if g is not None else None
    return tuple(float(t) for t in v.split(",")) if v else None
def inside_box(ctx, prefix, box_obj, margin_px=0.0):
    """Every object whose id starts with prefix lies inside the box's declared volume (world coordinates)."""
    g = ctx.group(box_obj); bx = g.get("data-box") if g is not None else None
    if not bx: return False, f"{box_obj} carries no data-box", "a box with data-box"
    x0, y0, z0, x1, y1, z1 = (float(t) for t in bx.split(","))
    ids = [el.get("id") for el in ctx.root.iter() if (el.get("id") or "").startswith(prefix) and el.get("data-world")]
    m = float(margin_px) / (ctx.scale or 1)
    out = [i for i in ids if not (x0 + m <= _world3(ctx, i)[0] <= x1 - m and y0 + m <= _world3(ctx, i)[1] <= y1 - m and z0 + m <= _world3(ctx, i)[2] <= z1 - m)]
    return bool(ids) and not out, f"{len(ids)} objects; outside: {out or 'none'}", "all inside"
def projected(ctx, prefix, tol=1.0):
    """Every object with data-world sits on the page where the resolved camera puts it."""
    if not ctx.cam: return False, "no resolved camera", "projection.resolved_camera"
    ids = [el.get("id") for el in ctx.root.iter() if (el.get("id") or "").startswith(prefix) and el.get("data-world")]
    errs = {i: norm(V(ctx.point(i), ctx.P3(*_world3(ctx, i)))) for i in ids}
    bad = [i for i, e in errs.items() if e > float(tol)]
    return bool(ids) and not bad, f"{len(ids)} objects; max error {max(errs.values()) if errs else 0:.2f} px; off: {bad or 'none'}", f"all within {tol} px of the camera's projection"
def no_overlap(ctx, prefix, min_gap_px=0.0):
    cs = []
    for el in ctx.root.iter():
        if (el.get("id") or "").startswith(prefix):
            c = [s for s in el.iter() if tag(s) == "circle"]
            if c: cs.append((el.get("id"), f(c[0], "cx"), f(c[0], "cy"), f(c[0], "r")))
    bad = [(a[0], b[0]) for i, a in enumerate(cs) for b in cs[i + 1:] if math.hypot(a[1] - b[1], a[2] - b[2]) < a[3] + b[3] + float(min_gap_px)]
    return bool(cs) and not bad, f"{len(cs)} circles; overlapping pairs: {bad[:4] or 'none'}", "none"
def starts_on(ctx, prefix_a, prefix_b, tol=1.5):
    """Each object a = prefix_a + k starts at the centre of b = prefix_b + k."""
    ids = [el.get("id") for el in ctx.root.iter() if (el.get("id") or "").startswith(prefix_a)]
    bad = []
    for i in ids:
        k = i[len(prefix_a):]; j = prefix_b + k
        a, b = ctx.point(i, "start"), ctx.point(j)
        if not a or not b or norm(V(a, b)) > float(tol): bad.append(i)
    return bool(ids) and not bad, f"{len(ids)} objects; not starting on their partner: {bad or 'none'}", "none"
def count(ctx, prefix, n):
    ids = [el.get("id") for el in ctx.root.iter() if (el.get("id") or "").startswith(prefix) and tag(el) == "g"]
    return len(ids) == int(n), f"{len(ids)} groups with prefix {prefix}", f"{n}"
def above(ctx, a, b, gap_px=0.0):
    pa, pb = ctx.point(a), ctx.point(b)
    if not pa or not pb: return False, "missing centre", "both centres"
    return pa[1] + float(gap_px) < pb[1], f"{a} at y={pa[1]:.1f}, {b} at y={pb[1]:.1f}", f"{a} above {b}"
def hidden_edges_dashed(ctx, box_obj):
    """Re-derive which box edges the camera hides; those and only those are dashed."""
    g = ctx.group(box_obj); bx = g.get("data-box") if g is not None else None
    if not bx or not ctx.cam: return False, "no data-box or camera", "both"
    import math as _m
    a = _m.radians(ctx.cam["alpha"]); k = ctx.cam["k"]; d = (-k * _m.cos(a), -k * _m.sin(a), 1.0)
    x0, y0, z0, x1, y1, z1 = (float(t) for t in bx.split(","))
    Vx = {"A": (x0, y0, z0), "B": (x1, y0, z0), "C": (x1, y1, z0), "D": (x0, y1, z0), "E": (x0, y0, z1), "F": (x1, y0, z1), "G": (x1, y1, z1), "H": (x0, y1, z1)}
    faces = {"front": ("ABCD", (0, 0, -1)), "back": ("EFGH", (0, 0, 1)), "bottom": ("ABFE", (0, -1, 0)), "top": ("DCGH", (0, 1, 0)), "left": ("ADHE", (-1, 0, 0)), "right": ("BCGF", (1, 0, 0))}
    vis = {n: sum(p * q for p, q in zip(fn, d)) < 0 for n, (_, fn) in faces.items()}
    bad = []
    for el in g.iter():
        e = el.get("data-edge-3d")
        if not e: continue
        fs = [n for n, (vs, _) in faces.items() if e[0] in vs and e[1] in vs]
        hidden = not any(vis[n] for n in fs); dashed = el.get("stroke-dasharray") is not None
        if hidden != dashed: bad.append(e)
    n_edges = sum(1 for el in g.iter() if el.get("data-edge-3d"))
    return n_edges == 12 and not bad, f"{n_edges} edges; hidden/dashed mismatches: {bad or 'none'}", "12 edges, no mismatch"

RELATIONS = {k: v for k, v in globals().items() if callable(v) and not k.startswith("_") and k not in
             ("Ctx", "tag", "f", "norm", "V", "unit", "dot", "cross", "dist_pt_seg", "dist_pt_polyline", "inside_poly", "segs_intersect",
              "arc_center", "parse_path", "shape_points")}
