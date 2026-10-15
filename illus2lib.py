"""
illus2lib — the standard library of illus/2. A generator composes these calls from the spec; the library handles the
artifact rules (ids, data attributes, metadata, fit, label placement) so that a generator is short and declarative.

    from illus2lib import Scene
    S = Scene("spec.json")                      # loads the spec, evaluates params/derived, searches free params
    S.molecule("reactant", "C[C@@H](Br)CC", at=(170, 180))
    S.arrow("reaction_arrow", start=(400, 180), tip=(500, 180), edge=("reactant", "product", "reaction"))
    S.curly("curly_1", start="nucleophile:atom:1", tip="reactant:atom:2", bulge=-40)
    S.text_mark("plus_left", "+", at=(260, 180))
    S.label("reactant", "(R)-2-bromobutane", side="below")
    S.write()                                   # resolves the fit, writes spec.json back and scene.svg

World-unit scenes (physics): S.fit_world(xs, ys, hold="floor at bottom") first, then S.W2P(x, y) for page points,
S.curve("trajectory", pieces=spec pieces), S.point("ball_t0", world=(0, "h0"), r=7), S.vector(...), S.angle_mark(...).
"""
import json, math, html, re
from textmetrics import text_width, text_box

def _env(params, derived):
    env = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    env.update({"rad": math.radians, "deg": math.degrees, "min": min, "max": max, "abs": abs})
    for k, v in params.items():
        val = v.get("value") if isinstance(v, dict) else v
        if isinstance(val, (int, float)): env[k] = float(val)
    for _ in range(len(derived) + 1):
        for k, ex in derived.items():
            if k not in env:
                try: env[k] = float(eval(str(ex), {"__builtins__": {}}, env))
                except Exception: pass
    return env

