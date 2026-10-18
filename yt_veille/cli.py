"""Interface en ligne de commande de YT Veille.

Exemples :
    yt-veille init-db
    yt-veille seed
    yt-veille domains
    yt-veille collect --domain ia
    yt-veille collect              # tous les domaines actifs
    yt-veille top --domain ia --limit 10
    yt-veille report --domain ia
    yt-veille export --domain ia --format xlsx
    yt-veille quota
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from . import __version__
from .collector import collect_all, latest_scores, quota_today
from .config import get_settings
from .db import init_db, session_scope
from .models import Domain, Keyword
from .reports import export_rows, rows_for_domain, write_markdown_report
from .youtube import YouTubeClient

console = Console()
EXPORTS_DIR = Path("exports")
REPORTS_DIR = Path("reports")
DAILY_QUOTA = 10_000


# ─────────────────────────────────────────────────────────────
#  Commandes
# ─────────────────────────────────────────────────────────────
def cmd_init_db(_args: argparse.Namespace) -> int:
    init_db()
    console.print("[green]✓[/] Base de données initialisée.")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    init_db()
    path = Path(args.file)
    if not path.exists():
        console.print(f"[red]Fichier introuvable :[/] {path}")
        return 1
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    created_domains = created_keywords = 0
    with session_scope() as session:
        for entry in data.get("domains", []):
            slug = entry["slug"]
            domain = session.query(Domain).filter_by(slug=slug).one_or_none()
            if domain is None:
                domain = Domain(
                    slug=slug,
                    name=entry["name"],
                    description=entry.get("description", ""),
                )
                session.add(domain)
                session.flush()
                created_domains += 1
            existing = {k.term for k in domain.keywords}
            for term in entry.get("keywords", []):
                if term not in existing:
                    session.add(Keyword(domain_id=domain.id, term=term))
                    created_keywords += 1
    console.print(
        f"[green]✓[/] Seed terminé : {created_domains} domaine(s) et "
        f"{created_keywords} mot(s)-clé(s) créés."
    )
    return 0


def cmd_domains(_args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        domains = session.query(Domain).order_by(Domain.slug).all()
        if not domains:
            console.print("[yellow]Aucun domaine. Lance « yt-veille seed ».[/]")
            return 0
        table = Table(title="Domaines")
        table.add_column("slug")
        table.add_column("nom")
        table.add_column("actif", justify="center")
        table.add_column("mots-clés", justify="right")
        for d in domains:
            table.add_row(d.slug, d.name, "✓" if d.is_active else "✗", str(len(d.keywords)))
        console.print(table)
    return 0


def cmd_add_domain(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        if session.query(Domain).filter_by(slug=args.slug).one_or_none():
            console.print(f"[red]Le domaine « {args.slug} » existe déjà.[/]")
            return 1
        session.add(Domain(slug=args.slug, name=args.name, description=args.description or ""))
    console.print(f"[green]✓[/] Domaine « {args.slug} » créé.")
    return 0


def cmd_add_keyword(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        domain = session.query(Domain).filter_by(slug=args.domain).one_or_none()
        if domain is None:
            console.print(f"[red]Domaine inconnu :[/] {args.domain}")
            return 1
        if session.query(Keyword).filter_by(domain_id=domain.id, term=args.term).one_or_none():
            console.print("[yellow]Ce mot-clé existe déjà.[/]")
            return 0
        session.add(Keyword(domain_id=domain.id, term=args.term))
    console.print(f"[green]✓[/] Mot-clé « {args.term} » ajouté à « {args.domain} ».")
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    init_db()
    settings = get_settings()
    with session_scope() as session:
        with YouTubeClient(settings.youtube_api_key) as client:
            collections = collect_all(
                session,
                client,
                domain_slug=args.domain,
                freshness_days=args.days,
                max_results=args.max,
                order=args.order,
            )
            table = Table(title="Collecte")
            table.add_column("domaine")
            table.add_column("statut")
            table.add_column("vidéos", justify="right")
            table.add_column("unités", justify="right")
            table.add_column("erreur")
            for coll in collections:
                domain = session.get(Domain, coll.domain_id)
                status = "[green]ok[/]" if coll.status == "ok" else f"[red]{coll.status}[/]"
                table.add_row(
                    domain.slug if domain else str(coll.domain_id),
                    status,
                    str(coll.videos_found),
                    str(coll.api_units_used),
                    (coll.error_message or "")[:60],
                )
            console.print(table)

            usage = quota_today(session)
            console.print(
                f"Quota du jour : [bold]{usage.units_used}[/] / {DAILY_QUOTA} unités "
                f"({usage.requests_count} requêtes)."
            )
    return 0


def cmd_top(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        domain = session.query(Domain).filter_by(slug=args.domain).one_or_none()
        if domain is None:
            console.print(f"[red]Domaine inconnu :[/] {args.domain}")
            return 1
        rows = rows_for_domain(session, domain, limit=args.limit)
        if not rows:
            console.print("[yellow]Aucune vidéo. Lance une collecte.[/]")
            return 0
        table = Table(title=f"Top {len(rows)} — {domain.name}")
        table.add_column("#", justify="right")
        table.add_column("score", justify="right")
        table.add_column("titre", overflow="ellipsis", max_width=48)
        table.add_column("chaîne", overflow="ellipsis", max_width=20)
        table.add_column("vues", justify="right")
        table.add_column("âge(j)", justify="right")
        for r in rows:
            table.add_row(
                str(r["rank"]),
                f"{r['score_total']:.3f}",
                r["title"],
                r["channel"],
                f"{r['view_count']:,}",
                str(r["age_days"]),
            )
        console.print(table)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    init_db()
    settings = get_settings()
    with session_scope() as session:
        domain = session.query(Domain).filter_by(slug=args.domain).one_or_none()
        if domain is None:
            console.print(f"[red]Domaine inconnu :[/] {args.domain}")
            return 1
        path = write_markdown_report(
            session, domain, REPORTS_DIR, limit=args.limit, freshness_days=settings.freshness_days
        )
    console.print(f"[green]✓[/] Rapport écrit : {path}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        domain = session.query(Domain).filter_by(slug=args.domain).one_or_none()
        if domain is None:
            console.print(f"[red]Domaine inconnu :[/] {args.domain}")
            return 1
        rows = rows_for_domain(session, domain, limit=args.limit)
        if not rows:
            console.print("[yellow]Aucune donnée à exporter.[/]")
            return 0
        out = Path(args.out) if args.out else EXPORTS_DIR / f"{domain.slug}.{args.format}"
        path = export_rows(rows, args.format, out)
    console.print(f"[green]✓[/] Export écrit : {path} ({len(rows)} lignes)")
    return 0


def cmd_quota(_args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        usage = quota_today(session)
        pct = usage.units_used / DAILY_QUOTA * 100
        color = "green" if pct < 70 else "yellow" if pct < 90 else "red"
        console.print(
            f"Quota YouTube aujourd'hui : [bold {color}]{usage.units_used}[/] / {DAILY_QUOTA} "
            f"unités ({pct:.1f} %) — {usage.requests_count} requêtes."
        )
    return 0


# ─────────────────────────────────────────────────────────────
#  Parseur d'arguments
# ─────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-veille",
        description="Veille des meilleures vidéos YouTube par domaine.",
    )
    parser.add_argument("--version", action="version", version=f"yt-veille {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Créer les tables").set_defaults(func=cmd_init_db)

    p_seed = sub.add_parser("seed", help="Importer les domaines depuis un fichier YAML")
    p_seed.add_argument("--file", default="seed.yml", help="Chemin du fichier (défaut : seed.yml)")
    p_seed.set_defaults(func=cmd_seed)

    sub.add_parser("domains", help="Lister les domaines").set_defaults(func=cmd_domains)

    p_add = sub.add_parser("add-domain", help="Créer un domaine")
    p_add.add_argument("--slug", required=True)
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--description", default="")
    p_add.set_defaults(func=cmd_add_domain)

    p_kw = sub.add_parser("add-keyword", help="Ajouter un mot-clé à un domaine")
    p_kw.add_argument("--domain", required=True)
    p_kw.add_argument("--term", required=True)
    p_kw.set_defaults(func=cmd_add_keyword)

    p_collect = sub.add_parser("collect", help="Lancer une collecte")
    p_collect.add_argument("--domain", help="Slug d'un domaine (sinon : tous les actifs)")
    p_collect.add_argument("--days", type=int, help="Fenêtre de fraîcheur en jours")
    p_collect.add_argument("--max", type=int, help="Résultats max par mot-clé (1–50)")
    p_collect.add_argument(
        "--order", help="Tri YouTube : relevance | viewCount | date | rating"
    )
    p_collect.set_defaults(func=cmd_collect)

    p_top = sub.add_parser("top", help="Afficher le classement d'un domaine")
    p_top.add_argument("--domain", required=True)
    p_top.add_argument("--limit", type=int, default=15)
    p_top.set_defaults(func=cmd_top)

    p_report = sub.add_parser("report", help="Générer le rapport Markdown d'un domaine")
    p_report.add_argument("--domain", required=True)
    p_report.add_argument("--limit", type=int, default=10)
    p_report.set_defaults(func=cmd_report)

    p_export = sub.add_parser("export", help="Exporter les données d'un domaine")
    p_export.add_argument("--domain", required=True)
    p_export.add_argument("--format", default="csv", choices=["csv", "json", "xlsx"])
    p_export.add_argument("--out", help="Chemin de sortie (optionnel)")
    p_export.add_argument("--limit", type=int, default=None)
    p_export.set_defaults(func=cmd_export)

    sub.add_parser("quota", help="Afficher le quota API utilisé aujourd'hui").set_defaults(
        func=cmd_quota
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # message d'erreur lisible plutôt qu'une trace brute
        console.print(f"[red]Erreur :[/] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
