# -*- coding: utf-8 -*-
"""Utility to format product descriptions for Discord (Nighty + CLI).

Incluye todas las correcciones solicitadas:
• Mantiene emoji 🔔/🔥/🙂 en el encabezado.
• Alias de países (US→USA, GB→UK, etc.).
• Regex de beneficios permite montos sin símbolo $.
• Se añaden separadores de miles en «Units/Orders».
• Elimina campos extra como «Tendencia …».
• Quita comas/espacios finales accidentales.
"""
from __future__ import annotations

import asyncio
import builtins
import re
import sys
import textwrap
import types
from pathlib import Path
from typing import Dict, List

import logging_helper  # noqa: F401 - sets builtins.log

try:
    import requests  # opcional, solo Nighty
except Exception:  # pragma: no cover
    requests = None  # type: ignore

# ────────── Nighty stubs si se ejecuta como script ───────────
if not hasattr(builtins, "nightyScript"):
    builtins.nightyScript = lambda *a, **k: (lambda f: f)
if not hasattr(builtins, "bot"):
    builtins.bot = types.SimpleNamespace(command=lambda *a, **k: (lambda f: f))

# ───────────────────────── Configuración ─────────────────────
COUNTRY_ORDER = [
    ("USA", "🇺🇸"),
    ("UK", "🇬🇧"),
    ("DE", "🇩🇪"),
    ("AU", "🇦🇺"),
]

# Alias para normalizar códigos recibidos
CODE_ALIAS = {"US": "USA", "GB": "UK"}

TEMPLATE_MD = textwrap.dedent(
    """{emoji} **{name}**\n{date_line}\n\n💰 **Precio (producto + envío)**\n{price_lines}\n\n📦 **Logística**\n- Peso bruto: {weight}\n- Tránsito: {ship_times}\n\n{metrics_section}\n🔑 Keyword 1688: `{keyword}`"""
)

SEPARATOR = "―"  # U+2015 para CLI

# Regex actualizados
price_re = re.compile(r"\$([0-9.]+) to ([A-Z]{2})")
profit_re = re.compile(r"\$?([0-9.]+)")
margin_re = re.compile(r"([0-9.]+)%")
shipping_re = re.compile(r"To ([A-Z]{2,3}): ([0-9\\-]+ days)")


# ────────────────── Funciones auxiliares globales ────────────
def infer_type_emoji(raw_header: str) -> str:
    if "Daily" in raw_header:
        return "🔔"
    if "Dropshipper" in raw_header or "Dropshippers" in raw_header:
        return "🔥"
    return "🙂"


def format_thousands(num_str: str) -> str:
    """Convierte 2100 → 2,100. Mantiene '+' si existe."""
    match = re.match(r"([0-9 ]+)(\+?)", num_str.replace(",", ""))
    if not match:
        return num_str
    digits, plus = match.groups()
    digits = digits.replace(" ", "")
    return f"{int(digits):,}{plus}"


# ───────────────────── Parsing de campos comunes ─────────────
def parse_prices(text: str) -> Dict[str, Dict[str, str]]:
    data: Dict[str, Dict[str, str]] = {}
    for part in re.split(r"[\n,;]+", text):
        for sub in part.split('/'):
            sub = sub.strip()
            if not sub:
                continue
            m1 = re.search(r"\b([A-Za-z]{2,3})\b[^$€£\d]*([$€£]?\d+(?:\.\d+)?)", sub)
            if m1:
                code, price = m1.group(1).upper(), m1.group(2)
            else:
                m2 = re.search(r"([$€£]?\d+(?:\.\d+)?)[^A-Za-z0-9]*to[^A-Za-z0-9]*([A-Za-z]{2,3})", sub, re.I)
                if not m2:
                    continue
                price, code = m2.group(1), m2.group(2).upper()
            code = CODE_ALIAS.get(code, code)
            ship_m = re.search(r"shipping\s*([$€£]\d+(?:\.\d+)?)", sub, re.I)
            ship = ship_m.group(1) if ship_m else "N/A"
            data[code] = {"price": price, "shipping": ship}
    return data


def parse_shipping(text: str):
    return {c: d for c, d in shipping_re.findall(text)}


def parse_profits(text: str):
    return profit_re.findall(text)


def parse_margins(text: str):
    return margin_re.findall(text)

# Exponer helpers para tests
globals().update({
    "parse_prices": parse_prices,
    "parse_shipping": parse_shipping,
    "parse_profits": parse_profits,
    "parse_margins": parse_margins,
})

def remove_price_sections(text: str, codes):
    parts: List[str] = []
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

globals()["remove_price_sections"] = remove_price_sections

