#!/usr/bin/env python3
"""tools ノード: 機械窓口の道具（受付の設計 docs/specs/2026-10-17-reception-design.md の 5 章）の中身。道具の定義は会社の形の
[[roles.tools]]（読むのは role ノード）。流れ（--call・合図・回す）は calls.py が持つ。

- 入力の確かめ（check_input）: 物であること・required の鍵が在ること・additionalProperties = false なら知らない鍵が無いこと・
  properties の各鍵の type だけを見る。ほかの決まりは道具が自分で確かめる。
- 片づいたか: 道具の終了の値が 0 なら片づいた、0 以外なら片づかなかった（外れ）。
- 回す頼み（miss_text）と、回す先の部署を自動で立てるときの名前と枝（auto_name・auto_branch）。
"""

import contextlib
import json
import os
import re
import shutil
import tempfile

TAIL_LINES = 20   # 外れの記録と回す頼みに載せる、道具の出力の終わりの行数
TYPES = {"string": str, "boolean": bool, "array": list, "object": dict}


def find(roles, role_name, tool_name):
    """(役の項目, 道具) か、見つからない訳の文。"""
    the_role = roles.get(role_name)
    if the_role is None:
        return None, f"役「{role_name}」が会社の形に無い（在る役: {'、'.join(roles) or 'なし'}）"
    tool = next((t for t in the_role.get("tools") or [] if t["name"] == tool_name), None)
    if tool is None:
        names = "、".join(t["name"] for t in the_role.get("tools") or []) or "なし"
        return None, f"役「{role_name}」に道具「{tool_name}」が無い（在る道具: {names}）"
    return (the_role, tool), None


def _typed(value, kind):
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "null":
        return value is None
    want = TYPES.get(kind)
    return want is None or isinstance(value, want)


def check_input(schema, value):
    """入力が道具の inputSchema に合わない訳の並び（空なら合う）。"""
    if not isinstance(value, dict):
        return ["入力が JSON の物（{...}）で無い"]
    out = [f"要る鍵 {k} が無い" for k in schema.get("required") or [] if k not in value]
    props = schema.get("properties") or {}
    if schema.get("additionalProperties") is False:
        out += [f"知らない鍵 {k}" for k in value if k not in props]
    for k, v in value.items():
        kind = (props.get(k) or {}).get("type")
        kinds = kind if isinstance(kind, list) else [kind] if kind else []
        if kinds and not any(_typed(v, x) for x in kinds):
            out.append(f"鍵 {k} の型が {'・'.join(kinds)} で無い")
    return out


@contextlib.contextmanager
def place(root, g):
    """道具を走らせる場所: origin の既定の枝（会社の形を読むのと同じ ref）の中身を、一時の worktree に出したもの。代表の clone の
    作業ツリーは、持ち主がほかの枝を開いていることがあり、その枝に道具の台本が在るとは限らないため。origin/HEAD が無ければ
    代表の clone の根（(場所, 注記) を渡す）。書く口（一時の worktree を作って消す）。"""
    ref = g.origin_head(root)
    sha = g.rev(root, ref) if ref else None
    if not sha:
        yield root, "origin の既定の枝が分からないので、代表の clone の作業ツリーで走らせた"
        return
    path = os.path.join(tempfile.mkdtemp(prefix="works-dispatch-tool-"), "tree")
    g.add_detached(root, path, sha)
    try:
        yield path, None
    finally:
        try:
            g.remove_detached(root, path)
        except g.GitError:
            pass
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def tail(text, lines=TAIL_LINES):
    return "\n".join((text or "").rstrip().splitlines()[-lines:])


def label(tool):
    return tool.get("title") or tool["name"]


def miss_text(role_name, tool, value, code, out_tail):
    """片づかなかった道具の仕事を、AI の部署への頼みに変えた本文。"""
    return (f"機械の道具「{label(tool)}」（{role_name}/{tool['name']}）が片づけられなかった（終了の値 {code}）。\n\n"
            f"入力: {json.dumps(value, ensure_ascii=False)}\n\n道具の出力の終わり:\n```\n{out_tail}\n```\n\n"
            "この入力の仕事を進める。")


def auto_name(role_name, tool):
    """回す先の部署を自動で立てるときの名前（「<道具を持つ役>：<道具の title、無ければ name>」）。"""
    return f"{role_name}：{label(tool)}"


def auto_branch(tool, ask_id):
    """回す先の部署を自動で立てるときの枝（work/<道具の name を英小文字にし、英数字でない字を - にした物>-<受付番号の末尾 6 字>）。"""
    slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", tool["name"].lower())).strip("-") or "tool"
    return f"work/{slug}-{ask_id[-6:]}"
