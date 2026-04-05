from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cs2.config import ConfigError, load_settings
from cs2.models.decision import DecisionAction
from cs2.pipeline import Pipeline, PipelineError, PipelineResult
from cs2.storage.cache import CacheStore
from cs2.engine.identity import InvalidItemError, resolve_identity
from cs2.storage.database import (
    get_connection,
    query_price_history,
    add_portfolio_item,
    list_portfolio_items,
    sell_portfolio_item,
    portfolio_summary,
)
from cs2.storage.logger import DecisionLogger


console = Console()


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="cs2",
        description="CS2 Skins Analysis System — buy/no-buy/review decisions",
    )
    subparsers = parser.add_subparsers(dest="command")

    # analyze subcommand
    analyze_parser = subparsers.add_parser(
        "analyze", help="Analyze a CS2 item listing"
    )
    analyze_parser.add_argument(
        "url", nargs="?", default=None, help="CSFloat or Steam Market URL"
    )
    analyze_parser.add_argument("--weapon", help="Weapon name (e.g. AK-47)")
    analyze_parser.add_argument("--skin", help="Skin name (e.g. Redline)")
    analyze_parser.add_argument(
        "--quality", help="Quality (FN/MW/FT/WW/BS or full name)"
    )
    analyze_parser.add_argument("--float", type=float, dest="float_value", help="Float value")
    analyze_parser.add_argument(
        "--stattrak", action="store_true", help="StatTrak item"
    )
    analyze_parser.add_argument(
        "--config", default=None, help="Path to config.toml"
    )
    analyze_parser.add_argument(
        "--env", default=None, help="Path to .env file"
    )

    # history subcommand
    history_parser = subparsers.add_parser(
        "history", help="Show price history for a CS2 item"
    )
    history_parser.add_argument(
        "item_name", help='Item name, e.g. "AK-47 Redline FT" or "AK-47 | Redline (Field-Tested)"'
    )
    history_parser.add_argument(
        "--days", type=int, default=30, help="Number of days to look back (default: 30)"
    )
    history_parser.add_argument(
        "--limit", type=int, default=50, help="Maximum rows to display (default: 50)"
    )

    # portfolio subcommand
    portfolio_parser = subparsers.add_parser(
        "portfolio", help="Track your CS2 skin inventory"
    )
    portfolio_sub = portfolio_parser.add_subparsers(dest="portfolio_action")

    # portfolio add
    port_add = portfolio_sub.add_parser("add", help="Add item to portfolio")
    port_add.add_argument("item_name", help='Item name, e.g. "AK-47 Redline FT"')
    port_add.add_argument("--price", type=float, required=True, help="Purchase price")
    port_add.add_argument("--float", type=float, dest="float_value", help="Float value")
    port_add.add_argument("--source", help='Source: csfloat, steam, manual')
    port_add.add_argument("--notes", help="Additional notes")

    # portfolio list
    port_list = portfolio_sub.add_parser("list", help="List portfolio items")
    port_list.add_argument("--all", action="store_true", dest="show_all", help="Include sold items")

    # portfolio sell
    port_sell = portfolio_sub.add_parser("sell", help="Mark item as sold")
    port_sell.add_argument("item_id", type=int, help="Item ID to mark as sold")
    port_sell.add_argument("--price", type=float, required=True, help="Sell price")

    # portfolio value
    portfolio_sub.add_parser("value", help="Portfolio summary and P&L")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "analyze":
        _run_analyze(args)
    elif args.command == "history":
        _run_history(args)
    elif args.command == "portfolio":
        _run_portfolio(args)


def _run_analyze(args: argparse.Namespace) -> None:
    """Execute the analyze command."""
    try:
        settings = load_settings(
            config_path=args.config,
            env_path=args.env,
        )
    except ConfigError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        sys.exit(1)
    conn = get_connection()
    cache = CacheStore(conn)
    logger = DecisionLogger(conn)
    pipeline = Pipeline(settings, cache, logger)

    try:
        # Batch mode: argument is a file path
        if args.url and os.path.isfile(args.url):
            _run_batch(args.url, pipeline)
        elif args.url:
            result = pipeline.analyze_url(args.url)
            for w in result.warnings:
                console.print(f"[yellow]Warning:[/yellow] {w}")
            _render_decision_card(result)
        elif args.weapon and args.skin and args.quality:
            result = pipeline.analyze_manual(
                weapon=args.weapon,
                skin=args.skin,
                quality=args.quality,
                float_value=args.float_value,
                stattrak=args.stattrak,
            )
            for w in result.warnings:
                console.print(f"[yellow]Warning:[/yellow] {w}")
            _render_decision_card(result)
        else:
            console.print(
                "[red]Error:[/red] Provide a URL or --weapon/--skin/--quality",
                style="bold",
            )
            sys.exit(1)

    except PipelineError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    finally:
        pipeline.close()
        conn.close()


