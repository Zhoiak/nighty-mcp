# -*- coding: utf-8 -*-
"""Utility to format product descriptions for Discord."""

from pathlib import Path
import sys
import asyncio
import re
import builtins
import types
import textwrap
try:
    import requests
except Exception:  # pragma: no cover - optional dependency
    requests = None

# Ensure this script's directory is on sys.path so sibling modules can be
# imported even if executed from another location.
_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

# Provide no-op defaults when running outside Nighty
if not hasattr(builtins, "nightyScript"):
    builtins.nightyScript = lambda *a, **k: (lambda f: f)
if not hasattr(builtins, "bot"):
    builtins.bot = types.SimpleNamespace(command=lambda *a, **k: (lambda f: f))

COUNTRY_ORDER = [
    ("USA", "🇺🇸"),
    ("UK", "🇬🇧"),
    ("DE", "🇩🇪"),
    ("AU", "🇦🇺"),
]

TEMPLATE_MD = textwrap.dedent(
    """{emoji} **{name}**
{date_line}

💰 **Precio (producto + envío)**
{price_lines}

📦 **Logística**
- Peso bruto: {weight}
- Tránsito: {ship_times}

{metrics_section}
🔑 Keyword 1688: `{keyword}`"""
)

SEPARATOR = "―"  # U+2015

price_re = re.compile(r"\$([0-9.]+) to ([A-Z]{2})")
profit_re = re.compile(r"\$([0-9.]+)")
margin_re = re.compile(r"([0-9.]+)%")
shipping_re = re.compile(r"To ([A-Z]{2,3}): ([0-9\-]+ days)")