# ───────────────────────── Formatter core ────────────────────
async def _run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def clean_block(text: str) -> str:
    m = re.search(r"```(?:[a-zA-Z0-9_-]+)?\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


def call_mcp(prompt: str, model: str = "meta-llama/llama-4-maverick:free") -> str:
    try:
        import builtins
    except Exception:  # pragma: no cover - should never happen
        class _Builtins:
            def log(self, *a, **k):
                pass

        builtins = _Builtins()  # type: ignore
    if requests is None:
        builtins.log("requests library missing for MCP call", type_="ERROR")
        return "Unknown"
    try:
        resp = requests.post(
            "http://localhost:3000/generate",
            json={"prompt": prompt, "model": model, "language": "text"},
            timeout=30,
        )
        resp.raise_for_status()
        return clean_block(resp.json().get("output", ""))
    except Exception as e:  # pragma: no cover - network fails
        builtins.log(f"MCP error: {e}", type_="ERROR")
        return "Unknown"


async def _clean_text(raw: str) -> str:
    # Si todo viene en una línea, forzar saltos antes de tokens clave
    raw = re.sub(r"(?=(Goshippro Price|Gross Weight|Profit|Units Sold|Orders|To USA|Keyword))", "\n", raw)
    # Quitar Tendencia u otras líneas irrelevantes
    raw = re.sub(r"Tendencia.*", "", raw, flags=re.I)
    return raw.strip()


async def format_description(text: str) -> str:
    if not text.strip():
        return ""
    text = await _clean_text(text)

    first_line, *rest = text.split("\n", 1)
    emoji = first_line[0] if first_line and first_line[0] in "🔔🔥🙂" else infer_type_emoji(first_line)
    name = re.sub(r"^[^A-Za-z0-9]+", "", first_line).strip()

    date_match = re.search(r"(\d{4}[/-]\d{2}[/-]\d{2})", first_line)
    date_line = "*" + date_match.group(1).replace("/", "-") + "*" if date_match else ""

    body = rest[0] if rest else ""

    keyword_match = re.search(r"Keyword[^:]*:\s*(.+)", body, re.I)
    keyword = keyword_match.group(1).strip() if keyword_match else ""
    body = re.sub(r"Keyword.*$", "", body, flags=re.I | re.S)

    price_info = parse_prices(body)
    weight_m = re.search(r"Gross Weight:?[\s:]*([0-9.]+)\s*kg", body, re.I)
    weight = f"{weight_m.group(1)} kg" if weight_m else "? kg"
    ship_times = parse_shipping(body)

    orders_m = re.search(r"(Orders[^\n]*|Units Sold[^\n]*)", body, re.I)
    orders_line = ""
    if orders_m:
        val = orders_m.group(0).split(":", 1)[1].strip()
        orders_line = f"- Unidades vendidas este año: **{format_thousands(val)}**"

    profits = parse_profits(body)
    margins = parse_margins(body)

    rrp_m = re.search(r"Recommended Retail Price[^\n]*", body, re.I)
    rrp_line = f"- PVP recomendado: **{rrp_m.group(0).split(':',1)[1].strip()}**" if rrp_m else ""

    await _run_in_thread(
        call_mcp,
        f"Categorize this product title: {name}. Only return the category.",
    )

    price_lines: List[str] = []
    for idx, (code, flag) in enumerate(COUNTRY_ORDER):
        if code not in price_info:
            continue
        price_str = price_info[code]["price"]
        if not price_str.startswith("$"):
            price_str = "$" + price_str
        extra = ""
        if profits and idx < len(profits):
            extra = f" (💸 ${profits[idx]}"
            if margins and idx < len(margins):
                extra += f" • {margins[idx]}%)"
            else:
                extra += ")"
        price_lines.append(f"- {flag} {code}: **{price_str}**{extra}")
    price_lines = "\n".join(price_lines)

    ship_parts = [f"{c} {ship_times[c]}" for c in ["USA", "EU", "AU"] if c in ship_times]
    ship_times_str = " · ".join(ship_parts) if ship_parts else "?"

    metrics_section = "\n".join([l for l in [orders_line, rrp_line] if l])
    if metrics_section:
        metrics_section = f"📊 **Métricas**\n{metrics_section}\n\n"

    md = TEMPLATE_MD.format(
        emoji=emoji,
        name=name.rstrip(", ") or "Product",
        date_line=date_line,
        price_lines=price_lines,
        weight=weight.rstrip(","),
        ship_times=ship_times_str,
        metrics_section=metrics_section,
        keyword=keyword,
    )
    return md


globals()["format_description"] = format_description


# ─────────── Nighty command (si bot disponible) ──────────────
@builtins.nightyScript(
    name="Product Formatter",
    author="thedorekaczynski",
    description="Format product info and categorize with OpenRouter",
    usage="<p>formatproduct <raw description>",
)

def product_formatter():  # noqa: D401
    """Nighty wrapper que llama a `format_description`."""

    async def formatproduct(ctx, *, args: str):  # type: ignore
        await ctx.message.delete()
        result = await format_description(args)
        if not result:
            await ctx.send("Provide a description.")
            return
        await ctx.send(result)

    builtins.bot.command(
        name="formatproduct",
        description="Format a raw product description",
        usage="<raw description>",
    )(formatproduct)

product_formatter()  # registrar comando si Nighty


# ─────────────────────────── CLI helper ─────────────────────

def main(argv: List[str]):
    raw = Path(argv[1]).read_text() if len(argv) > 1 else sys.stdin.read()
    blocks = re.split(r"\n\s*\n", raw.strip())
    print(f"\n{SEPARATOR}\n".join(asyncio.run(format_description(b)) for b in blocks if b.strip()))


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv)
