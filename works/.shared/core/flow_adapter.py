"""流れの道具（今は Archon v0.11.1）に触る口（依頼 239 の設計 §6）。層 L1（works の物を何も知らない）。標準ライブラリだけ。

部品の中身と引き継ぎの文書は、流れの道具の事をこの口だけを通して知る。別の道具へ乗り換える時に書き直すのはこの模块の中身だけ。
口は 5 つに限る:
- current_scope() -> str: 今の script が居る include の名（線の最上段なら ""）。盤面の部品の置き場（scope）の名になる
- artifact_root() -> Path | None: run の成果物の置き場（無い・空は None）
- input(name) -> str | None: 節に渡された入力の値（無ければ None。既定の空は "" のまま届く）
- session_handle()・resume(handle, prompt): 聞き直しの口。まだ作らない（NotImplementedError。形は下と session.schema.json）

scope の出どころ（測り M1。Archon v0.11.1 で 2026-10-03 に実測）:
- 形 A（採る）: Archon はどの script の節にも環境変数 ARCHON_NODE_EXECUTION（JSON）を渡し、その欄 path が include の名を頭に持つ
  step の名（include の最上段は `<include>__<節>`、輪の中は `<include>__<輪>.<節>`、線の最上段は `__` を持たない `<節>`）。
  scope は path の最初の `__` の前（`__` が無ければ ""）。今の works の節の id は `__` を持たない。入れ子の include は測っていない
- 形 B（測った代わりの手）: include の節の `with:` に 1 度だけ書いた入力 include_id が、そのブロックの全部の節に INPUTS_INCLUDE_ID で
  届く（渡さない include には既定の "" が届く）。形 B へ移すなら、読み口 _scope_from の中身を
  `return env.get("INPUTS_INCLUDE_ID", "")` の 1 行に替え、YAML の全部の include の節に include_id を書く。ほかは変えない

聞き直し（設計 §5。今は作らない。塞がないための形だけ）:
- 会話の手がかり: 役を起こした節ごとに、この口が `<scope の根>/r<N>/session.json`（session.schema.json の形 {tool, handle}。
  流れの道具の会話の手がかりを開いた形で書く）を置き、部品の宣言した出力の 1 つとして扱う。Archon の provider_session_id
  （DB の remote_agent_workflow_run_node_sessions）がこれに当たるかは仮説で、作る時にこの口の中で確かめる
- 問い: 後の節が前の節に聞き直す時は、自分の scope の根に `questions/<相手 scope>/<連番>.md` を Produces として書く
- 答え: この口が相手の session.json から会話を開き直して答えを得て、相手の scope の根に `answers/<問いの scope>/<連番>.md` を
  書き、core が相手の追加の出力として登録する。問いも答えも引き継ぎのファイルと同じ宣言した Markdown（新しい仕組みは要らない）

口の内に入れる物（Archon に固く結び付いた所。乗り換えたらここだけ書き直す。設計 §6）:
- include の名・入れ子の道の取り方（current_scope）
- ARTIFACTS_DIR（または今の盤面の根）の場所（artifact_root）
- INPUTS_* 環境変数の読み方（input）
- provider_session_id とその DB（remote_agent_workflow_run_node_sessions）（session_handle・resume。まだ作らない）
- 再開した時の振る舞い（同じ節を走り直しても scope が同じになること。形 A は step の名から引くので同じ）
口の外に残る物（Archon 固有だが、乗り換える時に書き直す物として並べるだけ）:
- workflow の YAML 本体（blk-*.yaml の include・節の書き方）
- works から .archon/workflows/works へ写す同期（.works-source.json）
- YAML の中で include に scope や Consumes の結び付けを渡す書き方
works 独自で道具に依らない物（口の外。乗り換えても残る）:
- 盤面の配置・manifest・照らしの関所・共有の記録の書き手の制限・ファイルの形

今の works の INPUTS_* の読み（script_io ほか）をこの口へ寄せるのは依頼 239 の外。新しく Archon に触るコードだけがこの口を通る。
"""
from __future__ import annotations

import json
import os
import pathlib
import re

NODE_EXECUTION_ENV = "ARCHON_NODE_EXECUTION"   # 形 A の出どころ（JSON。欄 path が include の名を頭に持つ step の名）
INCLUDE_SEP = "__"                             # Archon が include の名と節の名をつなぐ字
ARTIFACTS_ENV = "ARTIFACTS_DIR"
INPUTS_PREFIX = "INPUTS_"
ASK_BACK = "聞き直しはまだ作らない（依頼 239 の §5。形は session.schema.json）"
# scope の名の決まり（盤面の board.SCOPE_RULE と同じ字の組。board はこの模块を読まないので字で持つ）: 英字で始まり英数字・_・-
# だけで、周の置き場 r<N> と紛れない名
SCOPE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
ROUND_NAME = re.compile(r"r\d+")


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
    head, sep, _ = path.partition(INCLUDE_SEP)
    if sep and not (SCOPE_NAME.fullmatch(head) and not ROUND_NAME.fullmatch(head)):
        raise ValueError(f"環境変数 {NODE_EXECUTION_ENV} の include の名 {head!r} は scope に使えない（英字で始まり英数字・_・- だけで、"
                         f"r<数字> でない名。周の置き場や盤面の根の外に私物を書かない）: {path}")
    return head if sep else ""


def current_scope() -> str:
    """今の script が居る include の名（線の最上段・流れの道具の外なら ""）"""
    return _scope_from(os.environ)


def artifact_root() -> pathlib.Path | None:
    """run の成果物の置き場（ARTIFACTS_DIR。無い・空は None）。解決（resolve）と $ の柵は呼び手の仕事"""
    raw = os.environ.get(ARTIFACTS_ENV, "")
    return pathlib.Path(raw) if raw else None


def input(name: str) -> str | None:  # noqa: A001（設計 §6 の口の名）
    """節に渡された入力 name の値（INPUTS_<NAME の大文字>）。無ければ None、既定の空は空の文字列のまま"""
    return os.environ.get(INPUTS_PREFIX + name.upper())


def session_handle() -> dict:
    """今の節の役の会話の手がかり（形は session.schema.json）。まだ作らない（モジュールの docstring の「聞き直し」）"""
    raise NotImplementedError(ASK_BACK)


def resume(handle: dict, prompt: str) -> str:
    """handle の会話を開き直して prompt を聞き、答えの本文を返す。まだ作らない（モジュールの docstring の「聞き直し」）"""
    raise NotImplementedError(ASK_BACK)
