#!/usr/bin/env python3
"""Goshippro ➜ Discord Formatter
==================================

This script converts raw Goshippro/1688 listings into Markdown ready for Discord posts.
"""

import re
import sys
import textwrap
from pathlib import Path
from typing import Dict, List

COUNTRY_ORDER = [
    ("USA", "🇺🇸"),
    ("UK", "🇬🇧"),
    ("DE", "🇩🇪"),
    ("AU", "🇦🇺"),
]

TEMPLATE_MD = textwrap.dedent(
    """{emoji} **{name}**\n{date_line}\n\n💰 **Precio (producto + envío)**\n{price_lines}\n\n📦 **Logística**\n- Peso bruto: {weight}\n- Tránsito: {ship_times}\n\n{metrics_section}\n🔑 Keyword 1688: `{keyword}`"""
)

SEPARATOR = "―"  # U+2015

price_re = re.compile(r"\$([0-9.]+) to ([A-Z]{2})")
profit_re = re.compile(r"\$([0-9.]+)")
margin_re = re.compile(r"([0-9.]+)%")
shipping_re = re.compile(r"To ([A-Z]{2,3}): ([0-9\\-]+ days)")


def infer_type_emoji(raw_header: str) -> str:
    """Return 🔔 for Daily, 🔥 for Dropshipper, 🙂 otherwise."""
    if "Daily" in raw_header:
        return "🔔"
    if "Dropshipper" in raw_header or "Dropshippers" in raw_header:
        return "🔥"
    return "🙂"


def parse_prices(line: str) -> Dict[str, str]:
    prices: Dict[str, str] = {}
    for price, country in price_re.findall(line):
        prices[country] = price
    return prices


def parse_shipping(line: str) -> Dict[str, str]:
    ship: Dict[str, str] = {}
    for country, days in shipping_re.findall(line):
        ship[country] = days
    return ship


def parse_profits(line: str) -> List[str]:
    return profit_re.findall(line)


def parse_margins(line: str) -> List[str]:
    return margin_re.findall(line)


def parse_block(raw: str) -> str:
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        return ""

    header = lines[0]
    emoji = infer_type_emoji(header[0]) if header and header[0] in "🔔🔥🙂" else infer_type_emoji(header)

    name = re.sub(r"^[^A-Za-z0-9]+", "", header)
    date_match = re.search(r"(\d{4}/\d{2}/\d{2})", header)
    date_line = "*" + date_match.group(1).replace("/", "-") + "*" if date_match else ""

    prices = {}
    profits = []
    margins = []
    weight = "? kg"
    orders_line = ""
    rrp = ""
    ship_times = {}
    keyword = ""

    for line in lines[1:]:
        if "Goshippro Price" in line:
            prices = parse_prices(line)
        elif line.startswith("Gross Weight"):
            weight = line.split(":", 1)[1].strip()
        elif "Orders" in line or "Units Sold" in line:
            orders_line = line.split(":", 1)[1].strip()
        elif line.startswith("Profit Per Unit"):
            profits = parse_profits(line)
        elif line.startswith("Profit Margin"):
            margins = parse_margins(line)
        elif line.startswith("Recommended Retail Price"):
            rrp = line.split(":", 1)[1].strip()
        elif line.startswith("To USA"):
            ship_times = parse_shipping(line)
        elif line.startswith("Keyword"):
            keyword = line.split(":", 1)[1].strip()

    price_lines = []
    for idx, (code, flag) in enumerate(COUNTRY_ORDER):
        if code in prices:
            extra = ""
            if profits:
                extra += f" (💸 ${profits[idx]}"
                if margins:
                    extra += f" • {margins[idx]}%)"
                else:
                    extra += ")"
            price_lines.append(f"- {flag} {code}: **${prices[code]}**{extra}")
    price_lines = "\n".join(price_lines)

    ship_parts = []
    for code in ["USA", "EU", "AU"]:
        days = ship_times.get(code)
        if days:
            ship_parts.append(f"{code} {days}")
    ship_times_str = " · ".join(ship_parts) if ship_parts else "?"

    metrics_lines = []
    if orders_line:
        metrics_lines.append(f"- {orders_line}")
    if rrp:
        metrics_lines.append(f"- PVP recomendado: **{rrp}**")
    metrics_section = "📊 **Métricas**\n" + "\n".join(metrics_lines) + "\n\n" if metrics_lines else ""

    md = TEMPLATE_MD.format(
        emoji=emoji,
        name=name.strip(),
        date_line=date_line,
        price_lines=price_lines,
        weight=weight,
        ship_times=ship_times_str,
        metrics_section=metrics_section,
        keyword=keyword,
    )
    return md


def main(argv: List[str]):
    raw_text = Path(argv[1]).read_text() if len(argv) > 1 else sys.stdin.read()
    blocks = re.split(r"\n\s*\n", raw_text.strip())
    formatted_blocks = [parse_block(b) for b in blocks if b.strip()]
    output = f"\n{SEPARATOR}\n".join(formatted_blocks)
    print(output)


if __name__ == "__main__":
    main(sys.argv)
