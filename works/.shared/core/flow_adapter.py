"""流れの道具（今は Archon v0.11.1）に触る口（依頼 239 の設計 §6）。層 L1（works の物を何も知らない）。標準ライブラリだけ。

部品の中身と引き継ぎの文書は、流れの道具の事をこの口だけを通して知る。別の道具へ乗り換える時に書き直すのはこの模块の中身だけ。
口は 4 つに限る:
- current_scope() -> str: 今の script が居る include の名（線の最上段なら ""。fan_out の子なら「fan の節の名--子の印」）。
  盤面の部品の置き場（scope）の名になる
- fan_node(scope) -> str: scope が fan_out の子の物なら fan の節の名（ほかは ""）。照らしの窓が子の全部を 1 つに束ねる鍵
- in_flow_node() -> bool: 今のプロセスが流れの道具の節として起こされたか（run の外の道具・試験の手は偽）。盤面の窓を動かすのは節だけ
- artifact_root() -> Path | None: run の成果物の置き場（無い・空は None）

scope の出どころ（測り M1。Archon v0.11.1 で 2026-10-03 に実測）:
- 形 A（採る）: Archon はどの script の節にも環境変数 ARCHON_NODE_EXECUTION（JSON）を渡し、その欄 path が include の名を頭に持つ
  step の名（include の最上段は `<include>__<節>`、輪の中は `<include>__<輪>.<節>`、線の最上段は `__` を持たない `<節>`）。
  scope は path の最初の `__` の前（`__` が無ければ ""）。今の works の節の id は `__` を持たない。入れ子の include は測っていない
- fan_out の子（2026-10-04 に実測）: 線の最上段の include の節に fan_out を付けると、子の節の path は
  `__archon_fan_out__<fan の節>__root__<印>__<fan の節>__<印>__<子の節>`（印は items の値の sha256 の頭 16 字。同じ値なら
  走り直しても同じ）。最初の `__` の前は空なので、形 A のままでは scope が読めない。子の scope は `<fan の節>--<印の頭 8 字>`
  （FAN_SEP）にし、子ごとに私物の置き場を分ける。manifest は起こされたスクリプトのブロック（scopes.running_block）で引くので、
  fan の節が差し込む部品の物で照らされる。測っていない形（root でない親・入れ子の中の fan_out・path の途中の
  `__archon_fan_out__`）は ValueError（黙って別の置き場に落とさない）。ふつうの include の名に FAN_SEP は使えない
- 形 B（測った代わりの手）: include の節の `with:` に 1 度だけ書いた入力 include_id が、そのブロックの全部の節に INPUTS_INCLUDE_ID で
  届く（渡さない include には既定の "" が届く）。形 B へ移すなら、読み口 _scope_from の中身を
  `return env.get("INPUTS_INCLUDE_ID", "")` の 1 行に替え、YAML の全部の include の節に include_id を書く。ほかは変えない

口の内に入れる物（Archon に固く結び付いた所。乗り換えたらここだけ書き直す。設計 §6）:
- include の名・入れ子の道・fan_out の子の道の取り方（current_scope・fan_node）
- ARTIFACTS_DIR（または今の盤面の根）の場所（artifact_root）
- 再開した時の振る舞い（同じ節を走り直しても scope が同じになること。形 A は step の名から引くので同じ）
口の外に残る物（Archon 固有だが、乗り換える時に書き直す物として並べるだけ）:
- workflow の YAML 本体（blk-*.yaml の include・節の書き方）
- works から .archon/workflows/works へ写す同期（.works-source.json）
- YAML の中で include に scope や Consumes の結び付けを渡す書き方
works 独自で道具に依らない物（口の外。乗り換えても残る）:
- 盤面の配置・manifest・照らしの関所・共有の記録の書き手の制限・ファイルの形

INPUTS_* の読み（script_io ほか）と聞き直し（設計 §5。docs/plans/2026-10-03-block-scope.md）はこの口の外。呼び手の無い入力の口
input と、作らないまま置いた聞き直しの口 session_handle・resume・session.schema.json は外した（2026-10-09 の掃除）。
"""
from __future__ import annotations

import json
import os
import pathlib
import re

