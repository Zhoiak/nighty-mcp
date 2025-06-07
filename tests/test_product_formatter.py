import builtins
import importlib
import asyncio
import sys
import types
from pathlib import Path

# Stub required globals and modules before importing the script
builtins.nightyScript = lambda *a, **k: (lambda f: f)
builtins.bot = types.SimpleNamespace(command=lambda *a, **k: (lambda f: f))
sys.modules['discord'] = types.ModuleType('discord')
sys.modules['requests'] = types.ModuleType('requests')

# Ensure repository root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import product_formatter

parse_prices = product_formatter.parse_prices


def test_parse_prices_country_leading():
    text = "USA $99 shipping $10, UK £80 shipping £5"
    result = parse_prices(text)
    assert result == {
        "USA": {"price": "$99", "shipping": "$10"},
        "UK": {"price": "£80", "shipping": "£5"},
    }


def test_parse_prices_price_to_country():
    text = "$99 to USA / £80 to UK"
    result = parse_prices(text)
    assert result == {
        "USA": {"price": "$99", "shipping": "N/A"},
        "UK": {"price": "£80", "shipping": "N/A"},
    }


def test_parse_prices_mixed_formats():
    text = "USA $70 shipping $5 / €60 to DE"
    result = parse_prices(text)
    assert result == {
        "USA": {"price": "$70", "shipping": "$5"},
        "DE": {"price": "€60", "shipping": "N/A"},
    }


def test_word_boundary_parsing():
    text = "Hause Price (Product Cost+Shipping Cost): $4.03 to USA"
    result = parse_prices(text)
    assert result == {"USA": {"price": "$4.03", "shipping": "N/A"}}


def test_call_mcp_failure(monkeypatch):
    logged = []
    builtins.log = lambda m, type_="INFO": logged.append((m, type_))

    class BadReq:
        def post(*a, **k):
            raise RuntimeError("fail")

    product_formatter.requests = BadReq
    fmt = importlib.reload(product_formatter)
    out = asyncio.run(fmt.format_description("USA $5"))
    assert out.strip()
    assert "Unknown" not in out
    assert any("MCP error" in m for m, _ in logged)
