from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from cs2.config import ConfigError, load_settings
from cs2.models.decision import DecisionAction
from cs2.pipeline import Pipeline, PipelineError, PipelineResult
from cs2.storage.cache import CacheStore
from cs2.storage.database import get_connection
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

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "analyze":
        _run_analyze(args)


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
        if args.url:
            result = pipeline.analyze_url(args.url)
        elif args.weapon and args.skin and args.quality:
            result = pipeline.analyze_manual(
                weapon=args.weapon,
                skin=args.skin,
                quality=args.quality,
                float_value=args.float_value,
                stattrak=args.stattrak,
            )
        else:
            console.print(
                "[red]Error:[/red] Provide a URL or --weapon/--skin/--quality",
                style="bold",
            )
            sys.exit(1)

        # Show warnings
        for w in result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {w}")

        # Render decision card
        _render_decision_card(result)

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
