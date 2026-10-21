"""Command-line interface. Thin layer: parses input, calls services, prints."""

from __future__ import annotations

import argparse
import logging
import sys

from webscraper.container import Container, build_container
from webscraper.exporters import available_formats
from webscraper.models import ScrapedPage
from webscraper.services.sessions import SessionNotFound
from webscraper.storage import SessionSummary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="webscraper", description="Scrape the web for a keyword.")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="search a keyword, scrape results, stage them and export a file")
    s.add_argument("keyword", nargs="+", help="keyword or phrase to search for")
    s.add_argument("-n", "--limit", type=int, default=10, help="number of results (default 10)")
    s.add_argument("-f", "--format", choices=available_formats(), default="json")
    choice = s.add_mutually_exclusive_group()
    choice.add_argument("--save", action="store_true", help="save to the database without asking")
    choice.add_argument("--no-save", action="store_true", help="keep in staging only, don't ask")

    sub.add_parser("staged", help="list sessions waiting in the temporary DB")
    sub.add_parser("saved", help="list sessions in the permanent DB")

    p = sub.add_parser("save", help="move a staged session into the permanent DB")
    p.add_argument("session_id")

    d = sub.add_parser("discard", help="delete a staged session")
    d.add_argument("session_id")

    e = sub.add_parser("export", help="export a staged or saved session to a file")
    e.add_argument("session_id")
    e.add_argument("-f", "--format", choices=available_formats(), default="json")

    w = sub.add_parser("serve", help="start the web UI")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    app = build_container()
    app.sessions.purge_expired()

    try:
        return COMMANDS[args.command](app, args)
    except SessionNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130


def cmd_search(app: Container, args: argparse.Namespace) -> int:
    keyword = " ".join(args.keyword)
    print(f"Searching for {keyword!r} ({app.settings.search_provider}, up to {args.limit} results)...")

    try:
        session = app.scraper.run(keyword, limit=args.limit, on_page=_print_page)
    except Exception as exc:  # search provider failure: nothing to stage
        print(f"error: search failed: {exc}", file=sys.stderr)
        return 1
    if not session.pages:
        print("No results found.")
        return 1

    print(f"\nScraped {session.success_count}/{len(session.pages)} pages (results from {session.provider}).")
    print(f"Staged in temporary DB as session {session.id}")
    print(f"Exported to {app.sessions.export(session, args.format)}")

    if args.save or (not args.no_save and _confirm("Save this data to the database? [y/N] ")):
        app.sessions.promote(session.id)
        print(f"Saved to {app.settings.permanent_db_path}")
    else:
        print(
            f"Kept in staging only (auto-deleted after {app.settings.staging_ttl_hours}h). "
            f"Run `webscraper save {session.id}` to keep it."
        )
    return 0


def cmd_staged(app: Container, _: argparse.Namespace) -> int:
    _print_sessions(app.sessions.list_staged(), "No staged sessions.")
    return 0


def cmd_saved(app: Container, _: argparse.Namespace) -> int:
    _print_sessions(app.sessions.list_saved(), "No saved sessions.")
    return 0


def cmd_save(app: Container, args: argparse.Namespace) -> int:
    session = app.sessions.promote(args.session_id)
    print(f"Saved session {session.id} ({session.keyword!r}) to {app.settings.permanent_db_path}")
    return 0


def cmd_discard(app: Container, args: argparse.Namespace) -> int:
    if not app.sessions.discard(args.session_id):
        raise SessionNotFound(f"No staged session with id {args.session_id!r}")
    print(f"Discarded session {args.session_id}")
    return 0


def cmd_export(app: Container, args: argparse.Namespace) -> int:
    session = app.sessions.find(args.session_id)
    print(f"Exported to {app.sessions.export(session, args.format)}")
    return 0


def cmd_serve(app: Container, args: argparse.Namespace) -> int:
    import uvicorn

    from webscraper.web import create_app

    print(f"Webscraper UI running at http://{args.host}:{args.port}  (Ctrl+C to stop)")
    uvicorn.run(create_app(app), host=args.host, port=args.port, log_level="warning")
    return 0


COMMANDS = {
    "search": cmd_search,
    "staged": cmd_staged,
    "saved": cmd_saved,
    "save": cmd_save,
    "discard": cmd_discard,
    "export": cmd_export,
    "serve": cmd_serve,
}


def _print_page(page: ScrapedPage) -> None:
    status = "ok " if page.ok else "ERR"
    detail = page.title if page.ok else page.error
    print(f"  [{status}] #{page.rank:<2} {page.url}\n         {(detail or '')[:100]}")


def _print_sessions(rows: list[SessionSummary], empty: str) -> None:
    if not rows:
        print(empty)
        return
    for r in rows:
        print(f"{r.id}  {r.created_at:%Y-%m-%d %H:%M}  {r.page_count:>3} pages  {r.keyword}")


def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(prompt).strip().lower() in ("y", "yes")
