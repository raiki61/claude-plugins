"""rules（rules/<loop>.py）の読み込み。graph が名前で指し、engine が名前で呼ぶ。

rules は engine を import しない。差し込む道具は下の INJECT の鍵が正本——ここに列挙を書き写すと、
鍵を足したときに散文だけが古くなる（実測: 4 個と 9 個の食い違う写しが 2 ファイルに在った）。
"""
import importlib.util
import pathlib

from .schema import validate_schema
from .util import Reject, die, get_path, git, has_path, pick, porcelain, read_json, set_path, sha, write_json

_VALIDATORS = {}


def validator_module(b):
    """検証器（init --validator で決まった scripts/<loop>-record.py）を import して定数・述語を読む——rules は写さない。
    以前は review / research の rules がそれぞれ同じ 4 手順を持っていた（差は文言だけ）。loop 名は盤面から来るので
    engine に loop の語は入らない。"""
    path = b.state.get("validator")
    if not path:
        raise Reject("検証器（scripts/<loop>-record.py）が見つからない。init --validator で渡せ")
    if path not in _VALIDATORS:
        spec = importlib.util.spec_from_file_location("graphloops_validator", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _VALIDATORS[path] = mod
    return _VALIDATORS[path]


INJECT = {"Reject": Reject, "pick": pick, "get_path": get_path, "set_path": set_path, "has_path": has_path,
          "porcelain": porcelain, "read_json": read_json, "write_json": write_json, "git": git, "sha": sha,
          "validator_module": validator_module, "validate_schema": validate_schema}


def load_rules(graph_path, graph):
    rel = graph.get("rules")
    if not rel:
        return None
    p = (pathlib.Path(graph_path).parent / rel).resolve()
    spec = importlib.util.spec_from_file_location("graphloops_rules", p)
    if spec is None:
        die(f"rules が読めない: {p}")
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__.update(INJECT)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        die(f"rules {p} の読み込みで例外（{type(e).__name__}）: {e}")
    return mod


def registry(rules, name):
    return getattr(rules, name, {}) if rules else {}


def hook(rules, name):
    return getattr(rules, name, None) if rules else None
