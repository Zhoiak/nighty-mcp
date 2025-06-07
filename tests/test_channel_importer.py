import builtins
import importlib
import sys
import types
import asyncio
from datetime import datetime
from pathlib import Path

builtins.nightyScript = lambda *a, **k: (lambda f: f)
_captured = {}

class FakeChannel:
    def __init__(self, messages=None):
        self.messages = messages or []
        self.sent = []

    def history(self, limit=None, oldest_first=True, after=None, before=None):
        async def gen():
            for m in self.messages:
                yield m
        return gen()

    async def send(self, content=None, files=None):
        self.sent.append((content, files))

class FakeBot:
    def __init__(self, channels):
        self.channels = channels
    def command(self, *a, **k):
        name = k.get('name') if k else None
        def dec(f):
            if name:
                _captured[name] = f
            return f
        return dec
    def event(self, func):
        return func
    def get_channel(self, cid):
        return self.channels.get(cid)

class FakeMessage:
    def __init__(self, content):
        self.content = content
        self.attachments = []
        self.created_at = datetime(2024, 1, 1)

# stub modules used by product_formatter
sys.modules['requests'] = types.ModuleType('requests')
sys.modules['discord'] = types.ModuleType('discord')
sys.modules['emoji'] = types.ModuleType('emoji')
sys.modules['emoji'].emojize = lambda val, language=None: val

channels = {1: FakeChannel([FakeMessage("Test product")]), 2: FakeChannel()}

builtins.bot = FakeBot(channels)

# ensure isolation across tests
if hasattr(builtins, 'product_formatter'):
    delattr(builtins, 'product_formatter')

# ensure repo root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import product_formatter
importlib.reload(product_formatter)

async def fake_format(text: str):
    calls.append(text)
    return "FORMATTED"

calls = []
product_formatter.format_description = fake_format

import channel_importer
importlib.reload(channel_importer)

import_fn = _captured['importmsgs']
_free = {n: c.cell_contents for n, c in zip(import_fn.__code__.co_freevars, import_fn.__closure__)}
do_import = _free['do_import']

opts = {
    'source_id': 1,
    'dest_id': 2,
    'limit': 50,
    'skip_words': [],
    'replacements': {},
    'remove_lines': [],
    'omit_words': [],
    'after_date': None,
    'before_date': None,
    'include_files': False,
    'signature': '',
    'mention_roles': [],
    'format_product': True,
    'format_file': None,
    'log_channel': None,
}

asyncio.run(do_import(opts))

expected = "FORMATTED\nTendencia [2024-01-01]"
assert channels[2].sent == [(expected, None)]
assert calls == ["Test product"]