class Scene:
    def __init__(self, spec_path="spec.json", font="Inter, Arial, sans-serif"):
        self.spec_path = spec_path; self.spec = json.load(open(spec_path)); self.font = font
        self.groups = []            # (id, svg string) in paint order
        self.labels = []            # pending labels
        self.points = {}            # "obj" -> {"centre": (x,y), "start":..., "tip":...}
        self.atoms = {}             # mol id -> {idx: (x,y)}
        self.bonds = {}             # mol id -> [(i, j)]
        self.obstacles = []         # segments and sampled points, for label placement
        self.defs = ['<marker id="arrow" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#111"/></marker>',
                     '<marker id="arrow-red" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#c33"/></marker>']
        self.search_free_params(); self.env = _env(self.spec.get("params", {}), self.spec.get("derived", {}))
        pj = self.spec.setdefault("projection", {}); fit = pj.get("fit", {}); fr = fit.get("frame", [960, 540])
        self.W, self.H = fr[0], fr[1]; self.margin = fit.get("margin_px", 30)
        self.scale, self.origin = None, None; self.scale_x = self.scale_y = None; self.cam = None; self._frame = None
    # ---------------------------------------------------------------- params
    def ev(self, ex, **kw):
        if isinstance(ex, (int, float)): return float(ex)
        return float(eval(str(ex), {"__builtins__": {}}, {**self.env, **kw}))
    def search_free_params(self):
        P = self.spec.get("params", {}); D = self.spec.get("derived", {})
        feas = [a for c in self.spec.get("constraints", []) if c.get("rel") == "feasible" for a in c.get("args", [])]
        for name, p in P.items():
            if isinstance(p, dict) and p.get("value") == "search":
                m = re.match(r"integers\s+(-?\d+)\.\.(-?\d+)", str(p.get("domain", "")))
                lo, hi = (int(m.group(1)), int(m.group(2))) if m else (1, 100)
                for cand in range(lo, hi + 1):
                    env = _env({**P, name: {"value": cand}}, D)
                    try: ok = all(bool(eval(str(e), {"__builtins__": {}}, env)) for e in feas)
                    except Exception: ok = False
                    if ok: p["value"] = cand; break
    # ---------------------------------------------------------------- projection
    def fit_world(self, xs, ys, hold="floor at bottom", pad=0.0):
        """World bbox -> one scale; floor (y = 0) held at the bottom margin, or centred."""
        x0, x1 = min(xs) - pad, max(xs) + pad; y0, y1 = min(ys) - pad, max(ys) + pad
        s_max = self.spec["projection"].get("px_per_unit_max", 300)
        s = min(s_max, (self.W - 2 * self.margin) / (x1 - x0), (self.H - 2 * self.margin - 40) / (y1 - y0))
        ox = self.margin - s * x0 + ((self.W - 2 * self.margin) - s * (x1 - x0)) / 2
        oy = self.H - self.margin if "bottom" in hold else self.H / 2 + s * (y0 + y1) / 2
        self.scale, self.origin = s, (ox, oy); return s
    def set_page_scale(self, px_per_unit, origin=None):
        self.scale = px_per_unit; self.origin = origin or (0.0, self.H / 2)
    def W2P(self, x, y):
        sx, sy = (self.scale_x or self.scale), (self.scale_y or self.scale)
        return (self.origin[0] + sx * self.ev(x), self.origin[1] - sy * self.ev(y))
    def set_plot(self, x_range, y_range, plot_box=None):
        """A plot projection: data space -> page with separate x and y scales; plot_box = (x0, y0, x1, y1) page px."""
        x0, y0, x1, y1 = plot_box or (self.margin + 60, self.margin + 10, self.W - self.margin, self.H - self.margin - 40)
        self.scale_x = (x1 - x0) / (x_range[1] - x_range[0]); self.scale_y = (y1 - y0) / (y_range[1] - y_range[0])
        self.scale = None; self.origin = (x0 - self.scale_x * x_range[0], y1 + self.scale_y * y_range[0])
        self.plot_ranges = (x_range, y_range)
    def axes(self, x_id="x_axis", y_id="y_axis", colour="#e0302a", width=1.6, overshoot_px=14):
        (xr, yr) = self.plot_ranges
        o = self.W2P(xr[0], yr[0]); xe = self.W2P(xr[1], yr[0]); ye = self.W2P(xr[0], yr[1])
        xe = (xe[0] + overshoot_px, xe[1]); ye = (ye[0], ye[1] - overshoot_px)
        self.defs.append(f'<marker id="axis-arrow" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="{colour}"/></marker>')
        self._add(x_id, f'<line x1="{o[0]:.2f}" y1="{o[1]:.2f}" x2="{xe[0]:.2f}" y2="{xe[1]:.2f}" stroke="{colour}" stroke-width="{width}" marker-end="url(#axis-arrow)"/>', pts={"start": o, "tip": xe, "centre": ((o[0] + xe[0]) / 2, o[1])}, obstacles=[(o, xe)])
        self._add(y_id, f'<line x1="{o[0]:.2f}" y1="{o[1]:.2f}" x2="{ye[0]:.2f}" y2="{ye[1]:.2f}" stroke="{colour}" stroke-width="{width}" marker-end="url(#axis-arrow)"/>', pts={"start": o, "tip": ye, "centre": (o[0], (o[1] + ye[1]) / 2)}, obstacles=[(o, ye)])
    def axis_title(self, for_id, text, rotate=False, font_size=13, colour="#222"):
        """A plot axis title: horizontal under the x axis, or rotated along the y axis (a rotated <text> is allowed)."""
        p = self.points[for_id]
        if rotate:
            self.labels.append((for_id, text, "rotated", p["centre"], 60, font_size, colour))
        else:
            self.labels.append((for_id, text, "below", (p["centre"][0], p["centre"][1]), 60, font_size, colour))
    def annotation(self, id_, text, tip_world, from_page, colour="#2b7bd6", font_size=12):
        """An annotation: a short label at from_page with an arrow to the world point."""
        b = self.W2P(*tip_world); a = (float(from_page[0]), float(from_page[1]))
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1; u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L); b2 = (b[0] - u[0] * 7, b[1] - u[1] * 7)
        self._add(id_, f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b2[0]:.2f}" y2="{b2[1]:.2f}" stroke="{colour}" stroke-width="1.4" marker-end="url(#arrow-blue)"/>', pts={"start": a, "tip": b2, "centre": ((a[0] + b2[0]) / 2, (a[1] + b2[1]) / 2)}, obstacles=[(a, b2)])
        self.defs.append(f'<marker id="arrow-blue" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="{colour}"/></marker>')
        self.labels.append((id_, text, "above", a, 60, font_size, colour))
    # ---------------------------------------------------------------- 3D (cabinet projection)
    def set_camera_cabinet(self, alpha_deg=45, k=0.5, px_per_unit=180, origin=None):
        self.cam = {"type": "cabinet", "alpha": alpha_deg, "k": k}; self.scale = px_per_unit
        self.origin = origin or (self.W / 2 - px_per_unit * 0.6, self.H / 2 + px_per_unit * 0.55)
    def P3(self, x, y, z):
        a = math.radians(self.cam["alpha"]); k = self.cam["k"]
        return (self.origin[0] + self.scale * (x + k * z * math.cos(a)), self.origin[1] - self.scale * (y + k * z * math.sin(a)))
    def box3d(self, oid, origin3=(0, 0, 0), size3=(1, 1, 1), face_fill="#bfe3f7", face_opacity=0.45, edge="#2a8fd0"):
        """A transparent box; faces as polygons, edges as lines; hidden edges dashed and marked data-hidden."""
        x0, y0, z0 = origin3; x1, y1, z1 = x0 + size3[0], y0 + size3[1], z0 + size3[2]
        V = {"A": (x0, y0, z0), "B": (x1, y0, z0), "C": (x1, y1, z0), "D": (x0, y1, z0), "E": (x0, y0, z1), "F": (x1, y0, z1), "G": (x1, y1, z1), "H": (x0, y1, z1)}
        faces = {"front": (["A", "B", "C", "D"], (0, 0, -1)), "back": (["E", "F", "G", "H"], (0, 0, 1)), "bottom": (["A", "B", "F", "E"], (0, -1, 0)),
                 "top": (["D", "C", "G", "H"], (0, 1, 0)), "left": (["A", "D", "H", "E"], (-1, 0, 0)), "right": (["B", "C", "G", "F"], (1, 0, 0))}
        a = math.radians(self.cam["alpha"]); k = self.cam["k"]; d = (-k * math.cos(a), -k * math.sin(a), 1.0)
        vis = {n: (f[1][0] * d[0] + f[1][1] * d[1] + f[1][2] * d[2]) < 0 for n, f in faces.items()}
        edges = [("A", "B"), ("B", "C"), ("C", "D"), ("D", "A"), ("E", "F"), ("F", "G"), ("G", "H"), ("H", "E"), ("A", "E"), ("B", "F"), ("C", "G"), ("D", "H")]
        out, obst = [], []
        for n in ("back", "bottom", "left", "right", "top", "front"):
            if vis[n] or n == "back":   # paint far faces first; the box is transparent so all faces show faintly
                pts = [self.P3(*V[v]) for v in faces[n][0]]
                out.append(f'<polygon data-face="{n}" points="{" ".join(f"{p[0]:.2f},{p[1]:.2f}" for p in pts)}" fill="{face_fill}" fill-opacity="{face_opacity if vis[n] else face_opacity * 0.5}" stroke="none"/>')
        for e in edges:
            fs = [n for n, f in faces.items() if e[0] in f[0] and e[1] in f[0]]
            hidden = not any(vis[n] for n in fs)
            p, q = self.P3(*V[e[0]]), self.P3(*V[e[1]])
            dash = ' stroke-dasharray="5 4" data-hidden="1"' if hidden else ''
            out.append(f'<line data-edge-3d="{e[0]}{e[1]}" x1="{p[0]:.2f}" y1="{p[1]:.2f}" x2="{q[0]:.2f}" y2="{q[1]:.2f}" stroke="{edge}" stroke-width="1.4"{dash}/>')
            obst.append((p, q))
        c = self.P3((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
        g = f'<g id="{oid}" data-box="{x0},{y0},{z0},{x1},{y1},{z1}" data-p-centre="{c[0]:.2f},{c[1]:.2f}" data-p-top="{self.P3((x0 + x1) / 2, y1, z0)[0]:.2f},{self.P3((x0 + x1) / 2, y1, z0)[1]:.2f}">' + "".join(out) + "</g>"
        self.groups.append((oid, g)); self.points[oid] = {"centre": c, "top": self.P3((x0 + x1) / 2, y1, z0)}; self.obstacles += obst
        self.bbox = getattr(self, "bbox", {}); self.bbox[oid] = (min(p[0] for q in obst for p in q), min(p[1] for q in obst for p in q), max(p[0] for q in obst for p in q), max(p[1] for q in obst for p in q))
        self.spec["projection"]["resolved_camera"] = dict(self.cam)
    def sphere3d(self, oid, world3, r_px=7, fill="#f2c230", stroke="#8a6a00"):
        p = self.P3(*world3)
        self._add(oid, f'<circle cx="{p[0]:.2f}" cy="{p[1]:.2f}" r="{r_px}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>', pts={"centre": p})
        self.groups[-1] = (oid, self.groups[-1][1].replace(f'<g id="{oid}"', f'<g id="{oid}" data-world="{world3[0]:.4f},{world3[1]:.4f},{world3[2]:.4f}"', 1))
    def vector3d(self, oid, from_world3, dir3, length_px, colour="#222", width=1.3):
        a = self.P3(*from_world3); n = math.sqrt(sum(c * c for c in dir3)) or 1
        d2 = self.P3(from_world3[0] + dir3[0] / n, from_world3[1] + dir3[1] / n, from_world3[2] + dir3[2] / n)
        L = math.hypot(d2[0] - a[0], d2[1] - a[1]) or 1; u = ((d2[0] - a[0]) / L, (d2[1] - a[1]) / L); b = (a[0] + u[0] * length_px, a[1] + u[1] * length_px)
        self.defs.append(f'<marker id="arrow-dark" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="{colour}"/></marker>')
        self._add(oid, f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="{colour}" stroke-width="{width}" marker-end="url(#arrow-dark)"/>', pts={"start": a, "tip": b, "centre": ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)}, obstacles=[(a, b)])
    # ---------------------------------------------------------------- symbols with anchors (flat icons)
    ANCHOR_SPACING_AT_90 = {"heart": 11.3, "lungs": 24.0, "body": 30.0}   # closest pair of vessel anchors at size 90
    @classmethod
    def min_symbol_size(cls, kind, vessel_width, k=2.0):
        """The smallest size at which the symbol's closest vessel anchors are k × vessel_width apart (rule anchors_apart)."""
        return math.ceil(90.0 * k * vessel_width / cls.ANCHOR_SPACING_AT_90[kind])
    def symbol(self, oid, kind, at, size=90):
        """Flat icon with named anchor points: 'lungs' (hilum_l, hilum_r, top, bottom), 'heart' (ra, rv_out, la, lv_out, top, bottom), 'body' (top, bottom, left, right)."""
        cx, cy = float(at[0]), float(at[1]); s = size / 90.0; pts = {"centre": (cx, cy)}
        if kind == "lungs":
            w, h = 36 * s, 62 * s
            body = (f'<rect x="{cx - 5 * s:.1f}" y="{cy - h / 2 - 16 * s:.1f}" width="{10 * s:.1f}" height="{26 * s:.1f}" rx="{4 * s:.1f}" fill="#e38b88" stroke="#b55a57" stroke-width="1.2"/>'
                    f'<path d="M {cx - 8 * s:.1f} {cy - h / 2 + 6 * s:.1f} C {cx - 8 * s:.1f} {cy - h / 2 - 2 * s:.1f} {cx - 10 * s - w:.1f} {cy - h / 2 + 4 * s:.1f} {cx - 10 * s - w:.1f} {cy + 8 * s:.1f} C {cx - 10 * s - w:.1f} {cy + h / 2:.1f} {cx - 8 * s:.1f} {cy + h / 2 + 2 * s:.1f} {cx - 8 * s:.1f} {cy + 2 * s:.1f} Z" fill="#f08a8a" stroke="#b55a57" stroke-width="1.2"/>'
                    f'<path d="M {cx + 8 * s:.1f} {cy - h / 2 + 6 * s:.1f} C {cx + 8 * s:.1f} {cy - h / 2 - 2 * s:.1f} {cx + 10 * s + w:.1f} {cy - h / 2 + 4 * s:.1f} {cx + 10 * s + w:.1f} {cy + 8 * s:.1f} C {cx + 10 * s + w:.1f} {cy + h / 2:.1f} {cx + 8 * s:.1f} {cy + h / 2 + 2 * s:.1f} {cx + 8 * s:.1f} {cy + 2 * s:.1f} Z" fill="#f08a8a" stroke="#b55a57" stroke-width="1.2"/>')
            pts.update({"hilum_l": (cx - 12 * s, cy + 4 * s), "hilum_r": (cx + 12 * s, cy + 4 * s), "top": (cx, cy - h / 2 - 16 * s), "bottom": (cx, cy + h / 2 + 2 * s)})
            bb = (cx - 10 * s - w, cy - h / 2 - 16 * s, cx + 10 * s + w, cy + h / 2 + 2 * s)
        elif kind == "heart":
            w, h = 40 * s, 44 * s
            body = (f'<path d="M {cx - w / 2:.1f} {cy - 6 * s:.1f} C {cx - w / 2:.1f} {cy - h / 2 - 6 * s:.1f} {cx - 2 * s:.1f} {cy - h / 2 - 2 * s:.1f} {cx:.1f} {cy - h / 2 + 6 * s:.1f} C {cx + 2 * s:.1f} {cy - h / 2 - 2 * s:.1f} {cx + w / 2:.1f} {cy - h / 2 - 6 * s:.1f} {cx + w / 2:.1f} {cy - 6 * s:.1f} C {cx + w / 2:.1f} {cy + 14 * s:.1f} {cx + 6 * s:.1f} {cy + h / 2 - 2 * s:.1f} {cx:.1f} {cy + h / 2:.1f} C {cx - 6 * s:.1f} {cy + h / 2 - 2 * s:.1f} {cx - w / 2:.1f} {cy + 14 * s:.1f} {cx - w / 2:.1f} {cy - 6 * s:.1f} Z" fill="#f4b7b4" stroke="#a9433f" stroke-width="1.3"/>'
                    f'<line x1="{cx:.1f}" y1="{cy - h / 2 + 8 * s:.1f}" x2="{cx:.1f}" y2="{cy + h / 2 - 4 * s:.1f}" stroke="#a9433f" stroke-width="1"/>'
                    f'<line x1="{cx - w / 2 + 3 * s:.1f}" y1="{cy - 2 * s:.1f}" x2="{cx + w / 2 - 3 * s:.1f}" y2="{cy - 2 * s:.1f}" stroke="#a9433f" stroke-width="1" stroke-dasharray="2 2"/>')
            pts.update({"ra": (cx - w / 2 + 4 * s, cy - 12 * s), "rv_out": (cx - 8 * s, cy - h / 2 + 2 * s), "la": (cx + w / 2 - 4 * s, cy - 12 * s), "lv_out": (cx + 8 * s, cy - h / 2 + 2 * s),
                        "rv": (cx - 9 * s, cy + 8 * s), "lv": (cx + 9 * s, cy + 8 * s), "top": (cx, cy - h / 2), "bottom": (cx, cy + h / 2)})
            bb = (cx - w / 2, cy - h / 2 - 2 * s, cx + w / 2, cy + h / 2)
        elif kind == "body":
            r, tw, th = 11 * s, 30 * s, 56 * s
            body = (f'<circle cx="{cx:.1f}" cy="{cy - th / 2 - r - 2 * s:.1f}" r="{r:.1f}" fill="#2d3748"/>'
                    f'<rect x="{cx - tw / 2:.1f}" y="{cy - th / 2:.1f}" width="{tw:.1f}" height="{th:.1f}" rx="{10 * s:.1f}" fill="#2d3748"/>'
                    f'<rect x="{cx - tw / 2:.1f}" y="{cy + th / 2 - 4 * s:.1f}" width="{12 * s:.1f}" height="{30 * s:.1f}" rx="{5 * s:.1f}" fill="#2d3748"/>'
                    f'<rect x="{cx + tw / 2 - 12 * s:.1f}" y="{cy + th / 2 - 4 * s:.1f}" width="{12 * s:.1f}" height="{30 * s:.1f}" rx="{5 * s:.1f}" fill="#2d3748"/>')
            pts.update({"top": (cx, cy - th / 2 - 2 * r - 2 * s), "bottom": (cx, cy + th / 2 + 26 * s), "left": (cx - tw / 2, cy), "right": (cx + tw / 2, cy)})
            bb = (cx - tw / 2, cy - th / 2 - 2 * r - 2 * s, cx + tw / 2, cy + th / 2 + 26 * s)
        else:
            raise ValueError(kind)
        attrs = "".join(f' data-p-{k}="{v[0]:.2f},{v[1]:.2f}"' for k, v in pts.items())
        self.groups.append((oid, f'<g id="{oid}" data-symbol="{kind}"{attrs}>{body}</g>')); self.points[oid] = pts
        self.bbox = getattr(self, "bbox", {}); self.bbox[oid] = bb
        self.obstacles += [((bb[0], bb[1]), (bb[2], bb[1])), ((bb[2], bb[1]), (bb[2], bb[3])), ((bb[2], bb[3]), (bb[0], bb[3])), ((bb[0], bb[3]), (bb[0], bb[1]))]
    def vessel(self, oid, waypoints, colour="#e0302a", width=7, edge=None, arrows_at=(0.5,), radius_px=16):
        """A vessel: a polyline through waypoints (page points or refs) with rounded corners, flow arrows along it,
        data-edge/data-kind when it is an edge of the circulation graph. start = first point, tip = last."""
        P = [self._ref(w) for w in waypoints]
        d = [f"M {P[0][0]:.2f} {P[0][1]:.2f}"]
        for i in range(1, len(P) - 1):
            a, b, c = P[i - 1], P[i], P[i + 1]
            def toward(p, q, r):
                L = math.hypot(q[0] - p[0], q[1] - p[1]) or 1; r = min(r, L / 2); return (p[0] + (q[0] - p[0]) / L * r, p[1] + (q[1] - p[1]) / L * r)
            e1 = toward(b, a, radius_px); e2 = toward(b, c, radius_px)
            d.append(f"L {e1[0]:.2f} {e1[1]:.2f} Q {b[0]:.2f} {b[1]:.2f} {e2[0]:.2f} {e2[1]:.2f}")
        d.append(f"L {P[-1][0]:.2f} {P[-1][1]:.2f}")
        e = f' data-edge="{edge[0]}->{edge[1]}" data-kind="{edge[2]}"' if edge else ""
        body = f'<path{e} d="{" ".join(d)}" fill="none" stroke="{colour}" stroke-width="{width}" stroke-linecap="round"/>'
        # flow arrows: small white chevrons at fractions of the polyline length
        segs = [(P[i], P[i + 1]) for i in range(len(P) - 1)]; total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in segs)
        for fr in arrows_at:
            t = fr * total
            for a, b in segs:
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                if t <= L:
                    u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L); m = (a[0] + u[0] * t, a[1] + u[1] * t); n = (-u[1], u[0])
                    body += f'<path data-flow="1" d="M {m[0] - u[0] * 5 + n[0] * 4:.2f} {m[1] - u[1] * 5 + n[1] * 4:.2f} L {m[0] + u[0] * 4:.2f} {m[1] + u[1] * 4:.2f} L {m[0] - u[0] * 5 - n[0] * 4:.2f} {m[1] - u[1] * 5 - n[1] * 4:.2f}" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>'
                    break
                t -= L
        # obstacles for label placement follow the rounded path itself, not the waypoint polyline
        R_ = [P[0]]
        for i in range(1, len(P) - 1):
            a, b, c = P[i - 1], P[i], P[i + 1]
            def toward(p, q, r):
                L = math.hypot(q[0] - p[0], q[1] - p[1]) or 1; r = min(r, L / 2); return (p[0] + (q[0] - p[0]) / L * r, p[1] + (q[1] - p[1]) / L * r)
            e1 = toward(b, a, radius_px); e2 = toward(b, c, radius_px); R_.append(e1)
            for k in range(1, 8):
                t = k / 8; R_.append(((1 - t) ** 2 * e1[0] + 2 * (1 - t) * t * b[0] + t * t * e2[0], (1 - t) ** 2 * e1[1] + 2 * (1 - t) * t * b[1] + t * t * e2[1]))
            R_.append(e2)
        R_.append(P[-1])
        obst = [(R_[i], R_[i + 1]) for i in range(len(R_) - 1)]
        self._add(oid, body, pts={"start": P[0], "tip": P[-1], "centre": P[len(P) // 2]}, obstacles=obst)

    def group(self, oid, members):
        """Wrap already-drawn objects into one group <g id=oid> (e.g. the four vessels of a circulation graph).
        The members keep their own ids; the group takes the paint position of its first member."""
        picked = [g for g in self.groups if g[0] in members]
        if not picked: raise ValueError(f"group {oid}: none of {members} drawn yet")
        first = self.groups.index(picked[0]); self.groups = [g for g in self.groups if g not in picked]
        self.groups.insert(first, (oid, f'<g id="{oid}">' + "".join(g[1] for g in picked) + "</g>"))
        xs = [self.bbox[m] for m in members if m in getattr(self, "bbox", {})]
        if xs:
            self.bbox[oid] = (min(b[0] for b in xs), min(b[1] for b in xs), max(b[2] for b in xs), max(b[3] for b in xs))
            self.points[oid] = {"centre": ((self.bbox[oid][0] + self.bbox[oid][2]) / 2, (self.bbox[oid][1] + self.bbox[oid][3]) / 2)}

    # ---------------------------------------------------------------- helpers
    def _ref(self, r):
        if isinstance(r, (tuple, list)): return (float(r[0]), float(r[1]))
        if ":atom:" in r:
            oid, _, key = r.split(":"); A = self.atoms[oid]
            if key.isdigit(): return A[int(key)]
            hits = [p for i, p in A.items() if self.atom_el[oid][i] == key]; return hits[0]
        if ":bond:" in r:
            oid, _, ij = r.split(":"); i, j = (int(t) for t in ij.split("-")); A = self.atoms[oid]
            return ((A[i][0] + A[j][0]) / 2, (A[i][1] + A[j][1]) / 2)
        if "." in r:
            oid, name = r.split(".", 1); return self.points[oid][name]
        return self.points[r]["centre"]
    def _add(self, oid, body, pts=None, obstacles=None):
        attrs = "".join(f' data-p-{k}="{v[0]:.2f},{v[1]:.2f}"' for k, v in (pts or {}).items() if v)
        self.groups.append((oid, f'<g id="{oid}"{attrs}>{body}</g>'))
        if pts: self.points[oid] = dict(pts)
        if obstacles: self.obstacles += obstacles
        allp = [p for seg in (obstacles or []) for p in seg] + [v for v in (pts or {}).values() if v]
        if allp:
            self.bbox = getattr(self, "bbox", {}); self.bbox[oid] = (min(p[0] for p in allp), min(p[1] for p in allp), max(p[0] for p in allp), max(p[1] for p in allp))
    # ---------------------------------------------------------------- molecules (RDKit)
    def molecule(self, oid, smiles, at, bond_px=None, colour="#111", font_size=15):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        bond_px = bond_px or self.scale or 34
        m = Chem.MolFromSmiles(smiles); AllChem.Compute2DCoords(m); Chem.WedgeMolBonds(m, m.GetConformer()); conf = m.GetConformer()
        atoms = [{"idx": a.GetIdx() + 1, "el": a.GetSymbol(), "x": conf.GetAtomPosition(a.GetIdx()).x, "y": conf.GetAtomPosition(a.GetIdx()).y,
                  "charge": a.GetFormalCharge(), "hs": a.GetTotalNumHs()} for a in m.GetAtoms()]
        bonds = []
        for b in m.GetBonds():
            d = b.GetBondDir(); st = "wedge" if d == Chem.BondDir.BEGINWEDGE else ("hash" if d == Chem.BondDir.BEGINDASH else "none")
            bonds.append({"i": b.GetBeginAtomIdx() + 1, "j": b.GetEndAtomIdx() + 1, "order": int(b.GetBondTypeAsDouble()), "stereo": st})
        xs, ys = [a["x"] for a in atoms], [a["y"] for a in atoms]; mx, my = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        pos = {a["idx"]: (at[0] + bond_px * (a["x"] - mx), at[1] - bond_px * (a["y"] - my)) for a in atoms}
        el = {a["idx"]: a["el"] for a in atoms}
        out, obst = [], []
        for b in bonds:
            (x1, y1), (x2, y2) = pos[b["i"]], pos[b["j"]]; L = math.hypot(x2 - x1, y2 - y1); ux, uy = (x2 - x1) / L, (y2 - y1) / L
            s1 = 9 if el[b["i"]] != "C" else 0; s2 = 9 if el[b["j"]] != "C" else 0
            X1, Y1, X2, Y2 = x1 + ux * s1, y1 + uy * s1, x2 - ux * s2, y2 - uy * s2
            attrs = f'data-bond="{b["i"]}-{b["j"]}" data-order="{b["order"]}" data-stereo="{b["stereo"]}"'
            if b["stereo"] == "wedge":
                nx, ny = -uy * 3.2, ux * 3.2
                out.append(f'<polygon {attrs} points="{X1:.2f},{Y1:.2f} {X2 + nx:.2f},{Y2 + ny:.2f} {X2 - nx:.2f},{Y2 - ny:.2f}" fill="{colour}"/>')
            elif b["stereo"] == "hash":
                out.append(f'<line {attrs} x1="{X1:.2f}" y1="{Y1:.2f}" x2="{X2:.2f}" y2="{Y2:.2f}" stroke="{colour}" stroke-width="2.4" stroke-dasharray="2.2 2.2"/>')
            else:
                out.append(f'<line {attrs} x1="{X1:.2f}" y1="{Y1:.2f}" x2="{X2:.2f}" y2="{Y2:.2f}" stroke="{colour}" stroke-width="1.6"/>')
                if b["order"] == 2:
                    nx, ny = -uy * 3.5, ux * 3.5
                    out.append(f'<line x1="{X1 + nx:.2f}" y1="{Y1 + ny:.2f}" x2="{X2 + nx:.2f}" y2="{Y2 + ny:.2f}" stroke="{colour}" stroke-width="1.6"/>')
            obst.append(((X1, Y1), (X2, Y2)))
        for a in atoms:
            x, y = pos[a["idx"]]; base = f'data-atom="{a["el"]}" data-idx="{a["idx"]}" data-pos="{x:.2f},{y:.2f}"' + (f' data-charge="{a["charge"]}"' if a["charge"] else "")
            if a["el"] == "C" and not a["charge"]:
                out.append(f'<circle {base} cx="{x:.2f}" cy="{y:.2f}" r="0.5" fill="none" stroke="none"/>')
            else:
                hs = "H" if a["hs"] == 1 else (f"H{a['hs']}" if a["hs"] > 1 else "")
                chg = {-1: "⁻", 1: "⁺", -2: "²⁻", 2: "²⁺"}.get(a["charge"], "")
                out.append(f'<text {base} x="{x:.2f}" y="{y + font_size / 3:.2f}" text-anchor="middle" font-size="{font_size}" fill="{colour}">{a["el"]}{hs}{chg}</text>')
                obst.append(((x - 12, y - 8), (x + 12, y + 8)))
        self.atoms[oid] = pos; self.bonds[oid] = [(b["i"], b["j"]) for b in bonds]
        self.atom_el = getattr(self, "atom_el", {}); self.atom_el[oid] = el
        self._add(oid, "".join(out), pts={"centre": (float(at[0]), float(at[1]))}, obstacles=obst)
        return pos
    # ---------------------------------------------------------------- marks and arrows
    def text_mark(self, oid, text, at, font_size=18, colour="#111"):
        self._add(oid, f'<text x="{at[0]:.1f}" y="{at[1] + font_size / 3:.1f}" text-anchor="middle" font-size="{font_size}" fill="{colour}">{text}</text>', pts={"centre": (float(at[0]), float(at[1]))})
    def arrow(self, oid, start, tip, edge=None, colour="#111", width=1.8):
        a, b = self._ref(start), self._ref(tip)
        e = f' data-edge="{edge[0]}->{edge[1]}" data-kind="{edge[2]}"' if edge else ""
        self._add(oid, f'<line{e} x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="{colour}" stroke-width="{width}" marker-end="url(#arrow)"/>',
                  pts={"start": a, "tip": b, "centre": ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)}, obstacles=[(a, b)])
    def curly(self, oid, start, tip, bulge=-40, offset_start=(0, 0), offset_tip=(0, 0), colour="#c33"):
        """An electron-pushing arrow: from a point near `start` to a point near `tip`, bowed by `bulge` px."""
        a0, b0 = self._ref(start), self._ref(tip)
        a = (a0[0] + offset_start[0], a0[1] + offset_start[1]); b = (b0[0] + offset_tip[0], b0[1] + offset_tip[1])
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
        nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L; c = (mx + nx * bulge, my + ny * bulge)
        self._add(oid, f'<path d="M {a[0]:.2f} {a[1]:.2f} Q {c[0]:.2f} {c[1]:.2f} {b[0]:.2f} {b[1]:.2f}" fill="none" stroke="{colour}" stroke-width="1.4" marker-end="url(#arrow-red)"/>',
                  pts={"start": a, "tip": b, "centre": c}, obstacles=[(a, c), (c, b)])
    def line(self, oid, start, tip, colour="#222", width=1.6, dash=None, obstacle=True):
        a, b = self._ref(start), self._ref(tip); d = f' stroke-dasharray="{dash}"' if dash else ""
        self._add(oid, f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="{colour}" stroke-width="{width}"{d}/>',
                  pts={"start": a, "tip": b, "centre": ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)}, obstacles=[(a, b)] if obstacle else None)
    # ---------------------------------------------------------------- world-unit objects (physics)
    def point(self, oid, world, r=7, filled=True, colour="#1f77b4"):
        p = self.W2P(*world); fill = colour if filled else "#fff"
        self._add(oid, f'<circle cx="{p[0]:.2f}" cy="{p[1]:.2f}" r="{r}" fill="{fill}" stroke="{colour}" stroke-width="1.5"/>', pts={"centre": p})
    def vector(self, oid, world_from, angle_deg, length_px, colour="#c33"):
        a = self.W2P(*world_from); th = math.radians(self.ev(angle_deg)); b = (a[0] + length_px * math.cos(th), a[1] - length_px * math.sin(th))
        self._add(oid, f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="{colour}" stroke-width="2.2" marker-end="url(#arrow-red)"/>',
                  pts={"start": a, "tip": b, "centre": ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)}, obstacles=[(a, b)])
    def angle_mark(self, oid, world_centre, from_deg, to_deg, r_px=44):
        c = self.W2P(*world_centre); f0, f1 = math.radians(self.ev(from_deg)), math.radians(self.ev(to_deg))
        p0 = (c[0] + r_px * math.cos(f0), c[1] - r_px * math.sin(f0)); p1 = (c[0] + r_px * math.cos(f1), c[1] - r_px * math.sin(f1))
        self._add(oid, f'<path d="M {p0[0]:.2f} {p0[1]:.2f} A {r_px} {r_px} 0 0 0 {p1[0]:.2f} {p1[1]:.2f}" fill="none" stroke="#222" stroke-width="1.2"/>',
                  pts={"centre": (c[0] + r_px * math.cos((f0 + f1) / 2), c[1] - r_px * math.sin((f0 + f1) / 2))})
    def curve(self, oid, pieces, colour="#1f77b4", width=1.6, samples=120):
        d, obst, prev = [], [], None
        for n, pc in enumerate(pieces):
            t0, t1 = self.ev(pc["t"][0]), self.ev(pc["t"][1]); var = pc.get("var", "t")
            for k in range(samples + 1):
                t = t0 + (t1 - t0) * k / samples; p = self.W2P(self.ev(pc["x"], **{var: t}), self.ev(pc["y"], **{var: t}))
                d.append(("M " if (n == 0 and k == 0) else "L ") + f"{p[0]:.2f} {p[1]:.2f}")
                if prev: obst.append((prev, p))
                prev = p
        self._add(oid, f'<path d="{" ".join(d)}" fill="none" stroke="{colour}" stroke-width="{width}"/>', pts={"start": None, "tip": prev}, obstacles=obst)
        self.points[oid] = {"tip": prev}
    def hline_world(self, oid, y, x0, x1, colour="#222", width=1.6, hatch=False):
        a, b = self.W2P(x0, y), self.W2P(x1, y); body = f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{colour}" stroke-width="{width}"/>'
        if hatch: body += "".join(f'<line x1="{x:.1f}" y1="{a[1]:.1f}" x2="{x - 9:.1f}" y2="{a[1] + 9:.1f}" stroke="{colour}" stroke-width="1"/>' for x in [a[0] + 24 * i for i in range(int((b[0] - a[0]) / 24) + 1)])
        self._add(oid, body, pts={"start": a, "tip": b, "centre": ((a[0] + b[0]) / 2, a[1])}, obstacles=[(a, b)])
    def vline_world(self, oid, x, y0, y1, colour="#222", width=5):
        a, b = self.W2P(x, y0), self.W2P(x, y1)
        self._add(oid, f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="{colour}" stroke-width="{width}"/>', pts={"start": a, "tip": b, "centre": ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)}, obstacles=[(a, b)])
    # ---------------------------------------------------------------- labels
    def label(self, for_id, text, side="below", anchor=None, max_px=60, font_size=14, colour="#222", leader=False, frame=None, for_point=None):
        """A label for an object. leader=True draws a thin line from the label to the anchor (the point it names);
        for_point names a point of the object (e.g. 'rv' on a heart) to anchor to; frame=k shows it from frame k on."""
        if for_point and for_id in self.points and for_point in self.points[for_id]: anchor = self.points[for_id][for_point]
        self.labels.append((for_id, text, side, anchor, max_px, font_size, colour, leader, frame))
    def says(self, parts):
        sym, eq, val, unit = parts; v = self.env.get(val, val)
        if isinstance(v, float): v = int(v) if abs(v - round(v)) < 1e-9 else round(v, 2)
        return f"{sym} = {v} {unit}".strip()
    def _place_labels(self):
        out = []; boxes = []
        def box(x, y, text, fs, anc): return text_box(x, y, text, fs, anc)
        def clear(b):
            def seg_hit(a, c):
                r = [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3])]
                def ins(p): return b[0] < p[0] < b[2] and b[1] < p[1] < b[3]
                def x2(o, p, q): return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
                if ins(a) or ins(c): return True
                return any(x2(r[i], r[(i + 1) % 4], a) * x2(r[i], r[(i + 1) % 4], c) < 0 and x2(a, c, r[i]) * x2(a, c, r[(i + 1) % 4]) < 0 for i in range(4))
            if any(seg_hit(a, c) for a, c in self.obstacles): return False
            if any(not (b[2] < ob[0] or ob[2] < b[0] or b[3] < ob[1] or ob[3] < b[1]) for ob in boxes): return False
            return 6 <= b[0] and b[2] <= self.W - 6 and 6 <= b[1] and b[3] <= self.H - 6
        for entry in self.labels:
            for_id, text, side, anchor, max_px, fs, colour = entry[:7]; leader = entry[7] if len(entry) > 7 else False; frame = entry[8] if len(entry) > 8 else None
            if frame is not None and self._frame is not None and frame > self._frame: continue
            if side == "rotated":   # a turned title 44 px left of the anchor (the axis it names)
                x, y = anchor[0] - 44, anchor[1]; w, h = text_width(text, fs), 1.1 * fs
                out.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" font-size="{fs}" fill="{colour}" transform="rotate(-90 {x:.1f} {y:.1f})" data-for="{for_id}" data-anchor="{anchor[0]:.2f},{anchor[1]:.2f}">{text}</text>')
                boxes.append((x - h / 2, y - w / 2, x + h / 2, y + w / 2)); continue
            dirs = {"below": (0, 1), "above": (0, -1), "right": (1, 0), "left": (-1, 0)}
            bb = getattr(self, "bbox", {}).get(for_id)
            if anchor: anc = anchor
            elif bb:   # the edge midpoint of the object's extent on that side
                anc = {"below": ((bb[0] + bb[2]) / 2, bb[3]), "above": ((bb[0] + bb[2]) / 2, bb[1]),
                       "right": (bb[2], (bb[1] + bb[3]) / 2), "left": (bb[0], (bb[1] + bb[3]) / 2)}.get(side, ((bb[0] + bb[2]) / 2, bb[3]))
            else: anc = self.points.get(for_id, {}).get("centre") or self.points.get(for_id, {}).get("tip")
            d0 = dirs.get(side, (0, 1)); anc_t = "start" if side == "right" else ("end" if side == "left" else "middle")
            cands = []
            for r in range(14, int(max_px) - 4, 4):
                cands.append((anc[0] + d0[0] * r, anc[1] + d0[1] * r + (fs / 3 if d0[1] >= 0 else 0), anc_t))
                for a in range(0, 360, 30):
                    cands.append((anc[0] + r * math.cos(math.radians(a)), anc[1] + r * math.sin(math.radians(a)) + fs / 3, "middle"))
            # the side is a 90° cone from the anchor, not a preference: the label's box centre must lie in it
            def on_side(b):
                dx, dy = (b[0] + b[2]) / 2 - anc[0], (b[1] + b[3]) / 2 - anc[1]
                return {"above": -dy > abs(dx), "below": dy > abs(dx), "left": -dx > abs(dy), "right": dx > abs(dy)}.get(side, True)
            chosen = None
            for x, y, at in cands:
                b = box(x, y, text, fs, at)
                if on_side(b) and clear(b) and math.hypot((b[0] + b[2]) / 2 - anc[0], (b[1] + b[3]) / 2 - anc[1]) <= max_px: chosen = (x, y, at, b); break
            if chosen is None:
                x, y, at = cands[0]; chosen = (x, y, at, box(x, y, text, fs, at))
            x, y, at, b = chosen; boxes.append(b)
            if leader:   # from the nearest box edge midpoint to the anchor, stopping 3 px short
                cx_, cy_ = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                cands_e = [((b[0], cy_)), ((b[2], cy_)), ((cx_, b[1])), ((cx_, b[3]))]
                e = min(cands_e, key=lambda p: math.hypot(p[0] - anc[0], p[1] - anc[1]))
                L = math.hypot(anc[0] - e[0], anc[1] - e[1]) or 1; stop = (anc[0] - (anc[0] - e[0]) / L * 3, anc[1] - (anc[1] - e[1]) / L * 3)
                out.append(f'<line data-leader="1" x1="{e[0]:.1f}" y1="{e[1]:.1f}" x2="{stop[0]:.1f}" y2="{stop[1]:.1f}" stroke="#333" stroke-width="0.9"/>')
            out.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{at}" font-size="{fs}" fill="{colour}" data-for="{for_id}" data-anchor="{anc[0]:.2f},{anc[1]:.2f}">{text}</text>')
        return '<g id="labels">' + "".join(out) + "</g>"
    # ---------------------------------------------------------------- output
    def write(self, svg_path="scene.svg"):
        if self.scale is None and self.scale_x is None: self.set_page_scale(self.spec["params"].get("bond_px", {}).get("value", 34) if isinstance(self.spec.get("params", {}).get("bond_px"), dict) else 34)
        res = {"origin": [round(self.origin[0], 2), round(self.origin[1], 2)], "viewBox": [0, 0, self.W, self.H]}
        if self.scale_x: res.update({"scale_x": round(self.scale_x, 6), "scale_y": round(self.scale_y, 6)})
        else: res["scale"] = round(self.scale, 4)
        self.spec["projection"]["resolved"] = res
        frames = sorted({e[8] for e in self.labels if len(e) > 8 and e[8] is not None})
        self._frame = None
        for k in frames:
            self._frame = k; body = self._svg_body(); open(svg_path.replace(".svg", f"_f{k}.svg"), "w").write(body)
        self._frame = None
        self.spec["status"] = "drawn"
        json.dump(self.spec, open(self.spec_path, "w"), indent=1, ensure_ascii=False)
        open(svg_path, "w").write(self._svg_body()); return svg_path
    def _svg_body(self):
        layers = self.spec["projection"].get("layers", [])
        def order_of(oid):   # exact id, else the longest prefix layer ending in '_'
            if oid in layers: return layers.index(oid)
            pref = [n for n, L in enumerate(layers) if L.endswith("_") and oid.startswith(L)]
            return pref[-1] if pref else 10 ** 6
        groups = sorted(self.groups, key=lambda g: order_of(g[0]))
        defs = []; [defs.append(d) for d in self.defs if d not in defs]
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.W} {self.H}" width="{self.W}" height="{self.H}" font-family="{self.font}">',
               '<metadata id="scene-spec">' + html.escape(json.dumps(self.spec, ensure_ascii=False), quote=False) + '</metadata>',
               "<defs>" + "".join(defs) + "</defs>", f'<rect width="{self.W}" height="{self.H}" fill="#fff"/>']
        svg += [g for _, g in groups]; svg.append(self._place_labels()); svg.append("</svg>")
        return "\n".join(svg)