NODE_EXECUTION_ENV = "ARCHON_NODE_EXECUTION"   # 形 A の出どころ（JSON。欄 path が include の名を頭に持つ step の名）
INCLUDE_SEP = "__"                             # Archon が include の名と節の名をつなぐ字
ARTIFACTS_ENV = "ARTIFACTS_DIR"
# scope の名の決まり（盤面の board.SCOPE_RULE と同じ字の組。board はこの模块を読まないので字で持つ）: 英字で始まり英数字・_・-
# だけで、周の置き場 r<N> と紛れない名
SCOPE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
ROUND_NAME = re.compile(r"r\d+")
FAN_OUT_HEAD = "__archon_fan_out__"            # fan_out の子の節の path の頭（測った形。モジュールの docstring）
FAN_SEP = "--"                                 # fan_out の子の scope の「fan の節の名」と「子の印」の間（ふつうの include の名に使わない）
_FAN_PATH = re.compile(r"__archon_fan_out__(?P<fan>.+?)__root__(?P<mark>[0-9a-f]{8,})__(?P=fan)__(?P=mark)__(?P<node>.+)")


def _scope_from(env) -> str:
    """scope の読み口（ここ 1 か所。形 B へ移すならこの中身だけを替える）。形 A: ARCHON_NODE_EXECUTION の path の最初の `__` の前。
    変数が無い・空は ""。在るのに JSON のオブジェクトでない・path が文字列でない・include の名が scope の名の決まり（SCOPE_NAME で
    ROUND_NAME でない）に外れるなら ValueError（黙って線の置き場に落とさない・盤面の置き場に書く前に止める）"""
    raw = env.get(NODE_EXECUTION_ENV, "")
    if not raw:
        return ""
    try:
        doc = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"環境変数 {NODE_EXECUTION_ENV} が JSON として読めない: {e}") from None
    path = doc.get("path") if isinstance(doc, dict) else None
    if not isinstance(path, str):
        raise ValueError(f"環境変数 {NODE_EXECUTION_ENV} に文字列の欄 path が無い: {raw[:200]}")
    if FAN_OUT_HEAD in path:
        m = _FAN_PATH.fullmatch(path)
        if m is None:
            raise ValueError(f"環境変数 {NODE_EXECUTION_ENV} の fan_out の子の path が測った形（{FAN_OUT_HEAD}<fan の節>__root__<印>__"
                             f"<fan の節>__<印>__<子の節>）でない（入れ子の中の fan_out は測っていない）: {path}")
        _name_ok(m["fan"], path, "fan の節の名")
        return f"{m['fan']}{FAN_SEP}{m['mark'][:8]}"
    head, sep, _ = path.partition(INCLUDE_SEP)
    if sep:
        _name_ok(head, path, "include の名")
    return head if sep else ""


def _name_ok(name: str, path: str, what: str) -> None:
    """scope の頭に使う名 name が決まり（SCOPE_NAME で ROUND_NAME でなく、FAN_SEP を持たない）に合わなければ ValueError"""
    if not (SCOPE_NAME.fullmatch(name) and not ROUND_NAME.fullmatch(name) and FAN_SEP not in name):
        raise ValueError(f"環境変数 {NODE_EXECUTION_ENV} の{what} {name!r} は scope に使えない（英字で始まり英数字・_・- だけで、"
                         f"r<数字> でなく {FAN_SEP} を持たない名。周の置き場や盤面の根の外、ほかの fan_out の子の置き場に私物を"
                         f"書かない）: {path}")


def current_scope() -> str:
    """今の script が居る include の名（線の最上段・流れの道具の外なら ""）"""
    return _scope_from(os.environ)


def fan_node(scope: str) -> str:
    """scope が fan_out の子の物（<fan の節>--<印>）なら fan の節の名、ほかは ""。照らしの窓（scopes.enter）は同じ fan の子の全部を
    1 つの窓に束ねる（同時に走る子の 1 つの窓を別の子が閉じて、互いの書き込みを宣言の外と読まないように）"""
    head, sep, _ = scope.partition(FAN_SEP)
    return head if sep else ""


def in_flow_node() -> bool:
    """今のプロセスが流れの道具の節として起こされたか（Archon はどの script の節にも ARCHON_NODE_EXECUTION を渡す。測り M1）。
    run の外で盤面を読む道具（dev/report.sh・dev/fixmeasure.py）と試験の手は偽"""
    return bool(os.environ.get(NODE_EXECUTION_ENV, ""))


def artifact_root() -> pathlib.Path | None:
    """run の成果物の置き場（ARTIFACTS_DIR。無い・空は None）。解決（resolve）と $ の柵は呼び手の仕事"""
    raw = os.environ.get(ARTIFACTS_ENV, "")
    return pathlib.Path(raw) if raw else None
