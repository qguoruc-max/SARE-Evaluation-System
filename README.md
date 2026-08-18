# SARE-Math Evaluation Package

**SARE-Math** is a reproducible framework for evaluating mathematical manuscripts in the AI era. It separates three questions that should not be collapsed into a single score:

1. **How valuable is the mathematical result?** — `V`
2. **How much of the core work can a frozen AI baseline reproduce?** — `A`
3. **How much residual human contribution remains after that AI-reproducible work is deducted?** — `S_H`

The package contains the full description of the method, a deterministic Python reference implementation, pilot data, and a stability test.

> **Important:** the Python scripts do not search the web, read new manuscripts, or call AI models. Use external AI tools and expert review to collect and verify the evidence first, record the resulting scores in a frozen JSON file, and then use the scripts to calculate the final marks and robust tiers.

---

## 1. Package contents

| File | Purpose |
|---|---|
| `stable_ai_residual_math_evaluation.pdf` | Full description of the SARE-Math framework. Start here. |
| `stable_ai_residual_math_evaluation.tex` | LaTeX source of the framework document. |
| `sare_math_reference.py` | Deterministic reference implementation for computing `V`, `A`, `S_H`, uncertainty envelopes, and robust tiers. |
| `sare_math_stability_test.py` | Simulation for testing ranking sensitivity to weights, raters, and uncertainty in `A`. |
| `sare_math_pilot.json` | Example input packet containing fifteen pilot manuscripts. Use it as the template for a new assessment. |
| `sare_math_pilot_results.json` | Example JSON output from the reference implementation. |
| `sare_math_pilot_results.csv` | Example tabular output suitable for Excel, R, Python, or other ranking workflows. |
| `sare_math_stability_results.json` | Example output from the stability test. |

---

## 2. Recommended evaluation workflow

### Step 1 — Freeze the object being evaluated

Record the following before scoring:

- the exact manuscript version and file hash;
- the literature-search cutoff date;
- the mathematical field and comparison class;
- the AI systems, tool access, prompting protocol, and computation budget used to estimate `A`;
- the scoring-rule version and reviewer panel.

All manuscripts in one ranking should be evaluated using the same literature cutoff, AI capability baseline, and scoring rules.

### Step 2 — Apply a correctness gate

Before assigning marks, classify the manuscript as:

- `pass`: the main results and essential proof chain have been checked sufficiently for ranking;
- `provisional`: important steps remain unverified or a potentially repairable gap remains;
- `fail`: a fatal error invalidates a principal result.

Only `pass` manuscripts should enter a formal ranking. A high value score cannot compensate for an incorrect theorem or proof.

The present reference script assumes that the manuscripts included in the input JSON have already passed this gate; it does not enforce the gate automatically.

### Step 3 — Use AI tools to search the literature

Use one or more AI research tools together with mathematical databases and primary sources to determine:

- the strongest directly related earlier results;
- whether the main theorem was already known, claimed, or proved in another form;
- the actual gap between the manuscript and the state of the art;
- whether the claimed open problem is correctly identified;
- which definitions, lemmas, proof mechanisms, and computational ingredients are genuinely new;
- whether a later version, published version, correction, or competing manuscript changes the assessment.

Require the AI tool to give verifiable citations. Check the cited papers directly and save the search record in the frozen assessment packet. Do not score novelty from the manuscript's introduction alone.

### Step 4 — Use AI tools and experts to analyze the manuscript

Ask the AI tools to extract:

- the central theorems;
- the logical dependency graph of the proof;
- approximately `3–12` indispensable, nonstandard contribution units;
- the decisive observations and constructions;
- standard or routine parts that should not receive major credit;
- possible logical gaps, hidden assumptions, parameter restrictions, and unverified external inputs;
- the conceptual and technical relation to the closest previous work.

A domain expert should verify the analysis. AI-generated assessments are evidence to be checked, not final judgments.

### Step 5 — Score the six underlying dimensions

For each manuscript, score the following dimensions on `[0,1]`:

- `I`: mathematical importance;
- `C`: conceptual originality;
- `M`: methodological value and reusability;
- `H`: irreplaceable human contribution;
- `R`: robustness and independent verification;
- `E`: exposition and theoretical integration.

The full five-level behavioral anchors are given in the appendix of `stable_ai_residual_math_evaluation.pdf`. A practical method is to score each dimension first on `0–4` using those anchors and then divide by `4`.

### Step 6 — Estimate the AI-reproducible fraction `A`

Estimate `A` by capability testing rather than by guessing from writing style or relying only on an author's AI-use disclosure.

For each core contribution unit, test several frozen AI system configurations at four information levels:

- `H0`: problem, definitions, and prior literature, but no proof route;
- `H1`: additionally provide potentially relevant standard tools;
- `H2`: provide the proof skeleton but hide the decisive observation;
- `H3`: provide the decisive observation and ask the system to complete and verify the proof.

