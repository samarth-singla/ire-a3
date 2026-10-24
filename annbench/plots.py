"""Recall vs QPS plots (and later experiment figures), drawn with matplotlib.

Style: one fixed colour + marker per index family (validated colour-blind-safe categorical
palette, first three slots), thin 2-pt lines, recessive grey grid and axes, text in neutral
ink (never in the series colour). Every family has a legend entry and a direct label at the
end of its curve, because one colour (aqua) is below 3:1 contrast on white. Figures are saved
as both .png (200 dpi) and .pdf (for the LaTeX report).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from annbench.frontier import FAMILY_LABEL, pareto_df  # noqa: E402

# categorical slots 1-3 of the reference palette (validated: all-pairs CVD dE >= 9.2)
FAMILY_COLOR = {"hnsw": "#2a78d6", "ivfflat": "#eb6834", "ivfpq": "#1baf7a",
                "ivfpq_refine": "#2a78d6"}
FAMILY_MARKER = {"hnsw": "o", "ivfflat": "s", "ivfpq": "^", "ivfpq_refine": "D"}
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.grid(True, which="major", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def save(fig, out_base: Path) -> list[Path]:
    out_base = Path(out_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    paths = [out_base.with_suffix(".png"), out_base.with_suffix(".pdf")]
    fig.savefig(paths[0], dpi=200, bbox_inches="tight")
    fig.savefig(paths[1], bbox_inches="tight")
    plt.close(fig)
    return paths


def recall_qps_plot(df: pd.DataFrame, families, out_base: Path, title: str,
                    exact_qps: float | None = None, targets=(0.90, 0.95)) -> list[Path]:
    """Recall@10 (test) vs single-thread QPS (log), Pareto curve per family.

    ``df``: test-split rows of one dataset (all build configs). Non-frontier points are drawn
    as faint grey markers. ``exact_qps``: exact single-query QPS (Part 1), drawn as a
    horizontal line with a marker at recall 1.0; omitted (with a note) when None.
    """
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    _style(ax)
    xmin = 1.0
    for fam in families:
        d = df[df["index"] == fam]
        if d.empty:
            continue
        xmin = min(xmin, d["recall_at_10"].min())
        front = pareto_df(d)
        rest = d.drop(front.index)
        ax.scatter(rest["recall_at_10"], rest["qps_median"], s=10, color=AXIS,
                   edgecolors="none", zorder=2)
        label = FAMILY_LABEL[fam]
        ax.plot(front["recall_at_10"], front["qps_median"], color=FAMILY_COLOR[fam],
                linewidth=2, marker=FAMILY_MARKER[fam], markersize=5.5,
                markeredgecolor="white", markeredgewidth=0.8, label=label, zorder=3)
        # direct label at the high-recall end of the curve (text in ink, not series colour)
        end = front.iloc[-1]
        ax.annotate(label, (end["recall_at_10"], end["qps_median"]), xytext=(4, 4),
                    textcoords="offset points", fontsize=8, color=INK, zorder=4)

    if exact_qps is not None:
        ax.axhline(exact_qps, color=INK2, linewidth=1.2, linestyle=(0, (4, 2)), zorder=1)
        # direct label just above the line, right of centre (the legend sits at the left)
        ax.scatter([1.0], [exact_qps], s=36, color=INK2, marker="*", zorder=4)
        ax.annotate(f"Exact search, 1 thread: {exact_qps:,.0f} QPS", (0.5, exact_qps),
                    xycoords=("axes fraction", "data"), xytext=(0, 4),
                    textcoords="offset points", fontsize=8, color=INK2, ha="center")
    else:
        ax.text(0.01, 0.01, "exact baseline not available for this run",
                transform=ax.transAxes, fontsize=7, color=MUTED)

    for t in targets:
        ax.axvline(t, color=MUTED, linewidth=0.8, linestyle=(0, (3, 3)), zorder=1)
        ax.annotate(f"{t:.2f}", (t, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(2, -10), textcoords="offset points", fontsize=7, color=MUTED)

    ax.set_yscale("log")
    ax.set_xlim(max(0.0, xmin - 0.02), 1.005)
    ax.set_xlabel("Recall@10 (test queries)", fontsize=9, color=INK)
    ax.set_ylabel("Queries per second (1 thread, log scale)", fontsize=9, color=INK)
    ax.set_title(title, fontsize=10, color=INK, loc="left")
    leg = ax.legend(fontsize=8, frameon=False, loc="center left")
    for text in leg.get_texts():
        text.set_color(INK)
    return save(fig, out_base)
