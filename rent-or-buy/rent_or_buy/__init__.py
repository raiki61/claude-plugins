"""借りるか買うかのアルゴリズム（ski rental）。標準ライブラリだけを読み、外の事情を知らない。"""
from .core import InputError, decide
from .policies import register
from .record import append_record

__all__ = ["InputError", "decide", "register", "append_record"]
