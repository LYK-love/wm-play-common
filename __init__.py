"""Compatibility shim for using this repository directly as a submodule.

When the repository is mounted at a path named ``wm_play`` without installation,
this file redirects submodule imports such as ``wm_play.cli`` to ``src/wm_play``.
Installed usage goes through the normal package in ``src/wm_play``.
"""

from __future__ import annotations

import pathlib

_pkg = pathlib.Path(__file__).resolve().parent / 'src' / 'wm_play'
__path__ = [str(_pkg)]
