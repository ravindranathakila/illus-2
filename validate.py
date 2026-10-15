"""
validate.py <run_dir> <round>   — the illus/2 generic validator.

Reads <run_dir>/scene.svg, takes the spec from its <metadata>, and evaluates every constraint in the spec with the
relations library. It knows no subject. Core artifact rules are always checked. A status of "infeasible" is
accepted only if the validator's own search agrees. Writes validation_<round>.json; exit 0 = all pass.
"""
import json, os, sys, hashlib, shutil, subprocess, tempfile
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import relations as R

def validate(run_dir, rnd="0", svg_name="scene.svg", repro=True, quiet=False):
    results = []
    def check(cid, ok, measured, expected=""):
        results.append({"id": cid, "pass": bool(ok), "measured": str(measured), "expected": str(expected)})

    spec_path = os.path.join(run_dir, "spec.json"); svg_path = os.path.join(run_dir, svg_name)
    spec = None; root = None
    try:
        spec = json.load(open(spec_path))
    except Exception as e:
        check("A0", False, f"spec.json unreadable: {e}", "a JSON spec")

    if spec and spec.get("status") == "infeasible":
        # the model declined to draw: verify the claim by search, nothing else
        det = spec.get("infeasible") or {}
        param = det.get("param"); exprs = det.get("violated") or []
        check("A1", spec.get("language") == "illus/2", f"language {spec.get('language')}", "illus/2")
        ctx = R.Ctx(ET.Element("svg"), spec, run_dir)
        ok, m, e = R.infeasible_claim(ctx, param, *exprs) if param else (False, "no param named", "a searched param")
        check("F1", ok, m, e)
        check("F2", bool(det.get("options")), f"{len(det.get('options') or [])} options offered", "at least one option")
    else:
        try:
            root = ET.parse(svg_path).getroot()
        except Exception as e:
            check("A0", False, f"scene.svg does not parse: {e}", "well-formed SVG")
        if root is not None:
            md = root.find(".//*[@id='scene-spec']")
            try:
                md_spec = json.loads(md.text)
                same = json.dumps(md_spec, sort_keys=True) == json.dumps(spec, sort_keys=True)
                check("A1", md_spec.get("language") == "illus/2" and same, f"metadata spec {'matches' if same else 'DIFFERS from'} spec.json; language {md_spec.get('language')}", "identical; illus/2")
                spec = md_spec
            except Exception as e:
                check("A1", False, f"metadata spec missing or invalid: {e}", "the spec in <metadata id=scene-spec>")
            ctx = R.Ctx(root, spec or {}, run_dir)
            vb = ctx.vb
            check("A2", vb is not None and vb[2] <= 1000, f"viewBox {vb}", "present, width ≤ 1000")
            for cid, rel in (("A3", "ids_present"), ("A4", "no_transforms"), ("A5", "portable_text"), ("A6", "uniform_scale"), ("A8", "labels_match_spec")):
                ok, m, e = R.RELATIONS[rel](ctx); check(cid, ok, m, e)
            # reproducibility
            try:
                if not repro: raise RuntimeError("skipped")
                before = hashlib.sha256(open(svg_path, "rb").read()).hexdigest(); tmp = tempfile.mkdtemp()
                for fn in ("spec.json", "generate.py"): shutil.copy(os.path.join(run_dir, fn), tmp)
                p = subprocess.run([sys.executable, "-I", "generate.py"], cwd=tmp, capture_output=True, text=True, timeout=120)
                cands = [c for c in (os.path.join(tmp, "scene.svg"), svg_path) if os.path.exists(c)]
                newest = max(cands, key=os.path.getmtime) if cands else None
                after = hashlib.sha256(open(newest, "rb").read()).hexdigest() if newest else None
                check("A7", p.returncode == 0 and after == before, "generate.py reproduces scene.svg byte for byte" if after == before else f"regenerated SVG differs (rc={p.returncode}) {p.stderr[-160:]}", "identical")
            except RuntimeError:
                pass
            except Exception as e:
                check("A7", False, f"could not re-run generate.py: {e}", "identical")
            # the spec's own constraints
            for c in (spec or {}).get("constraints") or []:
                cid, rel, args = c.get("id", "?"), c.get("rel"), c.get("args") or []
                fn = R.RELATIONS.get(rel)
                if fn is None: check(cid, False, f"unknown relation '{rel}'", "a relation from the calculus"); continue
                try: ok, m, e = fn(ctx, *args)
                except Exception as ex: ok, m, e = False, f"{rel}{tuple(args)} raised {type(ex).__name__}: {ex}", "evaluable"
                check(cid, ok, f"{rel}: {m}", e)

    json.dump(results, open(os.path.join(run_dir, f"validation_{rnd}.json"), "w"), indent=1, ensure_ascii=False)
    n_fail = sum(1 for r in results if not r["pass"])
    if not quiet:
        for r in results:
            print(f"{r['id']:5} {'PASS' if r['pass'] else 'FAIL'}  {r['measured']}" + ("" if r["pass"] else f"\n       expected: {r['expected']}"))
        print(f"\n{len(results) - n_fail}/{len(results)} checks pass")
    return list(results)


if __name__ == "__main__":
    res = validate(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "0")
    sys.exit(1 if any(not r["pass"] for r in res) else 0)
