# illus/2 — a language for telling a model what a scientific picture must be

A scientific illustration is a proposition, rendered. The language lets a person state the proposition and lets a
model construct a rendering whose truth can be checked by a program that knows nothing about the subject.

## 0. What changed from v1 (the leaps)

| v1 (objects · geometry · projection, in prose) | v2 |
| --- | --- |
| constraints were sentences tagged metric/graph/topological/layout | constraints are **predicates from a fixed calculus**, evaluated by one subject-free validator |
| the checker was written per class | the class brings **relations**; the validator is generic |
| the SVG carried the spec | the SVG carries the spec **and its domain model**: equations and parameters, a molecule, a graph; checking is a **round-trip** from drawing back to the model |
| scale in px per metre | scale in **px per unit**, any unit or none; **fit is a rule**, never numbers |
| a scene was a moment | a scene has **parameters**; an object can be drawn at several values (`ball@t=1`) |
| the model always drew | **infeasible** is a legal answer, and the validator checks the claim |
| "repair" was advice | **repair** is defined: the smallest rule change; everything else byte-identical; each drawn element names the rule that produced it |

## 1. The spec (one JSON object inside `<metadata id="scene-spec">`)

```
language   "illus/2"
class      name of the diagram class
params     name → {value | "search", unit, domain?}      physical quantities; "search" = found by the generator
derived    name → expression over params/derived          the domain model, as formulas (Python math syntax)
model      optional standard domain object: {"kind": "molecule", "smiles": …} | {"kind": "graph", "nodes", "edges"}
objects    id → {type, ...}                                every drawable thing, keyed by its SVG group id
labels     [{for, says: [symbol, "=", value, unit] | text, place: {side, max_px}}]
constraints[{id, rel, args}]                                predicates (section 3)
projection {convention, unit, y_up, fit: {frame, margin_px, hold}, visibility}   section 4
status     "drawn" | "infeasible"   and for infeasible: {reason, violated: [expr], options: [{change, value}]}
```

Sizes are of two kinds and say which: physical (`_m`, `_bond`, any unit) or schematic (`_px`). The generator resolves
the projection (scale, origin, viewBox) from the fit rule and writes the resolved numbers into
`projection.resolved`; a person never types a pixel.

## 2. Objects and points

Every object is one `<g id="<id>">`. An object exposes named points as `data-p-<name>="x,y"` on its group
(`data-p-centre`, `data-p-tip`, `data-p-start`), and the validator also reads the basic shapes inside it. A
parameterised object is drawn once per value: `ball@t=1`, `ball@t=2.5` are separate groups whose spec entries give the
parameter value. Every element that a rule placed carries `data-rule="<rule name>"`, so a failed predicate names
the rule, not the coordinate.

## 3. The constraint calculus (what the validator can evaluate)

Geometry (page or world, through the resolved projection):
- `point_at(obj, x_expr, y_expr)` — the object's reference point is at the world point
- `on_curve(obj, curve_obj)` — the point lies on the drawn curve
- `direction(obj, angle_expr)` — a line or vector points at the angle (degrees, world, from +x)
- `starts_at(obj, x_expr, y_expr)`, `ends_at(obj, x_expr, y_expr)`
- `vertical_at(obj, x_expr)`, `horizontal_at(obj, y_expr)`, `spans_x(obj, x0_expr, x1_expr)`
- `arc(obj, centre_obj, from_deg_expr, to_deg_expr)` — an angle mark
- `length_px(obj, lo, hi)` — schematic size in bounds
- `perpendicular(obj_a, obj_b)`, `parallel(obj_a, obj_b)`, `distance(obj_a, obj_b, expr)`
- `curve_follows(obj)` — the drawn curve matches its `pieces` (parametric expressions) within tolerance
- `inside(obj, region_obj)`, `spans(obj, region_a, region_b)`, `attached(obj, region_obj)` — topology
Domain model:
- `feasible(expr, …)` — every boolean expression holds for the params (the story is consistent)
- `minimal(param, expr, …)` — the searched param is the smallest in its domain satisfying the expressions
- `molecule(obj, smiles)` — the drawn atoms, bonds, wedges and hashes, parsed as chemistry, are that molecule with that stereochemistry (RDKit round-trip)
- `graph(obj, edges)` — the drawn arrows between named objects are exactly this edge list, with these kinds
- `arrow(obj, from_ref, to_ref)` — an arrow runs from one named point to another (`mol:atom:3`, `mol:bond:2-3`, `obj.point`)
Layout and artifact:
- `labels_clear(max_px)`, `in_frame(margin_px)`, `uniform_scale()`, `ids_present()`, `reproducible()`, `portable_text()`