def _render_decision_card(result: PipelineResult) -> None:
    """Render Rich decision card panel."""
    decision = result.decision
    canonical = result.canonical
    instance = result.instance
    pricing = result.pricing

    # Title color based on action
    action_colors = {
        DecisionAction.BUY: "green",
        DecisionAction.NO_BUY: "red",
        DecisionAction.REVIEW: "yellow",
    }
    color = action_colors[decision.action]
    title = f"CS2 Analysis --- {decision.action.value.upper()}"

    # Build card body
    lines: list[str] = []

    # Item identity
    item_line = f"{canonical.weapon}"
    if canonical.skin:
        item_line += f" | {canonical.skin}"
    if canonical.quality:
        item_line += f" | {canonical.quality}"
    lines.append(item_line)

    # Exact details
    if instance:
        details = f"Float: {instance.float_value:.4f}  Pattern: {instance.paint_seed}"
        details += f"  StatTrak: {'Yes' if canonical.stattrak else 'No'}"
        lines.append(details)
        if instance.stickers:
            sticker_strs = []
            for s in instance.stickers:
                st = s.name
                if s.wear > 0.8:
                    st += " (scratched)"
                st += f" [pos {s.slot}]"
                sticker_strs.append(st)
            lines.append(f"Stickers: {', '.join(sticker_strs)}")
    lines.append("")

    # Pricing
    margin_sign = "+" if decision.margin_pct >= 0 else ""
    lines.append(f"Listing Price:    ${decision.listing_price:.2f}")
    lines.append(
        f"Estimated Value:  ${decision.estimated_value:.2f}  "
        f"({margin_sign}{decision.margin_pct:.1f}%)"
    )

    safe_margin = 0.0
    if decision.listing_price > 0:
        safe_margin = (
            (decision.safe_exit_price - decision.listing_price)
            / decision.listing_price
            * 100
        )
    safe_sign = "+" if safe_margin >= 0 else ""
    lines.append(
        f"Safe Exit:        ${decision.safe_exit_price:.2f}   "
        f"({safe_sign}{safe_margin:.1f}%)"
    )
    lines.append("")

    # Premium breakdown
    if pricing and pricing.premium_breakdown:
        lines.append(f"  Base Price:     ${pricing.base_price:.2f}")
        for key, val in pricing.premium_breakdown.items():
            sign = "+" if val >= 0 else ""
            label = key.replace("_", " ").title()
            lines.append(f"  {label}: {sign}${val:.2f}")
        lines.append("")

    # Liquidity
    if result.liquidity:
        liq = result.liquidity
        lines.append(
            f"Liquidity: {liq.grade.value.upper()} "
            f"({liq.avg_daily_volume}/day, {liq.avg_spread_pct:.1f}% spread)"
        )

    # Confidence
    lines.append(f"Confidence: {int(decision.confidence * 100)}%")
    lines.append("")

    # Reasons
    for reason in decision.reasons:
        lines.append(f"  {reason}")

    # Risk flags
    for flag in decision.risk_flags:
        lines.append(f"  ! {flag}")

    body = "\n".join(lines)
    panel = Panel(
        body,
        title=title,
        border_style=color,
        padding=(1, 2),
    )
    console.print(panel)


def _read_urls_from_file(file_path: str) -> list[str]:
    """Read URLs from a file, skipping empty lines and comments."""
    urls: list[str] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                urls.append(stripped)
    return urls


def _run_batch(file_path: str, pipeline: Pipeline) -> None:
    """Run batch analysis from a file of URLs."""
    urls = _read_urls_from_file(file_path)
    if not urls:
        console.print("[yellow]No URLs found in file.[/yellow]")
        return

    total = len(urls)
    console.print(f"\n[bold]Batch analysis: {total} item(s)[/bold]\n")

    # Each entry: (url, result_or_none, error_or_none)
    results: list[tuple[str, PipelineResult | None, str | None]] = []

    for i, url in enumerate(urls, 1):
        with console.status(f"Analyzing {i}/{total}: {url}..."):
            try:
                result = pipeline.analyze_url(url)
                results.append((url, result, None))
                for w in result.warnings:
                    console.print(f"[yellow]Warning:[/yellow] {w}")
                _render_decision_card(result)
            except (PipelineError, Exception) as exc:
                results.append((url, None, str(exc)))
                console.print(f"[red]Error analyzing {url}:[/red] {exc}")

    _render_batch_summary(results)


