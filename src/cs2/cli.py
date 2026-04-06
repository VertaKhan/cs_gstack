from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cs2.config import ConfigError, load_settings
from cs2.engine.monitor import Monitor, MonitorCriteria
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
        "--format",
        choices=["rich", "json", "csv"],
        default="rich",
        dest="output_format",
        help="Output format: rich (default), json, csv",
    )
    analyze_parser.add_argument(
        "-o", "--output",
        default=None,
        dest="output_file",
        help="Write output to file instead of stdout",
    )
    analyze_parser.add_argument(
        "--offline",
        action="store_true",
        help="Use only cached data, no API calls",
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

    # compare subcommand
    compare_parser = subparsers.add_parser(
        "compare", help="Side-by-side comparison of two CS2 item listings"
    )
    compare_parser.add_argument("url1", help="First CSFloat or Steam Market URL")
    compare_parser.add_argument("url2", help="Second CSFloat or Steam Market URL")
    compare_parser.add_argument(
        "--offline",
        action="store_true",
        help="Use only cached data, no API calls",
    )
    compare_parser.add_argument(
        "--config", default=None, help="Path to config.toml"
    )
    compare_parser.add_argument(
        "--env", default=None, help="Path to .env file"
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

    # monitor subcommand
    monitor_parser = subparsers.add_parser(
        "monitor", help="Monitor CS2 listings for underpriced items"
    )
    monitor_parser.add_argument("--weapon", required=True, help="Weapon name (e.g. AK-47)")
    monitor_parser.add_argument("--skin", required=True, help="Skin name (e.g. Redline)")
    monitor_parser.add_argument(
        "--quality", default="FT", help="Quality (FN/MW/FT/WW/BS, default: FT)"
    )
    monitor_parser.add_argument(
        "--stattrak", action="store_true", help="StatTrak items only"
    )
    monitor_parser.add_argument(
        "--max-price", type=float, default=None, help="Maximum price filter"
    )
    monitor_parser.add_argument(
        "--min-margin", type=float, default=None,
        help="Minimum margin %% to alert (default from config: 15)"
    )
    monitor_parser.add_argument(
        "--interval", type=int, default=None,
        help="Seconds between checks (default from config: 300)"
    )
    monitor_parser.add_argument(
        "--config", default=None, help="Path to config.toml"
    )
    monitor_parser.add_argument(
        "--env", default=None, help="Path to .env file"
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "analyze":
        _run_analyze(args)
    elif args.command == "compare":
        _run_compare(args)
    elif args.command == "history":
        _run_history(args)
    elif args.command == "portfolio":
        _run_portfolio(args)
    elif args.command == "monitor":
        _run_monitor(args)


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
    offline = args.offline
    conn = get_connection()
    cache = CacheStore(conn)
    logger = DecisionLogger(conn)
    pipeline = Pipeline(settings, cache, logger, offline=offline)

    if offline:
        console.print(
            "[yellow bold]\u26a0 OFFLINE MODE \u2014 using cached data only (may be stale)[/yellow bold]"
        )

    fmt = args.output_format

    try:
        # Batch mode: argument is a file path
        if args.url and os.path.isfile(args.url):
            _run_batch(args.url, pipeline, fmt, args.output_file)
        elif args.url:
            result = pipeline.analyze_url(args.url)
            for w in result.warnings:
                console.print(f"[yellow]Warning:[/yellow] {w}")
            _output_result([result], fmt, args.output_file)
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
            _output_result([result], fmt, args.output_file)
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


def _result_to_dict(result: PipelineResult) -> dict:
    """Convert a PipelineResult to a flat export dict."""
    decision = result.decision
    canonical = result.canonical
    pricing = result.pricing

    item_name = canonical.weapon
    if canonical.skin:
        item_name += f" | {canonical.skin}"
    if canonical.quality:
        item_name += f" ({canonical.quality})"
    if canonical.stattrak:
        item_name = f"StatTrak\u2122 {item_name}"

    d: dict = {
        "item": item_name,
        "action": decision.action.value,
        "confidence": decision.confidence,
        "listing_price": decision.listing_price,
        "estimated_value": decision.estimated_value,
        "margin_pct": decision.margin_pct,
        "safe_exit_price": decision.safe_exit_price,
        "reasons": decision.reasons,
        "risk_flags": decision.risk_flags,
        "base_price": pricing.base_price if pricing else 0.0,
        "item_class": pricing.item_class.value if pricing else "unknown",
        "liquidity_grade": result.liquidity.grade.value if result.liquidity else "unknown",
    }
    if pricing and pricing.premium_breakdown:
        d["premium_breakdown"] = pricing.premium_breakdown
    return d


_CSV_COLUMNS = [
    "item", "action", "confidence", "listing_price", "estimated_value",
    "margin_pct", "safe_exit_price", "base_price", "item_class", "liquidity_grade",
]


def _format_json(results: list[PipelineResult]) -> str:
    """Format results as JSON string."""
    data = [_result_to_dict(r) for r in results]
    if len(data) == 1:
        return json.dumps(data[0], indent=2, ensure_ascii=False)
    return json.dumps(data, indent=2, ensure_ascii=False)


def _format_csv(results: list[PipelineResult]) -> str:
    """Format results as CSV string."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in results:
        writer.writerow(_result_to_dict(r))
    return buf.getvalue()


def _output_result(
    results: list[PipelineResult],
    fmt: str,
    output_file: str | None,
) -> None:
    """Route output to the right formatter/destination."""
    if fmt == "json":
        text = _format_json(results)
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(text + "\n")
        else:
            print(text)
    elif fmt == "csv":
        text = _format_csv(results)
        if output_file:
            with open(output_file, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        else:
            sys.stdout.write(text)
    else:
        for r in results:
            _render_decision_card(r)


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


def _run_batch(
    file_path: str,
    pipeline: Pipeline,
    fmt: str = "rich",
    output_file: str | None = None,
) -> None:
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
                if fmt == "rich":
                    _render_decision_card(result)
            except (PipelineError, Exception) as exc:
                results.append((url, None, str(exc)))
                console.print(f"[red]Error analyzing {url}:[/red] {exc}")

    successful = [r for _, r, e in results if r is not None]
    if fmt != "rich" and successful:
        _output_result(successful, fmt, output_file)
    elif fmt == "rich":
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


def _run_compare(args: argparse.Namespace) -> None:
    """Execute the compare command --- side-by-side analysis of two items."""
    try:
        settings = load_settings(
            config_path=args.config,
            env_path=args.env,
        )
    except ConfigError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        sys.exit(1)

    offline = args.offline
    conn = get_connection()
    cache = CacheStore(conn)
    logger = DecisionLogger(conn)
    pipeline = Pipeline(settings, cache, logger, offline=offline)

    if offline:
        console.print(
            "[yellow bold]\u26a0 OFFLINE MODE \u2014 using cached data only (may be stale)[/yellow bold]"
        )

    result1: PipelineResult | None = None
    result2: PipelineResult | None = None
    error1: str | None = None
    error2: str | None = None

    try:
        try:
            result1 = pipeline.analyze_url(args.url1)
        except (PipelineError, Exception) as exc:
            error1 = str(exc)

        try:
            result2 = pipeline.analyze_url(args.url2)
        except (PipelineError, Exception) as exc:
            error2 = str(exc)
    finally:
        pipeline.close()
        conn.close()

    if error1 and error2:
        console.print(f"[red]Error analyzing Item 1:[/red] {error1}")
        console.print(f"[red]Error analyzing Item 2:[/red] {error2}")
        sys.exit(1)

    if error1:
        console.print(f"[yellow]Could not analyze Item 1:[/yellow] {error1}")
        console.print()
        assert result2 is not None
        _render_decision_card(result2)
        return

    if error2:
        console.print(f"[yellow]Could not analyze Item 2:[/yellow] {error2}")
        console.print()
        assert result1 is not None
        _render_decision_card(result1)
        return

    assert result1 is not None and result2 is not None
    _render_comparison(result1, result2)


def _item_label(result: PipelineResult) -> str:
    """Build a short item label from a PipelineResult."""
    c = result.canonical
    label = c.weapon
    if c.skin:
        label += f" {c.skin}"
    if c.quality:
        label += f" {c.quality}"
    return label


def _compare_recommendation(r1: PipelineResult, r2: PipelineResult) -> str:
    """Pick the better item. Returns recommendation string."""
    from cs2.models.liquidity import LiquidityGrade

    d1, d2 = r1.decision, r2.decision

    action_rank = {DecisionAction.BUY: 2, DecisionAction.REVIEW: 1, DecisionAction.NO_BUY: 0}
    rank1 = action_rank[d1.action]
    rank2 = action_rank[d2.action]

    if rank1 != rank2:
        winner = 1 if rank1 > rank2 else 2
        reason = "better action verdict"
    elif d1.confidence != d2.confidence:
        winner = 1 if d1.confidence > d2.confidence else 2
        reason = "higher confidence"
    elif d1.margin_pct != d2.margin_pct:
        winner = 1 if d1.margin_pct > d2.margin_pct else 2
        reason = "higher margin"
    else:
        liq_rank = {
            LiquidityGrade.HIGH: 3,
            LiquidityGrade.MEDIUM: 2,
            LiquidityGrade.LOW: 1,
            LiquidityGrade.UNKNOWN: 0,
        }
        g1 = r1.liquidity.grade if r1.liquidity else LiquidityGrade.UNKNOWN
        g2 = r2.liquidity.grade if r2.liquidity else LiquidityGrade.UNKNOWN
        if liq_rank[g1] != liq_rank[g2]:
            winner = 1 if liq_rank[g1] > liq_rank[g2] else 2
            reason = "better liquidity"
        else:
            return "Tie -- both items are equivalent"

    winner_result = r1 if winner == 1 else r2
    return f"Item {winner} ({_item_label(winner_result)}) -- {reason}"


def _render_comparison(r1: PipelineResult, r2: PipelineResult) -> None:
    """Render side-by-side Rich comparison table."""
    d1, d2 = r1.decision, r2.decision
    label1, label2 = _item_label(r1), _item_label(r2)

    action_colors = {
        DecisionAction.BUY: "green",
        DecisionAction.NO_BUY: "red",
        DecisionAction.REVIEW: "yellow",
    }

    table = Table(title="Comparison", show_lines=True, padding=(0, 1))
    table.add_column("", min_width=16, style="bold")
    table.add_column("Item 1", min_width=18)
    table.add_column("Item 2", min_width=18)

    table.add_row("Item", label1, label2)
    table.add_row(
        "Listing Price",
        f"${d1.listing_price:.2f}",
        f"${d2.listing_price:.2f}",
    )
    table.add_row(
        "Estimated Value",
        f"${d1.estimated_value:.2f}",
        f"${d2.estimated_value:.2f}",
    )

    m1_sign = "+" if d1.margin_pct >= 0 else ""
    m2_sign = "+" if d2.margin_pct >= 0 else ""
    table.add_row(
        "Margin",
        f"{m1_sign}{d1.margin_pct:.1f}%",
        f"{m2_sign}{d2.margin_pct:.1f}%",
    )

    table.add_row(
        "Safe Exit",
        f"${d1.safe_exit_price:.2f}",
        f"${d2.safe_exit_price:.2f}",
    )

    liq1 = r1.liquidity.grade.value.upper() if r1.liquidity else "N/A"
    liq2 = r2.liquidity.grade.value.upper() if r2.liquidity else "N/A"
    table.add_row("Liquidity", liq1, liq2)

    table.add_row(
        "Confidence",
        f"{int(d1.confidence * 100)}%",
        f"{int(d2.confidence * 100)}%",
    )

    c1 = action_colors[d1.action]
    c2 = action_colors[d2.action]
    table.add_row(
        "Action",
        f"[{c1}]{d1.action.value.upper()}[/{c1}]",
        f"[{c2}]{d2.action.value.upper()}[/{c2}]",
    )

    console.print()
    console.print(table)

    rec = _compare_recommendation(r1, r2)
    console.print()
    console.print(f"[bold]RECOMMENDATION:[/bold] {rec}")


def _run_monitor(args: argparse.Namespace) -> None:
    """Execute the monitor command."""
    try:
        settings = load_settings(
            config_path=args.config,
            env_path=args.env,
        )
    except ConfigError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        sys.exit(1)

    # Resolve quality alias
    from cs2.engine.identity import _normalize_quality
    quality = _normalize_quality(args.quality)

    # Read monitor defaults from config
    monitor_config = _load_monitor_config(args.config)
    interval = args.interval or monitor_config.get("default_interval", 300)
    min_margin = args.min_margin if args.min_margin is not None else monitor_config.get("default_min_margin", 15.0)

    criteria = MonitorCriteria(
        weapon=args.weapon,
        skin=args.skin,
        quality=quality,
        stattrak=args.stattrak,
        max_price=args.max_price,
        min_margin=min_margin,
    )

    conn = get_connection()
    cache = CacheStore(conn)
    logger = DecisionLogger(conn)

    try:
        monitor = Monitor(
            criteria=criteria,
            settings=settings,
            cache=cache,
            logger=logger,
            interval=interval,
        )
        monitor.run()
    finally:
        conn.close()


def _load_monitor_config(config_path: str | None) -> dict:
    """Load [monitor] section from config.toml."""
    from pathlib import Path

    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    if config_path is None:
        config_path_obj = Path.cwd() / "config.toml"
    else:
        config_path_obj = Path(config_path)

    if not config_path_obj.exists():
        return {}

    try:
        with open(config_path_obj, "rb") as f:
            data = tomllib.load(f)
        return data.get("monitor", {})
    except Exception:
        return {}
