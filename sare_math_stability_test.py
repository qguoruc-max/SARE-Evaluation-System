#!/usr/bin/env python3
"""Deterministic pilot stability experiment for SARE-Math 1.0.

This is a diagnostic simulation, not a correctness assessment of the papers.
It uses the frozen 15-paper pilot packet and fixed pseudo-random seeds.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
from scipy.special import expit, logit
from scipy.stats import kendalltau

from sare_math_reference import DIMS, calibrated_median

ALPHA = np.array([0.50, 0.30, 0.15, 0.05])
MULT = np.array([0.55, 0.85, 1.15, 1.35])
ANCHORS = np.array([
    [0.0,0.5,0.0,0.5,1.0,1.5], [0.5,1.0,1.5,0.0,1.5,2.0],
    [1.0,1.5,0.5,1.5,2.0,0.5], [1.5,0.0,2.0,1.0,2.5,2.5],
    [2.0,2.5,1.0,2.0,3.0,1.0], [2.5,2.0,2.5,2.5,1.0,3.0],
    [3.0,3.5,2.0,3.0,3.5,1.5], [3.5,3.0,3.5,3.5,2.0,3.5],
    [4.0,4.0,3.0,4.0,4.0,2.0], [0.75,2.75,4.0,1.75,0.5,4.0],
    [2.75,0.75,2.75,3.75,2.75,0.0], [3.75,1.75,1.75,2.75,1.75,2.75]
], dtype=float)


def rank_vector(scores: np.ndarray) -> np.ndarray:
    order = np.argsort(-scores, kind="mergesort")
    r = np.empty(len(scores), dtype=int)
    r[order] = np.arange(1, len(scores) + 1)
    return r


def human_score(dims: np.ndarray, A: np.ndarray, weights: np.ndarray) -> np.ndarray:
    x = dims.copy()
    x[:, :4] *= (1.0 - A)[:, None]
    return 100.0 * (x * weights[None, :]).sum(axis=1)


def paper_arrays(packet: dict) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    dims = np.array([[float(p["scores"][k]) for k in DIMS] for p in packet["papers"]])
    A = np.array([float(p["A"]) for p in packet["papers"]])
    w = np.array([float(packet["central_weights"][k]) for k in DIMS]) / 100.0
    return dims, A, w


def probs_for_A(A: float) -> np.ndarray:
    lo, hi = 0.0, 5.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        val = float(ALPHA @ np.clip(mid * MULT, 0.0, 1.0))
        if val < A:
            lo = mid
        else:
            hi = mid
    return np.clip(((lo + hi) / 2.0) * MULT, 0.0, 1.0)


def estimate_A(rng: np.random.Generator, A_true: np.ndarray,
               nrun: int, systems: int, family_shift_sd: float = 0.18) -> np.ndarray:
    out = []
    for a in A_true:
        base = probs_for_A(float(a))
        vals = []
        for _ in range(systems):
            shift = rng.normal(0.0, family_shift_sd)
            p = expit(logit(np.clip(base, 1e-5, 1.0 - 1e-5)) + shift)
            x = rng.binomial(nrun, p)
            post_mean = (x + 0.5) / (nrun + 1.0)
            vals.append(float(ALPHA @ post_mean))
        out.append(float(np.median(vals)))
    return np.array(out)


def generate_rater_packet(rng: np.random.Generator, true_dims: np.ndarray,
                          raters: int = 7) -> np.ndarray:
    anchor_raw, target_raw = [], []
    for _ in range(raters):
        outlier = rng.random() < 0.12
        gamma = np.exp(rng.normal(0.0, 0.30 if not outlier else 0.60, size=(1, 6)))
        scale = np.exp(rng.normal(0.0, 0.12 if not outlier else 0.25, size=(1, 6)))
        bias = rng.normal(0.0, 0.30 if not outlier else 0.65, size=(1, 6))
        noise = 0.25 if not outlier else 0.65
        def rate(mat: np.ndarray) -> np.ndarray:
            z = 4.0 * np.power(np.clip(mat / 4.0, 0.0, 1.0), gamma)
            raw = np.clip(bias + scale * z + rng.normal(0.0, noise, size=mat.shape), 0.0, 4.0)
            return np.round(raw * 4.0) / 4.0
        anchor_raw.append(rate(ANCHORS))
        target_raw.append(rate(true_dims * 4.0))
    med, _ = calibrated_median(ANCHORS, np.stack(anchor_raw), np.stack(target_raw))
    return med / 4.0


def sample_weight(rng: np.random.Generator, packet: dict) -> np.ndarray:
    lo = np.array([packet["weight_bounds"][k][0] for k in DIMS], dtype=float)
    hi = np.array([packet["weight_bounds"][k][1] for k in DIMS], dtype=float)
    for _ in range(10000):
        x = rng.uniform(lo, hi)
        x = 100.0 * x / x.sum()
        if np.all(x >= lo) and np.all(x <= hi) and x[1] + x[2] >= packet["weight_constraints"]["C_plus_M_min"]:
            return x / 100.0
    return np.array([packet["central_weights"][k] for k in DIMS], dtype=float) / 100.0


def summarize(records: np.ndarray, same_top: np.ndarray) -> Dict[str, float]:
    return {
        "mean_kendall_tau": float(records[:, 0].mean()),
        "tau_q10": float(np.quantile(records[:, 0], 0.10)),
        "tau_median": float(np.quantile(records[:, 0], 0.50)),
        "tau_q90": float(np.quantile(records[:, 0], 0.90)),
        "top4_exact_rate": float(same_top.mean()),
        "max_rank_move_q90": float(np.quantile(records[:, 1], 0.90)),
        "mean_A_MAE": float(records[:, 2].mean()) if records.shape[1] > 2 else 0.0,
    }


def run(packet: dict, reps: int = 2000) -> dict:
    dims, A_true, w0 = paper_arrays(packet)
    true_score = human_score(dims, A_true, w0)
    true_rank = rank_vector(true_score)
    true_top4 = set(np.argsort(-true_score)[:4].tolist())

    out = {}
    # Weight-only sensitivity.
    rng = np.random.default_rng(20260811)
    rec, top = [], []
    for _ in range(reps):
        w = sample_weight(rng, packet)
        s = human_score(dims, A_true, w)
        r = rank_vector(s)
        rec.append([kendalltau(true_rank, r).statistic, np.max(np.abs(r - true_rank))])
        top.append(set(np.argsort(-s)[:4].tolist()) == true_top4)
    out["weights_only"] = summarize(np.array(rec), np.array(top))

    # Rater-only sensitivity.
    rng = np.random.default_rng(20260810)
    rec, top = [], []
    for _ in range(reps):
        d_est = generate_rater_packet(rng, dims)
        s = human_score(d_est, A_true, w0)
        r = rank_vector(s)
        rec.append([kendalltau(true_rank, r).statistic, np.max(np.abs(r - true_rank))])
        top.append(set(np.argsort(-s)[:4].tolist()) == true_top4)
    out["raters_only"] = summarize(np.array(rec), np.array(top))

    # AI protocols.
    for nrun, systems in [(1,1), (9,3), (18,5)]:
        rng = np.random.default_rng(20260812 + nrun + systems)
        rec, top = [], []
        for _ in range(reps):
            A_est = estimate_A(rng, A_true, nrun=nrun, systems=systems)
            s = human_score(dims, A_est, w0)
            r = rank_vector(s)
            rec.append([kendalltau(true_rank, r).statistic,
                        np.max(np.abs(r - true_rank)),
                        np.mean(np.abs(A_est - A_true))])
            top.append(set(np.argsort(-s)[:4].tolist()) == true_top4)
        out[f"AI_{systems}x{nrun}"] = summarize(np.array(rec), np.array(top))

    # Combined recommended protocol.
    rng = np.random.default_rng(20260808)
    rec, top = [], []
    for _ in range(reps):
        d_est = generate_rater_packet(rng, dims)
        A_est = estimate_A(rng, A_true, nrun=18, systems=5)
        w = sample_weight(rng, packet)
        s = human_score(d_est, A_est, w)
        r = rank_vector(s)
        rec.append([kendalltau(true_rank, r).statistic,
                    np.max(np.abs(r - true_rank)),
                    np.mean(np.abs(A_est - A_true))])
        top.append(set(np.argsort(-s)[:4].tolist()) == true_top4)
    out["combined"] = summarize(np.array(rec), np.array(top))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--reps", type=int, default=300)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    packet = json.loads(args.input.read_text(encoding="utf-8"))
    result = run(packet, args.reps)
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

if __name__ == "__main__":
    main()