Expressions use the params and derived names, `pi`, and the functions of Python's `math` plus `rad()`, `deg()`.
A class may add relations; it cannot add prose.

## 4. Projection

`convention` is from a catalogue, and each convention fixes what "camera" means:
`orthographic_side`, `orthographic_top`, `cabinet_oblique(alpha, depth_scale)`, `isometric`, `perspective(fov)`,
`skeletal_wedge_hash`, `fischer`, `newman`, `haworth`, `cross_section`, `flattened_membrane`, `pathway_canvas`.
`unit` is the world unit (`m`, `bond`, `none`). `fit` is a rule: `{frame: [W, H], margin_px, hold: "floor at bottom" |
"centre" | "left to right"}`; the generator solves it. `visibility` says what happens to hidden edges and occluded parts.

## 5. The dialogue (the moves, and nothing else)

A move is one artifact. The harness sends moves one at a time — `spec` (write spec.json only), `generate` (compose the
generator from the standard library and run it), `check` (self-check) — because a turn can only stall on what it has
to plan, and a weak model stalls when asked to plan a whole picture at once. Found by experiment: a chemistry request
sent as one turn stalled twice; the same request as moves passed first time.

- **request** (person → model): intent and invariants in words, the class, fixed params, free params, required ids.
- **artifact** (model → person): spec + generator + SVG, or `status: infeasible` with the violated expressions and options.
- **report** (validator → model): the failed predicates, each with the measured and expected values, verbatim.
- **repair** (model → validator): the smallest rule change that satisfies the report; the reply states the diff in
  one line per rule; the generator reruns; everything the report did not name stays byte-identical.
- **edit** (person → model): a change to params, objects, labels or constraints, by name; never to pixels.
- **question** (model → person): only when the request is ambiguous in a way the spec cannot hold both of.

## 6. The standard library (illus2lib)

The language ships a library that owns the artifact rules, so a generator is a short composition: `Scene(spec)`,
`molecule(id, smiles, at)` (RDKit coordinates and wedges, every atom and bond with its data attributes),
`arrow`, `curly`, `text_mark`, `line`, `point`, `vector`, `angle_mark`, `curve(pieces)`, `hline_world`, `vline_world`,
`label(for, text, side, max_px)`, `fit_world(...)`, `write()`. Labels anchor to the edge of an object's extent on the
requested side (not to its centre) and take the nearest clear spot. Class conventions live here too: an
electron-pushing arrow stops 8 px short of a heteroatom symbol.

## 7. The artifact rules (SVG)

One `viewBox`; absolute coordinates; no `transform`; markers in `<defs>`; every object a `<g id>` in paint order; labels
as `<text>` in `<g id="labels">` with `data-for` and `data-anchor`; units in the same text run as their number; no
percentage font sizes, no `baseline-shift` (subscripts as Unicode); curves from their equations or templates, never
fitted by eye; the spec in `<metadata>`; the SVG byte-identical to a fresh run of the generator.

## 7b. v2.1 — what the deck run taught (biology schematic, 3-D gas box, Maxwell–Boltzmann plot)

