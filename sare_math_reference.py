#!/usr/bin/env python3
"""Reference implementation for SARE-Math 1.0.

The default path is deterministic: it reads a frozen JSON packet, computes
central scores, exact weight-robust score bounds by linear programming, and
robust-dominance tiers. No live model, web, clock, or random source is used.

Optional simulation routines are included only for diagnostics and use an
explicit seed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal, getcontext
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
import sympy as sp

getcontext().prec = 28
DIMS = ("I", "C", "M", "H", "R", "E")


def canonical_json_bytes(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def packet_hash(obj: object) -> str:
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


def d(x: object) -> Decimal:
    return Decimal(str(x))


def wilson_interval(x: int, n: int, z: float = 1.6448536269514722) -> Tuple[float, float]:
    """Two-sided 90% Wilson interval by default."""
    if n <= 0:
        return 0.0, 1.0
    p = x / n
    den = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / den
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def pava_fit(x: Sequence[float], y: Sequence[float]) -> Tuple[np.ndarray, np.ndarray]:
    """Deterministic isotonic regression via the pool-adjacent-violators algorithm.

    Duplicate x values are averaged before PAVA. Returns knot x and fitted y.
    """
    pairs: Dict[float, List[float]] = {}
    for xi, yi in zip(x, y):
        pairs.setdefault(float(xi), []).append(float(yi))
    xs = np.array(sorted(pairs), dtype=float)
    ys = np.array([np.mean(pairs[v]) for v in xs], dtype=float)
    wt = np.array([len(pairs[v]) for v in xs], dtype=float)
    blocks = [[ys[i], wt[i], i, i] for i in range(len(xs))]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] <= blocks[i + 1][0] + 1e-15:
            i += 1
            continue
        w = blocks[i][1] + blocks[i + 1][1]
        val = (blocks[i][0] * blocks[i][1] + blocks[i + 1][0] * blocks[i + 1][1]) / w
        blocks[i:i + 2] = [[val, w, blocks[i][2], blocks[i + 1][3]]]
        i = max(0, i - 1)
    fit = np.empty_like(ys)
    for val, _, lo, hi in blocks:
        fit[lo:hi + 1] = val
    return xs, np.clip(fit, 0.0, 4.0)


def pava_predict(knots_x: np.ndarray, knots_y: np.ndarray,
                 x_new: Sequence[float]) -> np.ndarray:
    return np.interp(np.asarray(x_new, dtype=float), knots_x, knots_y,
                     left=knots_y[0], right=knots_y[-1])


def calibrated_median(anchor_true: np.ndarray, anchor_raw: np.ndarray,
                      target_raw: np.ndarray, max_anchor_mae: float = 0.75) -> Tuple[np.ndarray, np.ndarray]:
    """Calibrate each rater/dimension by PAVA and aggregate by the median.

    Shapes: anchor_raw=(raters, anchors, dims), target_raw=(raters, papers, dims).
    Returns calibrated medians and per-dimension MAD intervals.
    """
    raters, _, dims = anchor_raw.shape
    papers = target_raw.shape[1]
    calibrated = np.full((raters, papers, dims), np.nan)
    errors = np.full((raters, dims), np.inf)
    for r in range(raters):
        for k in range(dims):
            kx, ky = pava_fit(anchor_raw[r, :, k], anchor_true[:, k])
            pred_anchor = pava_predict(kx, ky, anchor_raw[r, :, k])
            errors[r, k] = float(np.mean(np.abs(pred_anchor - anchor_true[:, k])))
            calibrated[r, :, k] = pava_predict(kx, ky, target_raw[r, :, k])
    med = np.zeros((papers, dims))
    rad = np.zeros((papers, dims))
    for k in range(dims):
        accepted = np.where(errors[:, k] <= max_anchor_mae)[0]
        if len(accepted) < 5:
            accepted = np.argsort(errors[:, k])[:min(5, raters)]
        vals = calibrated[accepted, :, k]
        med[:, k] = np.median(vals, axis=0)
        rad[:, k] = 1.4826 * np.median(np.abs(vals - med[None, :, k]), axis=0)
    return med, rad


def krippendorff_alpha_ordinal(ratings: np.ndarray, max_category: float = 4.0) -> float:
    """Krippendorff alpha with squared ordinal distance; NaNs are allowed."""
    ratings = np.asarray(ratings, dtype=float)
    observed_num = 0.0
    observed_den = 0
    pool: List[float] = []
    for item in range(ratings.shape[1]):
        vals = ratings[:, item]
        vals = vals[~np.isnan(vals)]
        pool.extend(vals.tolist())
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                observed_num += ((vals[i] - vals[j]) / max_category) ** 2
                observed_den += 1
    if observed_den == 0 or len(pool) < 2:
        return float("nan")
    Do = observed_num / observed_den
    expected_num = 0.0
    expected_den = 0
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            expected_num += ((pool[i] - pool[j]) / max_category) ** 2
            expected_den += 1
    De = expected_num / expected_den
    return 1.0 - Do / De if De > 0 else 1.0


def central_human_score(paper: dict, weights: Dict[str, int]) -> Decimal:
    A = d(paper["A"])
    total = Decimal("0")
    for k in DIMS:
        value = d(paper["scores"][k])
        if k in ("I", "C", "M", "H"):
            value *= Decimal("1") - A
        total += d(weights[k]) * value
    return total


def intrinsic_value(paper: dict) -> Decimal:
    s = paper["scores"]
    return (d(25) * d(s["I"]) + d(30) * d(s["C"]) +
            d(30) * d(s["M"]) + d(10) * d(s["R"]) + d(5) * d(s["E"]))


def component_intervals(paper: dict, score_unc: Dict[str, float]) -> Tuple[np.ndarray, np.ndarray]:
    A = float(paper["A"])
    Au = float(paper.get("A_unc", 0.0))
    lower = np.zeros(6)
    upper = np.zeros(6)
    for j, k in enumerate(DIMS):
        x = float(paper["scores"][k])
        e = float(score_unc[k])
        xl, xu = max(0.0, x - e), min(1.0, x + e)
        if k in ("I", "C", "M", "H"):
            lower[j] = (1.0 - min(1.0, A + Au)) * xl
            upper[j] = (1.0 - max(0.0, A - Au)) * xu
        else:
            lower[j], upper[j] = xl, xu
    return lower, upper


def _F(x: object) -> Fraction:
    return Fraction(str(x))


def weight_vertices(packet: dict) -> List[Tuple[Fraction, ...]]:
    """Enumerate the admissible weight-polytope vertices exactly.

    The polytope has six variables, one equality sum(w)=100, box bounds,
    and C+M>=35. Every linear optimum is attained at one of these vertices.
    """
    lower = [_F(packet["weight_bounds"][k][0]) for k in DIMS]
    upper = [_F(packet["weight_bounds"][k][1]) for k in DIMS]
    total = _F(packet["weight_constraints"]["sum"])
    cm_min = _F(packet["weight_constraints"]["C_plus_M_min"])
    # Each active constraint is (row, rhs).
    active = []
    for i in range(6):
        row = [Fraction(0) for _ in range(6)]; row[i] = Fraction(1)
        active.append((row, lower[i], f"L{i}"))
        active.append((row, upper[i], f"U{i}"))
    row = [Fraction(0) for _ in range(6)]; row[1] = row[2] = Fraction(1)
    active.append((row, cm_min, "CM"))
    base_row = [Fraction(1) for _ in range(6)]
    vertices = set()
    for combo in combinations(active, 5):
        A = [base_row] + [c[0] for c in combo]
        b = [total] + [c[1] for c in combo]
        M = sp.Matrix([[sp.Rational(v.numerator, v.denominator) for v in row] for row in A])
        if M.det() == 0:
            continue
        rhs = sp.Matrix([sp.Rational(v.numerator, v.denominator) for v in b])
        sol = M.LUsolve(rhs)
        x = tuple(Fraction(int(v.p), int(v.q)) for v in sol)
        if any(x[i] < lower[i] or x[i] > upper[i] for i in range(6)):
            continue
        if x[1] + x[2] < cm_min or sum(x) != total:
            continue
        vertices.add(x)
    if not vertices:
        raise RuntimeError("empty weight polytope")
    return sorted(vertices)


def weight_opt(packet: dict, objective: Sequence[float], maximize: bool = False,
               vertices: List[Tuple[Fraction, ...]] | None = None) -> Tuple[float, Tuple[Fraction, ...]]:
    if vertices is None:
        vertices = weight_vertices(packet)
    obj = [_F(v) for v in objective]
    values = [(sum(wi * ci for wi, ci in zip(v, obj)), v) for v in vertices]
    value, vertex = (max(values, key=lambda z: z[0]) if maximize else min(values, key=lambda z: z[0]))
    return float(value), vertex


def robust_tiers(packet: dict, lowers: List[np.ndarray], uppers: List[np.ndarray], vertices=None) -> Tuple[List[List[int]], List[Tuple[int, int, float]]]:
    margin = float(packet.get("robust_margin", 1.0))
    n = len(lowers)
    edges: List[Tuple[int, int, float]] = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            diff = lowers[i] - uppers[j]
            val, _ = weight_opt(packet, diff, maximize=False, vertices=vertices)
            if val > margin:
                edges.append((i, j, val))
    remaining = set(range(n))
    tiers: List[List[int]] = []
    central = [float(central_human_score(p, packet["central_weights"])) for p in packet["papers"]]
    while remaining:
        indeg = {j: 0 for j in remaining}
        for i, j, _ in edges:
            if i in remaining and j in remaining:
                indeg[j] += 1
        tier = [j for j, deg in indeg.items() if deg == 0]
        if not tier:
            tier = list(remaining)
        tier.sort(key=lambda idx: (-central[idx], packet["papers"][idx]["id"]))
        tiers.append(tier)
        remaining.difference_update(tier)
    return tiers, edges


def compute(packet: dict) -> dict:
    vertices = weight_vertices(packet)
    lowers, uppers = [], []
    rows = []
    for p in packet["papers"]:
        lo, up = component_intervals(p, packet["score_uncertainty"])
        lowers.append(lo); uppers.append(up)
        smin, _ = weight_opt(packet, lo, maximize=False, vertices=vertices)
        smax, _ = weight_opt(packet, up, maximize=True, vertices=vertices)
        rows.append({
            "id": p["id"], "title": p["short_title"], "arxiv": p.get("arxiv", ""),
            "V": float(intrinsic_value(p)), "A": float(p["A"]),
            "S_human": float(central_human_score(p, packet["central_weights"])),
            "S_min": smin, "S_max": smax,
        })
    tiers, edges = robust_tiers(packet, lowers, uppers, vertices=vertices)
    for t, idxs in enumerate(tiers, start=1):
        for idx in idxs:
            rows[idx]["tier"] = t
    rows.sort(key=lambda r: (r["tier"], -r["S_human"], r["id"]))
    return {
        "schema_version": packet["schema_version"],
        "evaluation_epoch": packet["evaluation_epoch"],
        "packet_hash": packet_hash(packet),
        "rows": rows,
        "tiers": [[packet["papers"][i]["id"] for i in tier] for tier in tiers],
        "weight_vertices": len(vertices),
        "robust_edges": len(edges),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--csv-out", type=Path, default=None)
    args = ap.parse_args()
    packet = json.loads(args.input.read_text(encoding="utf-8"))
    result = compute(packet)
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.csv_out:
        with args.csv_out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["tier","id","title","arxiv","V","A","S_human","S_min","S_max"])
            writer.writeheader()
            writer.writerows(result["rows"])


if __name__ == "__main__":
    main()
