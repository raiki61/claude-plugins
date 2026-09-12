"""rules（rules/<loop>.py）の読み込み。graph が名前で指し、engine が名前で呼ぶ。

rules は engine を import しない。差し込む道具は下の INJECT の鍵が正本——ここに列挙を書き写すと、
鍵を足したときに散文だけが古くなる（実測: 4 個と 9 個の食い違う写しが 2 ファイルに在った）。
"""
import importlib.util
import pathlib

from .schema import validate_schema
from .util import Reject, die, git, git_bytes, pick, porcelain, read_json, sha, write_json

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
        try:
            spec.loader.exec_module(mod)
        except KeyboardInterrupt:
            raise
        except BaseException as e:  # SystemExit は Exception 派生でない——検証器の import 時 sys.exit がそのまま終了コードになっていた
            die(f"検証器 {path} が import できない（{type(e).__name__}: {e}）——engine は import を契約にしている", 2)
        _VALIDATORS[path] = mod
    return _VALIDATORS[path]


# rules に差し込む道具の正本。**消費者が 0 の鍵は置かない**——get_path / set_path / has_path は同梱の rules 2 本から
# 一度も呼ばれておらず、『rules が記録の任意の場所を path で読み書きしてよい』と読める面だけを開いていた
# （記録を書く経路を writes に寄せる方針と逆向き）。使う日に戻せる
INJECT = {"Reject": Reject, "pick": pick, "porcelain": porcelain, "read_json": read_json, "write_json": write_json,
          "git": git, "git_bytes": git_bytes, "sha": sha,
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
    except KeyboardInterrupt:
        raise
    except BaseException as e:  # SystemExit も捕まえる（rules が import 時に sys.exit すると終了コードがそのまま抜けた）
        die(f"rules {p} の読み込みで例外（{type(e).__name__}）: {e}")
    return mod


def registry(rules, name):
    return getattr(rules, name, {}) if rules else {}


# engine が rules に探すフックの全部。**綴り違いと意図的な不在を分ける唯一の手掛かり**——getattr の名前一致だけ
# だったとき、on_new_round を 1 字違えても静かに「このループは持たない」に倒れ、周をまたぐ持ち越しが消えないまま
# 回り続けた。graphcheck がこの表を import して、rules の公開名のうち似て非なる物を落とす
HOOKS = ("on_init", "on_new_round", "on_answer", "on_unattended", "on_thickness", "finalize", "check_record", "init_record", "add")


def hook(rules, name):
    assert name in HOOKS, f"engine が知らないフック名: {name}（HOOKS が正本）"
    return getattr(rules, name, None) if rules else None
