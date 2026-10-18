#!/usr/bin/env python3
"""tools ノード: 機械窓口のツール（受付の設計 docs/specs/2026-10-17-reception-design.md の 5 章）の中身。ツールの定義は会社の形の
[[roles.tools]]（読むのは role ノード）。流れ（--call・合図・回す）は calls.py が持つ。

- 入力の確かめ（check_input）: 物であること・required の鍵が在ること・additionalProperties = false なら知らない鍵が無いこと・
  properties の各鍵の type だけを見る。ほかの決まりはツールが自分で確かめる。
- 片づいたか: ツールの終了の値が 0 なら片づいた、0 以外なら片づかなかった（外れ）。
- 回す頼み（miss_text）と、回す先の部署を自動で立てるときの名前とブランチ（auto_name・auto_branch）。
- 走らせる場所（place）: 一時の worktree（<一時のフォルダ>/works-dispatch-tool-<字>/tree）。作るときに、作った処理の pid を訳にした
  鍵を掛け（OWNER）、走らせ終えたら消す。処理が殺される（Bash の持ち時間切れなど）と消す所まで行かずに残るので、次にツールを走らせる
  ときと --clean が、作った処理がもう居ない物を消す（leftovers・sweep）。2026-10-17 に my_notes で、消えずに残った一時の worktree と、
  場所がもう無いのに鍵だけ残った行が、--tree に「（ブランチ無し）」で並んでいた。ツールはその場所で commit を作ることがある（写しのツールが
  来歴を commit して push する）ので、先頭の commit がどのブランチにも無ければ ref（KEPT_REF）に残してから消し、未コミットの変更が在る
  場所は消さない（その残り物には、push できずに殺された commit が載っていた）。
"""

import contextlib
import json
import os
import re
import shutil
import tempfile

TAIL_LINES = 20   # 外れの記録と回す頼みに載せる、ツールの出力の終わりの行数
PREFIX = "works-dispatch-tool-"   # 走らせる場所の親のフォルダの名前の頭（tempfile.mkdtemp の prefix）
OWNER = "works-dispatch-tool pid "   # 走らせる場所の鍵の訳。後ろに作った処理の pid
KEPT_REF = "refs/company/kept-tools/"   # 消した場所の先頭の commit がどのブランチにも無いとき、残す ref の頭（後ろに commit の id）
TYPES = {"string": str, "boolean": bool, "array": list, "object": dict}


def find(roles, role_name, tool_name):
    """(役の項目, ツール) か、見つからない訳の文。"""
    the_role = roles.get(role_name)
    if the_role is None:
        return None, f"役「{role_name}」が会社の形に無い（在る役: {'、'.join(roles) or 'なし'}）"
    tool = next((t for t in the_role.get("tools") or [] if t["name"] == tool_name), None)
    if tool is None:
        names = "、".join(t["name"] for t in the_role.get("tools") or []) or "なし"
        return None, f"役「{role_name}」にツール「{tool_name}」が無い（在るツール: {names}）"
    unchecked = schema_problems(tool["inputSchema"])
    if unchecked:   # 書いた制約が黙って効かないまま走らせない
        return None, (f"役「{role_name}」のツール「{tool_name}」の inputSchema の {', '.join(unchecked)} は入力の検査が確かめないので走らせない。"
                      f"使えるのは {', '.join(sorted(SCHEMA_KEYS))} と、各鍵の {', '.join(sorted(PROPERTY_KEYS))}")
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


# check_input が確かめる inputSchema の keyword。ここに無い keyword（enum・pattern・minimum など）を書いたツールは、書いた制約が
# 黙って効かないので、会社の形を読むとき（role._tools）に外す。JSON Schema の検査の全部は標準ライブラリに無く、要るのは
# 鍵の有る無しと型だけなので、自作の検査を広げず、受ける keyword を絞る
SCHEMA_KEYS = {"type", "properties", "required", "additionalProperties", "title", "description", "$schema"}
PROPERTY_KEYS = {"type", "description", "title"}


def schema_problems(schema):
    """inputSchema のうち check_input が確かめない書き方の並び（空なら全部確かめる）。"""
    out = [f"keyword {k}" for k in schema if k not in SCHEMA_KEYS]
    req = schema.get("required", [])
    if not (isinstance(req, list) and all(isinstance(k, str) for k in req)):
        out.append("required（文字列の並び）")
    if not isinstance(schema.get("additionalProperties", True), bool):
        out.append("additionalProperties（true か false）")
    props = schema.get("properties", {})
    if not isinstance(props, dict):
        return out + ["properties（表）"]
    known = set(TYPES) | {"integer", "number", "null"}
    for name, p in props.items():
        if not isinstance(p, dict):
            out.append(f"properties.{name}（表）")
            continue
        out += [f"properties.{name} の keyword {k}" for k in p if k not in PROPERTY_KEYS]
        kind = p.get("type")
        kinds = kind if isinstance(kind, list) else [kind] if kind is not None else []
        if not all(isinstance(x, str) and x in known for x in kinds):
            out.append(f"properties.{name} の type（{'・'.join(sorted(known))} のどれか）")
    return out


