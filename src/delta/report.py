"""Renders a DeltaResult as a human-readable Markdown report and a
machine-parseable JSON report. Both are written to disk; the Markdown
report (chunked by section) is also what the chat layer's retrieval index
treats as a first-class retrievable source alongside PID A and PID B.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.delta.engine import DeltaItem, DeltaResult


def to_json(result: DeltaResult) -> dict:
    return json.loads(result.model_dump_json())


def to_markdown(result: DeltaResult, label_a: str = "PID A", label_b: str = "PID B") -> str:
    counts = result.counts_by_kind()
    by_cat = result.counts_by_category()
    lines: list[str] = []

    lines.append(f"# Delta Report: {label_a} -> {label_b}")
    lines.append("")
    lines.append(f"- **PID A**: `{result.pid_a}`")
    lines.append(f"- **PID B**: `{result.pid_b}`")
    lines.append(f"- **Elements compared**: {result.total_a_elements} (A) vs {result.total_b_elements} (B)")
    lines.append(f"- **Unchanged**: {result.unchanged_count}")
    lines.append(
        f"- **Changes**: {len(result.items)} total "
        f"({counts['added']} added, {counts['removed']} removed, {counts['modified']} modified)"
    )
    if by_cat:
        cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(by_cat.items()))
        lines.append(f"- **By category**: {cat_str}")
    lines.append("")

    by_page: dict[int, list[DeltaItem]] = {}
    for item in result.items:
        by_page.setdefault(item.page_index, []).append(item)

    for page_index in sorted(by_page):
        lines.append(f"## Sheet {page_index}")
        lines.append("")
        for item in by_page[page_index]:
            loc = f"({item.bbox.x0:.0f}, {item.bbox.y0:.0f})"
            lines.append(
                f"- **[{item.change_kind.value.upper()}] [{item.category.value}]** "
                f"`{item.id}` at {loc} — {item.description} "
                f"(confidence: {item.confidence:.2f})"
            )
        lines.append("")

    if not result.items:
        lines.append("_No meaningful changes detected between these two revisions._")
        lines.append("")

    return "\n".join(lines)


def write_report(result: DeltaResult, out_dir: Path, label_a: str = "PID A", label_b: str = "PID B") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "delta_report.md"
    json_path = out_dir / "delta_report.json"

    md_path.write_text(to_markdown(result, label_a, label_b))
    json_path.write_text(json.dumps(to_json(result), indent=2))

    return {"markdown_path": str(md_path), "json_path": str(json_path)}