The full protocol recommends at least five system configurations from at least three model families, with repeated independent runs for high-stakes evaluation. A lower-cost preliminary screen may use fewer systems and wider uncertainty intervals.

A run counts as successful only when all predeclared mathematical checks are passed. The paper-level value is the contribution-weighted reproducible fraction. Record it as a decimal in `[0,1]`; for example, `A = 0.30` means an estimated AI-reproducible fraction of `30%` under the frozen baseline.

`A` is **not** a claim that the authors actually used AI, and a failed AI attempt is **not** proof of human originality.

### Step 7 — Enter the assessment in JSON

Copy `sare_math_pilot.json` and replace the pilot manuscripts with the new records. A minimal manuscript entry has the form:

```json
{
  "id": "P01",
  "short_title": "Short manuscript title",
  "arxiv": "2608.12345",
  "A": 0.25,
  "A_unc": 0.05,
  "scores": {
    "I": 0.85,
    "C": 0.80,
    "M": 0.75,
    "H": 0.90,
    "R": 0.80,
    "E": 0.85
  }
}
```

Here:

- `A` is the central AI-reproducible fraction;
- `A_unc` is the uncertainty half-width for `A`;
- every value in `scores` lies in `[0,1]`;
- `score_uncertainty` in the top-level JSON controls the uncertainty assigned to the six dimensions.

The reference program recomputes `V` from the six component scores. Do not rely on a manually entered `V` field in a manuscript record.

### Step 8 — Run the reference implementation

The scripts require Python 3 and the packages `numpy`, `sympy`, and `scipy`.

```bash
python -m venv .venv
```

Activate the environment and install the dependencies:

```bash
# macOS or Linux
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install numpy sympy scipy
```

Compute the scores and robust tiers:

```bash
python sare_math_reference.py sare_math_pilot.json \
  --json-out my_results.json \
  --csv-out my_results.csv
```

Run the diagnostic stability simulation:

```bash
python sare_math_stability_test.py sare_math_pilot.json \
  --reps 300 \
  --out my_stability_results.json
```

The principal output columns are:

- `V`: mathematical value, on a `0–100` scale;
- `A`: AI-reproducible fraction, stored on a `0–1` scale;
- `S_human`: the implementation's name for `S_H`, on a `0–100` scale;
- `S_min`, `S_max`: uncertainty envelope for the human residual score;
- `tier`: robust-dominance tier based on the human residual score and the permitted weight region.

The package's `tier` is not the same as the average-of-`V`-and-`S_H` ranking described below.

---

## 3. The three most important marks

### `V` — Mathematical Value

`V` measures the value of the mathematical result itself, independently of whether the underlying ideas were produced by a person or by an AI system. It is reported on a `0–100` scale.

In the reference implementation,

\[
V=100\bigl(0.25I+0.30C+0.30M+0.10R+0.05E\bigr).
\]

A high `V` indicates a mathematically important, conceptually original, methodologically useful, robust, and well-integrated result.

### `A` — AI-Reproducible Fraction

`A` estimates the fraction of the core contribution that a frozen AI capability baseline can reproduce. It is stored on a `0–1` scale and is often displayed as a percentage.

- `A = 0.10` means approximately `10%` AI-reproducible under the chosen baseline.
- `A = 0.70` means approximately `70%` AI-reproducible under the chosen baseline.

A high `A` does not make the theorem mathematically unimportant; that information remains in `V`. It means that less of the core work remains outside the tested AI capability baseline.

### `S_H` — Residual Human Contribution

`S_H` measures the human contribution remaining after deducting the AI-reproducible part of the core mathematical work. It is reported on a `0–100` scale. In the CSV and JSON output, it is named `S_human`.

For the reference implementation,

\[
S_H=100\Bigl[
0.15(1-A)I+0.20(1-A)C+0.20(1-A)M+0.35(1-A)H+0.05R+0.05E
\Bigr].
\]

The full framework can make the deduction contribution-unit by contribution-unit, which is more precise than using a single paper-level `A`.

The three marks should always be reported together. For example:

- high `V`, high `S_H`: a valuable result with substantial residual human contribution;
- high `V`, lower `S_H`: an important result whose core work is substantially reproducible by the frozen AI baseline;
- moderate `V`, high `S_H`: a narrower result with strong human originality or conceptual input.

---

## 4. Ranking manuscripts

### Default ranking used by the author of this package

The default ranking score is the arithmetic mean of `V` and `S_H`:

\[
\boxed{R_{0.5}=\frac{V+S_H}{2}.}
\]

Rank manuscripts in descending order of `R_{0.5}`, after applying the correctness gate.

This gives equal weight to:

- the value of the mathematical result; and
- the residual human contribution.