def check_input(schema, value):
    """入力がツールの inputSchema に合わない訳の並び（空なら合う）。"""
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
    """ツールを走らせる場所: origin の既定のブランチ（会社の形を読むのと同じ ref）の中身を、一時の worktree に出したもの。代表の clone の
    作業ツリーは、持ち主がほかのブランチを開いていることがあり、そのブランチにツールの台本が在るとは限らないため。origin/HEAD が無ければ
    代表の clone のルート（(場所, 注記) を渡す）。作る前に、前に殺された処理が残した場所を消す（sweep）。書く口（一時の worktree を作って消す）。"""
    ref = g.origin_head(root)
    sha = g.rev(root, ref) if ref else None
    if not sha:
        yield root, "origin の既定のブランチが分からないので、代表の clone の作業ツリーで走らせた"
        return
    sweep(root, g)
    path = os.path.join(tempfile.mkdtemp(prefix=PREFIX), "tree")
    g.add_detached(root, path, sha, lock=f"{OWNER}{os.getpid()}")
    try:
        yield path, None
    finally:
        try:
            g.remove_detached(root, path)
        except g.GitError:
            pass
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def is_place(path):
    """ツールを走らせる場所（place が作る一時の worktree）のパスの形か。"""
    return os.path.basename(path or "") == "tree" and os.path.basename(os.path.dirname(path or "")).startswith(PREFIX)


def _alive(pid, posix=os.name != "nt"):
    """その処理が居るか。Windows では確かめない（os.kill は 0 を渡しても処理を止める）ので、居るとみなす（消さない側に倒す）。"""
    if not posix:
        return True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def leftovers(entries, alive=_alive, exists=os.path.exists):
    """git の worktree の並び（gitx.listed_worktrees）のうち、ツールを走らせる場所で、作った処理がもう居ない物のパスの並び。
    鍵の訳が OWNER と pid の物はその pid の処理が居なければ、ほかの物は親のフォルダがもう無ければ、残り物とみる。ほかの物は、鍵の無い
    物（この版より前の place が作った。この版の place は作っている途中から鍵が在る）と、ほかの訳の鍵（git が作る途中に掛ける
    initializing・人が掛けた物）。鍵の無い物を残り物とみないのは、アカウントごとに入っている版が違う間、前の版のツールが今走っている
    場所かもしれないため（2026-10-18 に my_notes で、前の版の写しのツールが走っている最中の鍵の無い場所を見た）。"""
    out = []
    for e in entries:
        if not is_place(e["path"]):
            continue
        why = e.get("locked")
        pid = why[len(OWNER):].strip() if why is not None and why.startswith(OWNER) else ""
        if pid.isascii() and pid.isdigit():
            if alive(int(pid)):
                continue
        elif exists(os.path.dirname(e["path"])):
            continue
        out.append(e["path"])
    return out


# 残り物の場所を消さない・消せなかった訳のキー（呼ぶ側は文でなくこれで比べる。文は語の置き換えで替わりうる）
DIRTY = "dirty"   # 未コミットの変更か git に足していないファイルが在る
GIT_FAILED = "git"   # 消す git のコマンドが失敗した


def judge(entry, g, root):
    """残り物の場所 1 つの扱い。{path, keep, reason, why}。keep は消す前に KEPT_REF に残す commit（無ければ None）、reason は消さない訳の
    キー（DIRTY。消すなら None）、why はその人向けの文。未コミットの変更か git に足していないファイルが在れば消さない
    （.gitignore に当たる物は数えない）。"""
    path, head = entry["path"], entry.get("head")
    if os.path.isdir(path) and not g.is_clean(path):
        return {"path": path, "keep": None, "reason": DIRTY, "why": "未コミットの変更が在る"}
    keep = head if head and not g.on_some_ref(root, head) else None
    return {"path": path, "keep": keep, "reason": None, "why": None}


def sweep(root, g, alive=_alive):
    """leftovers を消す（git の worktree の記録と、親の一時のフォルダ）。先頭の commit がどのブランチにも無ければ KEPT_REF に残してから消す。
    (消した judge の並び, 消せなかった (パス, 訳のキー〔DIRTY・GIT_FAILED〕, 人向けの訳) の並び)。書く口。"""
    done, failed = [], []
    entries = g.listed_worktrees(root)
    stale = set(leftovers(entries, alive))
    for e in (e for e in entries if e["path"] in stale):
        got = judge(e, g, root)
        if got["reason"]:
            failed.append((got["path"], got["reason"], got["why"]))
            continue
        try:
            if got["keep"]:
                g.keep_commit(root, KEPT_REF + got["keep"], got["keep"])
            g.remove_detached(root, got["path"])
        except g.GitError as err:
            failed.append((got["path"], GIT_FAILED, str(err)))
            continue
        shutil.rmtree(os.path.dirname(got["path"]), ignore_errors=True)
        done.append(got)
    return done, failed


def tail(text, lines=TAIL_LINES):
    return "\n".join((text or "").rstrip().splitlines()[-lines:])


def label(tool):
    return tool.get("title") or tool["name"]


def miss_text(role_name, tool, value, code, out_tail):
    """片づかなかったツールの仕事を、AI の部署への頼みに変えた本文。"""
    return (f"機械のツール「{label(tool)}」（{role_name}/{tool['name']}）が片づけられなかった（終了の値 {code}）。\n\n"
            f"入力: {json.dumps(value, ensure_ascii=False)}\n\nツールの出力の終わり:\n```\n{out_tail}\n```\n\n"
            "この入力の仕事を進める。")


def auto_name(role_name, tool):
    """回す先の部署を自動で立てるときの名前（「<ツールを持つ役>：<ツールの title、無ければ name>」）。"""
    return f"{role_name}：{label(tool)}"


def auto_branch(tool, ask_id):
    """回す先の部署を自動で立てるときのブランチ（work/<ツールの name を英小文字にし、英数字でない字を - にした物>-<受付番号の末尾 6 字>）。"""
    slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", tool["name"].lower())).strip("-") or "tool"
    return f"work/{slug}-{ask_id[-6:]}"