def _render_batch_summary(
    results: list[tuple[str, PipelineResult | None, str | None]],
) -> None:
    """Render a summary table after batch analysis."""
    table = Table(
        title=f"Batch Summary ({len(results)} items)",
        show_lines=True,
    )
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Item", min_width=20)
    table.add_column("Action", justify="center")
    table.add_column("Conf", justify="center")
    table.add_column("Margin", justify="right")

    action_colors = {
        DecisionAction.BUY: "green",
        DecisionAction.NO_BUY: "red",
        DecisionAction.REVIEW: "yellow",
    }

    for idx, (url, result, error) in enumerate(results, 1):
        if error is not None:
            table.add_row(
                str(idx),
                url,
                "[red]ERROR[/red]",
                "-",
                f"[red]{error[:40]}[/red]",
            )
        else:
            assert result is not None
            decision = result.decision
            canonical = result.canonical
            item_name = canonical.weapon
            if canonical.skin:
                item_name += f" {canonical.skin}"
            if canonical.quality:
                item_name += f" {canonical.quality}"

            color = action_colors[decision.action]
            margin_sign = "+" if decision.margin_pct >= 0 else ""
            table.add_row(
                str(idx),
                item_name,
                f"[{color}]{decision.action.value.upper()}[/{color}]",
                f"{int(decision.confidence * 100)}%",
                f"{margin_sign}{decision.margin_pct:.1f}%",
            )

    console.print()
    console.print(table)


def _run_history(args: argparse.Namespace) -> None:
    """Execute the history command."""
    # Resolve item identity from free-form name
    try:
        canonical = resolve_identity(args.item_name)
    except InvalidItemError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    conn = get_connection()
    try:
        rows = query_price_history(
            conn,
            weapon=canonical.weapon,
            skin=canonical.skin,
            quality=canonical.quality,
            stattrak=canonical.stattrak,
            days=args.days,
            limit=args.limit,
        )

        # Build item label
        label = canonical.weapon
        if canonical.skin:
            label += f" | {canonical.skin}"
        if canonical.quality:
            label += f" ({canonical.quality})"
        if canonical.stattrak:
            label = f"StatTrak\u2122 {label}"

        if not rows:
            console.print(
                f"[yellow]No price history found for {label} "
                f"(last {args.days} days).[/yellow]"
            )
            return

        # Build Rich table
        table = Table(title=f"Price History \u2014 {label} (last {args.days} days)")
        table.add_column("Date", style="cyan")
        table.add_column("Price", style="green", justify="right")
        table.add_column("Volume", justify="right")
        table.add_column("Source", style="dim")

        for row in rows:
            date_str = row["recorded_at"][:10] if row["recorded_at"] else "?"
            price_str = f"${row['price']:.2f}"
            volume_str = str(row["volume"]) if row["volume"] is not None else "-"
            table.add_row(date_str, price_str, volume_str, row["source"])

        console.print(table)

        # Summary stats
        prices = [r["price"] for r in rows]
        min_p = min(prices)
        max_p = max(prices)
        avg_p = sum(prices) / len(prices)
        current_p = prices[0]  # most recent (ordered DESC)

        # Trend: compare first half avg vs second half avg
        mid = len(prices) // 2
        if mid > 0:
            recent_avg = sum(prices[:mid]) / mid
            older_avg = sum(prices[mid:]) / (len(prices) - mid)
            if recent_avg > older_avg * 1.02:
                trend = "[green]\u2191 Up[/green]"
            elif recent_avg < older_avg * 0.98:
                trend = "[red]\u2193 Down[/red]"
            else:
                trend = "[yellow]\u2192 Stable[/yellow]"
        else:
            trend = "[dim]N/A[/dim]"

        console.print()
        console.print(
            f"  Min: [green]${min_p:.2f}[/green]  "
            f"Max: [red]${max_p:.2f}[/red]  "
            f"Avg: ${avg_p:.2f}  "
            f"Current: [bold]${current_p:.2f}[/bold]  "
            f"Trend: {trend}"
        )
        console.print(f"  Records: {len(rows)}")
    finally:
        conn.close()


def _run_portfolio(args: argparse.Namespace) -> None:
    """Execute portfolio subcommands."""
    action = getattr(args, "portfolio_action", None)
    if action is None:
        console.print("[red]Error:[/red] Specify a portfolio action: add, list, sell, value")
        sys.exit(1)

    conn = get_connection()
    try:
        if action == "add":
            _portfolio_add(conn, args)
        elif action == "list":
            _portfolio_list(conn, args)
        elif action == "sell":
            _portfolio_sell(conn, args)
        elif action == "value":
            _portfolio_value(conn)
    finally:
        conn.close()


