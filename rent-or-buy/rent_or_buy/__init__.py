"""借りるか買うかのアルゴリズム（ski rental）。標準ライブラリだけを読み、外の事情を知らない。"""
from .core import InputError, decide
from .policies import register
from .record import KEY_CHARS, append_record, check_outcome, read_records

__all__ = ["InputError", "decide", "register", "append_record", "read_records", "check_outcome", "KEY_CHARS"]