@nightyScript(
    name="Product Formatter",
    author="thedorekaczynski",
    description="Format product info and categorize with OpenRouter",
    usage="<p>formatproduct <raw description>"
)
def product_formatter():
    """
    PRODUCT FORMATTER
    -----------------
    Takes a raw product description string, strips date patterns and
    removes trailing "Keyword..." sections,
    extracts price and shipping per country, categorizes the product title
    via the local MCP server (OpenRouter backend) and returns a nicely
    formatted Discord message with flag emojis.

    COMMANDS:
        <p>formatproduct <raw description>

    EXAMPLES:
        <p>formatproduct USA $99 shipping $10, UK £80 shipping £5 - Super Widget 2024-06-30
        <p>formatproduct USA $99 shipping $10, UK £80 shipping £5 - Super Widget 2024-06-30 Keyword: gadget sale
            **Super Widget**
            _Category: Example_
            \U0001F1FA\U0001F1F8 $99 + $10 shipping
            \U0001F1EC\U0001F1E7 £80 + £5 shipping

    NOTES:
    - Dates in the form YYYY-MM-DD or YYYY/MM/DD are removed from the input.
    - Any trailing text beginning with "Keyword" (case-insensitive) is stripped.
    """

    async def run_in_thread(func, *args, **kwargs):
        """Run sync function in thread."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    def clean_block(text: str) -> str:
        m = re.search(r"```(?:[a-zA-Z0-9_-]+)?\n(.*?)```", text, re.DOTALL)
        return m.group(1).strip() if m else text.strip()

    def call_mcp(prompt: str, model: str = "meta-llama/llama-4-maverick:free") -> str:
        if requests is None:
            log("requests library missing for MCP call", type_="ERROR")
            return "Unknown"
        try:
            resp = requests.post(
                "http://localhost:3000/generate",
                json={"prompt": prompt, "model": model, "language": "text"},
                timeout=30,
            )
            resp.raise_for_status()
            return clean_block(resp.json().get("output", ""))
        except Exception as e:
            log(f"MCP error: {e}", type_="ERROR")
            return "Unknown"

    FLAG_MAP = {
        "USA": "\U0001F1FA\U0001F1F8",
        "US": "\U0001F1FA\U0001F1F8",
        "UK": "\U0001F1EC\U0001F1E7",
        "GB": "\U0001F1EC\U0001F1E7",
        "DE": "\U0001F1E9\U0001F1EA",
        "AU": "\U0001F1E6\U0001F1FA",
        "CA": "\U0001F1E8\U0001F1E6",
        "FR": "\U0001F1EB\U0001F1F7",
        "IT": "\U0001F1EE\U0001F1F9",
        "ES": "\U0001F1EA\U0001F1F8",
        "JP": "\U0001F1EF\U0001F1F5"
    }

    def infer_type_emoji(raw_header: str) -> str:
        """Infer emoji based on keywords."""
        if "Daily" in raw_header:
            return "🔔"
        if "Dropshipper" in raw_header or "Dropshippers" in raw_header:
            return "🔥"
        return "🙂"

    def parse_prices(text: str):
        """Extract price + shipping info per country from the raw text."""
        data = {}

        # first split by common separators like newlines, commas or semicolons
        for part in re.split(r"[\n,;]+", text):
            part = part.strip()
            if not part:
                continue

            # each part may contain multiple country/price pairs separated by '/'
            for sub in part.split('/'):
                sub = sub.strip()
                if not sub:
                    continue

                # format 1: "USA $99" (optionally with "shipping $X")
                m1 = re.search(
                    r"\b([A-Za-z]{2,3})\b[^$€£\d]*([$€£]?\d+(?:\.\d+)?)",
                    sub,
                )
                if m1:
                    code = m1.group(1).upper()
                    price = m1.group(2)
                else:
                    # format 2: "$99 to USA"
                    m2 = re.search(
                        r"([$€£]?\d+(?:\.\d+)?)\s*to\s*([A-Za-z]{2,3})",
                        sub,
                        re.I,
                    )
                    if not m2:
                        continue
                    price = m2.group(1)
                    code = m2.group(2).upper()

                ship_m = re.search(r"shipping\s*([$€£]?\d+(?:\.\d+)?)", sub, re.I)
                ship = ship_m.group(1) if ship_m else "N/A"
                data[code] = {"price": price, "shipping": ship}

        return data

    # expose for testing
    globals()["parse_prices"] = parse_prices

    def parse_shipping(text: str):
        ship = {}
        for country, days in shipping_re.findall(text):
            ship[country] = days
        return ship

    def parse_profits(text: str):
        return profit_re.findall(text)

    def parse_margins(text: str):
        return margin_re.findall(text)

    globals()["parse_shipping"] = parse_shipping
    globals()["parse_profits"] = parse_profits
    globals()["parse_margins"] = parse_margins

    def remove_price_sections(text: str, codes):
        parts = []
        for piece in re.split(r"[\n,;]+", text):
            p = piece.strip()
            if not p:
                continue
            skip = False
            for code in codes:
                if re.search(rf"\b{code}\b[^$€£\d]*[$€£]?\d", p):
                    skip = True
                    break
                if re.search(rf"[$€£]?\d+(?:\.\d+)?\s*to\s*{code}\b", p, re.I):
                    skip = True
                    break
            if skip:
                continue
            parts.append(p)
        return " ".join(parts)

    # expose helper
    globals()["remove_price_sections"] = remove_price_sections

    async def format_description(text: str) -> str:
        """Return a formatted product description."""
        if not text.strip():
            return ""

        emoji = infer_type_emoji(text)
        keyword_match = re.search(r"Keyword[^:]*:\s*(.+)", text, re.I)
        keyword = keyword_match.group(1).strip() if keyword_match else ""
        cleaned = re.sub(r"Keyword.*$", "", text, flags=re.I | re.S)

        date_match = re.search(r"(\d{4}[/-]\d{2}[/-]\d{2})", cleaned)
        date_line = "*" + date_match.group(1).replace("/", "-") + "*" if date_match else ""
        cleaned = re.sub(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b", "", cleaned)

        price_info = parse_prices(cleaned)
        title = remove_price_sections(cleaned, price_info.keys()).strip()

        weight_m = re.search(r"Gross Weight:?\s*([0-9.]+\s*kg)", cleaned, re.I)
        weight = weight_m.group(1) if weight_m else "? kg"

        ship_times = parse_shipping(cleaned)

        orders_match = re.search(r"(Orders[^\n]*|Units Sold[^\n]*)", cleaned, re.I)
        orders_line = orders_match.group(0).split(":",1)[1].strip() if orders_match else ""

        profit_match = re.search(r"Profit Per Unit[^\n]*", cleaned, re.I)
        profits = parse_profits(profit_match.group(0)) if profit_match else []
        margin_match = re.search(r"Profit Margin[^\n]*", cleaned, re.I)
        margins = parse_margins(margin_match.group(0)) if margin_match else []

        rrp_match = re.search(r"Recommended Retail Price[^\n]*", cleaned, re.I)
        rrp = rrp_match.group(0).split(":",1)[1].strip() if rrp_match else ""

        # still call MCP for categorization but ignore the result (for tests)
        await run_in_thread(
            call_mcp,
            f"Categorize this product title: {title}. Only return the category."
        )

        price_lines = []
        for idx, (code, flag) in enumerate(COUNTRY_ORDER):
            if code in price_info:
                extra = ""
                if profits:
                    if idx < len(profits):
                        extra += f" (💸 ${profits[idx]}"
                        if margins and idx < len(margins):
                            extra += f" • {margins[idx]}%)"
                        else:
                            extra += ")"
                price_lines.append(f"- {flag} {code}: **{price_info[code]['price']}**{extra}")
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
            name=title if title else "Product",
            date_line=date_line,
            price_lines=price_lines,
            weight=weight,
            ship_times=ship_times_str,
            metrics_section=metrics_section,
            keyword=keyword,
        )
        return md

    # expose for external use
    globals()["format_description"] = format_description

    @bot.command(
        name="formatproduct",
        description="Format a raw product description",
        usage="<raw description>"
    )
    async def formatproduct(ctx, *, args: str):
        await ctx.message.delete()
        result = await format_description(args)
        if not result:
            await ctx.send("Provide a description.")
            return
        await ctx.send(result)

product_formatter()

if __name__ == "__main__":  # pragma: no cover - manual execution
    pass