`A` should still be displayed in the ranking table, but it should not normally be added as a separate third term because its effect is already incorporated into `S_H`. Adding both `A` and `S_H` independently can double-count the AI adjustment.

### Alternative ranking ratios

Other users may choose a different balance:

\[
\boxed{R_{\lambda}=\lambda V+(1-\lambda)S_H,\qquad 0\leq\lambda\leq1.}
\]

Examples:

| Choice | Formula | Interpretation |
|---|---|---|
| Equal balance | `0.50 V + 0.50 S_H` | Default used by the package author. |
| Result-focused | `0.70 V + 0.30 S_H` | Gives more weight to mathematical importance. |
| Human-contribution-focused | `0.30 V + 0.70 S_H` | Gives more weight to work beyond the AI baseline. |

Always publish the chosen value of `lambda`. Rankings made with different ratios answer different questions and should not be presented as if they were identical.

For close scores, it is preferable to report a tie or consult the uncertainty intervals and robust tiers rather than overinterpret small decimal differences. A practical convention is to treat a difference below one point as a tie.

### Ranking the generated CSV with Python

The following script uses only the Python standard library:

```python
import csv

alpha = 0.50  # weight assigned to V

with open("my_results.csv", encoding="utf-8", newline="") as file:
    rows = list(csv.DictReader(file))

for row in rows:
    value = float(row["V"])
    human = float(row["S_human"])
    row["ranking_score"] = alpha * value + (1.0 - alpha) * human

rows.sort(key=lambda row: (-row["ranking_score"], row["id"]))

for rank, row in enumerate(rows, start=1):
    print(
        rank,
        row["id"],
        row["title"],
        f"V={float(row['V']):.2f}",
        f"A={100.0 * float(row['A']):.1f}%",
        f"S_H={float(row['S_human']):.2f}",
        f"R={row['ranking_score']:.2f}",
    )
```

In an Excel table, an equivalent formula is:

```text
=0.5*[@V]+0.5*[@S_human]
```

Replace `0.5` by the desired value of `lambda` and replace the second `0.5` by `1-lambda`.

---

## 5. Suggested AI evaluation prompt

The following prompt can be adapted for an AI research tool that has access to the manuscript and literature search:

```text
Evaluate the attached mathematical manuscript under the SARE-Math framework.

Literature cutoff: [YYYY-MM-DD]
Mathematical field: [FIELD]
Comparison class: [ARXIV MONTH / JOURNAL LEVEL / RESEARCH AREA]

1. Search the directly related literature up to the cutoff date. Identify the
   strongest predecessors, competing results, later versions, and any prior
   solution of the claimed problem. Give verifiable primary-source citations.
2. State the manuscript's central theorems precisely and apply a correctness
   gate: pass, provisional, or fail. List every potentially fatal point.
3. Extract 3–12 indispensable nonstandard contribution units and explain the
   proof dependency graph.
4. Separate decisive observations, reusable methods, technical closure,
   routine work, and exposition.
5. Score I, C, M, H, R, and E on the 0–4 behavioral-anchor scale. Give a
   mathematical justification for every score and then divide each score by 4
   to obtain JSON-ready values in [0,1].
6. Do not infer AI use from prose style. Propose a reproducibility protocol for
   estimating A at prompt levels H0, H1, H2, and H3, including atomic success
   checks and uncertainty.
7. Return a concise evidence table, a list of unresolved uncertainties, and a
   JSON-ready manuscript record. Do not invent references or claim that an
   unverified proof step has been checked.
```

For a serious evaluation, repeat the analysis with multiple AI systems and independent expert reviewers. Resolve factual discrepancies from the primary mathematical sources before fixing the input JSON.

---

## 6. Reporting recommendations

A ranking table should contain at least:

| Rank | Manuscript | Correctness status | `V` | `A` | `S_H` | Ranking formula | Ranking score | Uncertainty/tier |
|---:|---|---|---:|---:|---:|---|---:|---|

Also report:

- the literature cutoff date;
- the AI capability baseline and number of runs;
- the reviewer panel or review procedure;
- the chosen value of `lambda`;
- any unresolved correctness or novelty questions;
- the assessment packet hash or version identifier.

Do not report only one aggregate rank. Keeping `V`, `A`, and `S_H` visible prevents a valuable AI-reproducible result from being confused with a result having large residual human contribution.

---

## 7. Interpretation and limitations

- SARE-Math is an evaluation framework, not an automatic proof verifier.
- `A` depends on the model, tools, literature access, prompting, and computation budget frozen for the evaluation.
- A future AI system may produce a different `A`; historical evaluation should use the capability baseline available at the relevant assessment date.
- Literature search and mathematical importance remain field-dependent and require expert judgment.
- Manuscripts from substantially different fields should not be ranked together without field normalization or carefully selected anchors.
- The stability simulation is diagnostic. It does not establish the correctness of the pilot manuscripts.

