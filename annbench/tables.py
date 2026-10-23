"""Write a table as Markdown (.md) and LaTeX (.tex) from the same rows.

The .tex file is a ``table`` float with a booktabs ``tabular`` (the report needs
``\\usepackage{booktabs}``), a caption and a label, ready for ``\\input{}``.
"""
from __future__ import annotations

from pathlib import Path

_LATEX_SPECIAL = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
                  "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
                  "^": r"\textasciicircum{}"}


def latex_escape(text) -> str:
    s = str(text)
    out = "".join(_LATEX_SPECIAL.get(ch, ch) for ch in s)
    return out.replace("×", r"$\times$").replace("≥", r"$\geq$").replace("≤", r"$\leq$")


def write_table(headers: list[str], rows: list[list], out_base: Path, caption: str,
                label: str, align: str | None = None) -> list[Path]:
    """Write ``out_base.md`` and ``out_base.tex``. ``rows`` hold already-formatted cells."""
    out_base = Path(out_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    cells = [[("" if c is None else str(c)) for c in r] for r in rows]

    md = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    md += ["| " + " | ".join(c.replace("|", "\\|") for c in r) + " |" for r in cells]
    md += ["", caption, ""]
    md_path = out_base.with_suffix(".md")
    md_path.write_text("\n".join(md), encoding="utf-8")

    align = align or ("l" * len(headers))
    tex = [r"\begin{table}[t]", r"\centering", r"\small",
           rf"\begin{{tabular}}{{{align}}}", r"\toprule",
           " & ".join(latex_escape(h) for h in headers) + r" \\", r"\midrule"]
    tex += [" & ".join(latex_escape(c) for c in r) + r" \\" for r in cells]
    tex += [r"\bottomrule", r"\end{tabular}", rf"\caption{{{latex_escape(caption)}}}",
            rf"\label{{{label}}}", r"\end{table}", ""]
    tex_path = out_base.with_suffix(".tex")
    tex_path.write_text("\n".join(tex), encoding="utf-8")
    return [md_path, tex_path]
