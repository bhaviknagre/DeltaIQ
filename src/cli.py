from __future__ import annotations

from pathlib import Path

import click

from src._version import __version__
from src.chat.agentic import answer_question_agentic
from src.chat.answer import answer_question
from src.chat.vector_index import build_retriever
from src.config import settings
from src.delta.engine import compute_delta
from src.delta.report import write_report
from src.ingest.pid_store import load, register_pid, resolve_pid
from src.markup.overlay import render_markup
from src.observability.logging import get_logger, log_event
from src.observability.tracing import new_trace

logger = get_logger("cli")


@click.group()
@click.version_option(version=__version__, prog_name="delta-chat")
def cli():
    pass


@cli.command()
@click.argument("pid")
@click.argument("path")
@click.option("--label", default=None, help="Revision label, e.g. 'Rev A'")
def register(pid: str, path: str, label: str | None):
    register_pid(pid, path, label)
    click.echo(f"Registered {pid} -> {path} ({label or 'no label'})")


@cli.command()
@click.argument("pid_a")
@click.argument("pid_b")
@click.option("--out-dir", default="output", help="Directory to write the delta report to")
def run(pid_a: str, pid_b: str, out_dir: str):
    """Ingest both PIDs, compute the delta, and write the delta report."""
    with new_trace(kind="run", pid_a=pid_a, pid_b=pid_b) as trace:
        with trace.span("ingest_a", pid=pid_a):
            doc_a = load(pid_a)
        with trace.span("ingest_b", pid=pid_b):
            doc_b = load(pid_b)
        with trace.span("delta") as span:
            delta = compute_delta(doc_a, doc_b)
            span.attrs.update(total_changes=len(delta.items), **delta.counts_by_kind())
        with trace.span("report"):
            paths = write_report(delta, Path(out_dir), label_a=pid_a, label_b=pid_b)

    click.echo(f"Delta: {delta.counts_by_kind()} ({len(delta.items)} total changes)")
    click.echo(f"Report: {paths['markdown_path']}")
    click.echo(f"Report (JSON): {paths['json_path']}")
    click.echo(f"Trace: traces/{trace.request_id}.json")


@cli.command()
@click.argument("pid_a")
@click.argument("pid_b")
@click.option("-q", "--question", default=None, help="Ask a single question and exit; omit for interactive mode")
@click.option(
    "--agentic", is_flag=True, default=None,
    help="Use the LangGraph retrieve->answer->verify-citations->retry pipeline (src/chat/agentic.py) "
    "instead of the single-round-trip default. Defaults to settings.chat_backend.",
)
def chat(pid_a: str, pid_b: str, question: str | None, agentic: bool | None):
    """Grounded chat over PID A, PID B, and their delta report."""
    click.echo("Ingesting and computing delta...")
    doc_a = load(pid_a)
    doc_b = load(pid_b)
    delta = compute_delta(doc_a, doc_b)
    index = build_retriever(doc_a, doc_b, delta)
    use_agentic = settings.chat_backend == "agentic" if agentic is None else agentic
    click.echo(
        f"Ready. {len(delta.items)} changes indexed. Ask questions about {pid_a}, {pid_b}, or the delta."
        f" [{'agentic' if use_agentic else 'simple'} pipeline]\n"
    )

    def _ask(q: str):
        with new_trace(kind="chat", pid_a=pid_a, pid_b=pid_b, question=q, agentic=use_agentic) as trace:
            if use_agentic:
                result = answer_question_agentic(q, index, trace)
            else:
                result = answer_question(q, index, trace)
        click.echo(f"\n{result.answer}\n")
        extra = ""
        if use_agentic:
            extra = f", verified={result.verified}, attempts={result.attempts}"
        click.echo(
            f"(grounded={result.grounded}, citations={len(result.citations_used)}, "
            f"model={result.model}, cost=${result.cost_usd:.6f}{extra})"
        )

    if question:
        _ask(question)
        return

    while True:
        try:
            q = click.prompt("You", type=str)
        except (EOFError, KeyboardInterrupt):
            break
        if q.strip().lower() in ("exit", "quit"):
            break
        _ask(q)


@cli.command()
@click.argument("pid_a")
@click.argument("pid_b")
@click.option("--out", default="output/markup.pdf")
def markup(pid_a: str, pid_b: str, out: str):
    """Overlay the delta onto PID B's rendered pages as a redline PDF."""
    doc_a = load(pid_a)
    doc_b = load(pid_b)
    delta = compute_delta(doc_a, doc_b)
    b_source = Path(resolve_pid(pid_b)["path"])
    out_path = render_markup(b_source, delta, Path(out))
    click.echo(f"Markup written to {out_path}")


if __name__ == "__main__":
    cli()
