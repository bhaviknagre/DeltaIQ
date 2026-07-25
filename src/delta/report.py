from __future__ import annotations

import json
from pathlib import Path

from src.delta.engine import ChangeKind, DeltaItem, DeltaResult

_SIGNAL_EMOJI = {"red": "\U0001F534", "yellow": "\U0001F7E1", "green": "\U0001F7E2"}


def to_json(result: DeltaResult) -> dict:
    return json.loads(result.model_dump_json())


def _item_line(item: DeltaItem, show_location: bool = True) -> str:
    loc = f" at ({item.bbox.x0:.0f}, {item.bbox.y0:.0f})" if show_location else ""
    signal = _SIGNAL_EMOJI[item.criticality.value]
    return (
        f"- {signal} **[{item.criticality.value.upper()}] [{item.change_kind.value.upper()}] [{item.category.value}]** "
        f"`{item.id}`{loc} — {item.description} (confidence: {item.confidence:.2f})"
    )


def to_markdown(result: DeltaResult, label_a: str = "PID A", label_b: str = "PID B") -> str:
    counts = result.counts_by_kind()
    by_cat = result.counts_by_category()
    by_crit = result.counts_by_criticality()
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
    lines.append(f"- **Average confidence**: {result.avg_confidence():.2f}")
    lines.append(
        f"- **Criticality**: {_SIGNAL_EMOJI['red']} {by_crit['red']} red · "
        f"{_SIGNAL_EMOJI['yellow']} {by_crit['yellow']} yellow · "
        f"{_SIGNAL_EMOJI['green']} {by_crit['green']} green"
    )
    if by_cat:
        cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(by_cat.items()))
        lines.append(f"- **By category**: {cat_str}")
    lines.append("")
    for kind, heading in ((ChangeKind.ADDED, "Added"), (ChangeKind.REMOVED, "Removed"), (ChangeKind.MODIFIED, "Modified")):
        items = [it for it in result.items if it.change_kind == kind]
        if not items:
            continue
        lines.append(f"## {heading}")
        lines.append("")
        for item in items:
            lines.append(_item_line(item))
        lines.append("")

    by_page: dict[int, list[DeltaItem]] = {}
    for item in result.items:
        by_page.setdefault(item.page_index, []).append(item)

    for page_index in sorted(by_page):
        lines.append(f"## Sheet {page_index} (by location)")
        lines.append("")
        for item in sorted(by_page[page_index], key=lambda it: (it.bbox.y0, it.bbox.x0)):
            lines.append(_item_line(item))
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