| finding (from a run, a reference, or the painter's eye) | rule now in the language |
| --- | --- |
| a weak model drew a label where its spec did not say, and *said so itself* | core rule **A8 `labels_match_spec`**: every spec label is drawn once, on its side, within its max_px; nothing drawn that the spec does not list |
| "above" had degraded into "anywhere near" (the placer fell back to a ring of candidates) | **side is a 90° cone** from the anchor; max_px is a disk; the placer searches only inside both, and the validator measures the same thing |
| two vessels of the hand-drawn *reference* crossed; nobody had noticed | class relation **`vessels_clear(group, gap_px, end_px)`**: distinct graph edges keep gap_px apart and never cross, except within end_px of their own ends |
| label boxes were estimated (0.56 em per character); labels touched; a leader stopped short of its text | **measured text** (`textmetrics`: Helvetica widths × 1.08 safety, 3 px pad) shared by placer and validator; a box is a bound on any renderer's box |
| the placer avoided the waypoint polyline, the validator sampled the rounded path; a label sat in a corner the curve cut through | obstacles are the **drawn path**, not the plan of it |
| wrapping member objects into a graph group needed a hack on the library's internals | `Scene.group(id, members)` |
| four vessel anchors on a 37 px heart with 7 px vessels merged into an X; 18/18 had passed | class relation **`anchors_apart(symbol, k)`**: anchors that vessels attach to are ≥ k × the attached vessel width apart; library convention `Scene.min_symbol_size(kind, vessel_width)` |
| the painter's stroke-width 7.5 re-broke that rule on a drawing repaired to 5 px vessels; geometry was untouched | a paint attribute can be read by a relation; the painting stage's **second proof** (relations re-run on the painted file) is not optional, and a painter repairs from the verbatim failure like the drawing model does |
| appearance is a separate competence from truth | the **painting stage** (§9) |

## 9. The painting stage (appearance as a layer, after truth)

The drawing stage owns positions, paths, labels and data attributes. The painting stage owns colour, gradients, stroke
weight, opacity, filters, and decorative sub-shapes *inside* an existing group. A painter (a vision model, looking at
the rendering and at a style target) proposes `paint.json`: `defs` (gradients, filters), `styles` (selector → paint
attributes), `decor` (group → elements appended inside it). Selectors name what the **inventory** lists: `gid`,
`gid > tag:nth(k)`, `gid > tag[attr=value]`. The harness applies it and proves two things on the painted file:
**P-INV** — the geometry fingerprint of every non-decorative element (tag, id, coordinates, path data, data-*, label
text) is unchanged — and every relation of the spec still holds. Geometry, ids and data-* attributes in a style are
refused; decor carries no data-*. Found by experiment (Haiku as painter, circulation figure): 90 attributes, 6 decor
elements, P-INV held, 17/17 relations held; a second round applied three worded corrections exactly (radial gradient
on the heart, chevron weight, flat body) and nothing else. Frames (progressive reveal) are untouched by paint: they
are drawn from the same generator with labels filtered by frame. Paint survives a geometry repair for free (selectors
name identities, not coordinates), but a paint attribute a relation reads — stroke-width in `anchors_apart` — is bound
by that relation; the second proof catches it and the painter repairs it (found by experiment: one round).

## 8. Maturity ladder

L0 a prose prompt · L1 objects/geometry/projection in prose + SVG rules (v1) · L2 executable constraints and a generic
validator (this) · L3 classes with their own relations, conventions catalogue, parameterised scenes ·
L4 dialogue moves with feasibility and defined repair · L4b appearance as a verified layer (painting with P-INV) ·
L5 calibration: per class, which predicates a given model gets wrong and how often, so autonomy is granted per class
on evidence. Evidence so far (Haiku, illus/2.1): first-pass 16/16, 16/16, 15/16 on three classes it had never seen
(circulation graph, 3-D box, distribution plot); every failure was a label-placement rule, none a relation of the science.
