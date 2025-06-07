"""Utility logging helper for Nighty scripts."""

import builtins


def log(msg, type_="INFO"):
    """Safe log that works with or without Nighty's patched print."""
    try:
        print(msg, type_=type_)
    except TypeError:
        print(msg)


# expose globally so other modules can always access builtins.log
if not hasattr(builtins, "log"):
    builtins.log = log