def _portfolio_add(conn, args: argparse.Namespace) -> None:
    """Add item to portfolio."""
    try:
        canonical = resolve_identity(args.item_name)
    except InvalidItemError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    item_id = add_portfolio_item(
        conn,
        weapon=canonical.weapon,
        skin=canonical.skin,
        quality=canonical.quality,
        stattrak=canonical.stattrak,
        float_value=args.float_value,
        purchase_price=args.price,
        source=args.source,
        notes=args.notes,
    )

    label = canonical.weapon
    if canonical.skin:
        label += f" | {canonical.skin}"
    if canonical.quality:
        label += f" ({canonical.quality})"
    if canonical.stattrak:
        label = f"StatTrak\u2122 {label}"

    console.print(
        f"[green]Added[/green] {label} to portfolio "
        f"(ID: {item_id}, price: ${args.price:.2f})"
    )


def _portfolio_list(conn, args: argparse.Namespace) -> None:
    """List portfolio items."""
    active_only = not args.show_all
    items = list_portfolio_items(conn, active_only=active_only)

    if not items:
        console.print("[yellow]Portfolio is empty.[/yellow]")
        return

    title = "Portfolio" if active_only else "Portfolio (all items)"
    table = Table(title=title, show_lines=True)
    table.add_column("ID", justify="right", style="dim", width=4)
    table.add_column("Item", min_width=20)
    table.add_column("Float", justify="right", width=8)
    table.add_column("Buy Price", justify="right", style="green")
    table.add_column("Buy Date", style="cyan")
    table.add_column("Source", style="dim")
    table.add_column("Notes", max_width=20)
    table.add_column("Status", justify="center")

    for item in items:
        label = item["weapon"]
        if item["skin"]:
            label += f" | {item['skin']}"
        if item["quality"]:
            label += f" ({item['quality']})"
        if item["stattrak"]:
            label = f"ST {label}"

        float_str = f"{item['float_value']:.4f}" if item["float_value"] is not None else "-"
        notes_str = (item["notes"] or "")[:20]

        if item["sold_price"] is not None:
            pnl = item["sold_price"] - item["purchase_price"]
            pnl_color = "green" if pnl >= 0 else "red"
            sign = "+" if pnl >= 0 else ""
            status = f"[{pnl_color}]Sold ${item['sold_price']:.2f} ({sign}${pnl:.2f})[/{pnl_color}]"
        else:
            status = "[bold]Active[/bold]"

        table.add_row(
            str(item["id"]),
            label,
            float_str,
            f"${item['purchase_price']:.2f}",
            item["purchase_date"],
            item["source"] or "-",
            notes_str,
            status,
        )

    console.print(table)


def _portfolio_sell(conn, args: argparse.Namespace) -> None:
    """Mark a portfolio item as sold."""
    result = sell_portfolio_item(conn, args.item_id, args.price)
    if result is None:
        console.print(f"[red]Error:[/red] Item ID {args.item_id} not found")
        sys.exit(1)

    if result["sold_price"] is None:
        console.print(f"[red]Error:[/red] Item ID {args.item_id} was already sold or not found")
        sys.exit(1)

    pnl = result["sold_price"] - result["purchase_price"]
    pnl_color = "green" if pnl >= 0 else "red"
    sign = "+" if pnl >= 0 else ""

    label = result["weapon"]
    if result["skin"]:
        label += f" | {result['skin']}"

    console.print(
        f"[green]Sold[/green] {label} (ID: {args.item_id}) "
        f"for ${args.price:.2f} — "
        f"P&L: [{pnl_color}]{sign}${pnl:.2f}[/{pnl_color}]"
    )


def _portfolio_value(conn) -> None:
    """Show portfolio summary."""
    summary = portfolio_summary(conn)

    if summary["active_count"] == 0 and summary["sold_count"] == 0:
        console.print("[yellow]Portfolio is empty.[/yellow]")
        return

    lines: list[str] = []
    lines.append(f"Active Items:      {summary['active_count']}")
    lines.append(f"Active Invested:   ${summary['active_invested']:.2f}")
    lines.append("")
    lines.append(f"Sold Items:        {summary['sold_count']}")
    lines.append(f"Sold Cost Basis:   ${summary['sold_invested']:.2f}")
    lines.append(f"Sold Revenue:      ${summary['total_sold_revenue']:.2f}")

    pnl = summary["realized_pnl"]
    pnl_color = "green" if pnl >= 0 else "red"
    sign = "+" if pnl >= 0 else ""
    lines.append(f"Realized P&L:      [{pnl_color}]{sign}${pnl:.2f}[/{pnl_color}]")

    panel = Panel(
        "\n".join(lines),
        title="Portfolio Summary",
        border_style="blue",
        padding=(1, 2),
    )
    console.print(panel)
