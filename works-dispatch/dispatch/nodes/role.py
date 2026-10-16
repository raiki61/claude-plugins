#!/usr/bin/env python3
"""role ノード: 会社の形のファイル（tree.read_info が見つけた物）から、役の項目と gh のアカウントを読み、部署に渡す物を組み立てる。書くのは、部署を起こすときの設定のファイル 1 つ（write_settings）だけ。

会社の形の設計（docs/specs/2026-10-16-company-shape-design.md）の 4.7（役ごとに起動時の文脈を絞る）と 4.8（役の渡し方）に当たる。
役は会社の形の [[roles]] に 1 つずつ書く。欄は次のとおりで、知らない欄は読み飛ばす。
- name: 役の名前（部署の属性 company.role と同じ字）
- instructions: 部署の会話の指示に足す役の本文。SessionStart のフックが毎回の起動で足すので短くし、AGENTS.md と同じことは書かない
- model: 部署を起こすときの --model
- settings: 部署を起こすときの --settings に渡す Claude Code の設定（表）。enabledPlugins・permissions.deny・skillOverrides など。
  その会話にだけ効き、利用者の全体の設定とリポジトリの設定は触らない
会社の形の頭の gh_user は、その会社の gh のアカウント（部署の会話の Bash に GH_TOKEN として入れる。env_line）。

入口の dispatch.py --task が起こすときに load・pick・settings_for・write_settings・gh_user・warnings を呼び、プラグインのフック
role_hook.py が context と env_line を呼ぶ。
"""

import json
import os
import shlex
import tomllib

# 部署を起こすときに必ず効かせる設定の鍵。役の設定より強い（裏の会話が自分で worktree を作らず、先に作った作業場で働くため）
FIXED = {"worktree": {"bgIsolation": "none"}}


def _empty():
    return {"roles": {}, "gh_user": None, "problems": []}


def load(path):
    """会社の形のファイルから {roles: 名前 → {name, instructions, model, settings}, gh_user, problems}。path が None なら空。
    形の違う役は problems に書いて外し、ほかの役は読む。"""
    out = _empty()
    if not path:
        return out
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        out["problems"].append(f"{path}: TOML として読めない（{e}）")
        return out
    gh_user = raw.get("gh_user")
    if gh_user is not None and not (isinstance(gh_user, str) and gh_user):
        out["problems"].append(f"{path}: gh_user が文字列で無い")
    elif gh_user:
        out["gh_user"] = gh_user
    roles = raw.get("roles", [])
    if not isinstance(roles, list):
        out["problems"].append(f"{path}: roles が表の並び（[[roles]]）で無い")
        return out
    for i, r in enumerate(roles):
        where = f"{path}: roles[{i}]"
        if not isinstance(r, dict) or not isinstance(r.get("name"), str) or not r["name"]:
            out["problems"].append(f"{where} に name が無い")
            continue
        bad = [k for k in ("instructions", "model") if k in r and not isinstance(r[k], str)]
        if "settings" in r and not isinstance(r["settings"], dict):
            bad.append("settings")
        if bad:
            out["problems"].append(f"{where}（{r['name']}）: {', '.join(bad)} の形が違う（instructions・model は文字列、settings は表）")
            continue
        if r["name"] in out["roles"]:
            out["problems"].append(f"{where}: 役 {r['name']} が 2 度書かれている（先の物を使う）")
            continue
        out["roles"][r["name"]] = {"name": r["name"], "instructions": (r.get("instructions") or "").strip() or None,
                                   "model": r.get("model") or None, "settings": r.get("settings") or None}
    return out


def pick(shape, name, explicit):
    """役の名前から役の項目。(項目か None, 止める訳か None)。会社の形に役が書かれていて、名前を明示したのに無ければ止める
    （書き損じで設定が黙って効かないのを防ぐ）。明示していない既定の役が無いのは止めない。"""
    got = shape["roles"].get(name)
    if got is None and explicit and shape["roles"]:
        return None, f"役 {name} が会社の形に無い（在る役: {', '.join(shape['roles'])}）"
    return got, None


def _merge(base, top):
    out = dict(base)
    for k, v in top.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def settings_for(role):
    """部署を起こすときに --settings に渡す設定（dict）。役の設定に、必ず効かせる鍵（FIXED）を上から重ねる。"""
    return _merge((role or {}).get("settings") or {}, FIXED)


def gh_user(repo_user, shape):
    """部署の会話に渡す gh のアカウントと、注記。dispatch の設定の [[repos]] の gh_user を先に、無ければ会社の形の gh_user。
    利用者の手元の設定を先にするのは、commit された会社の形に書かれたアカウントは、ほかの人のものでありうるため。"""
    company = shape.get("gh_user")
    if repo_user and company and repo_user != company:
        return repo_user, f"gh のアカウントは dispatch の設定の {repo_user} を使う（会社の形の gh_user {company} より先）"
    return repo_user or company, None


def context(role_name, role, company):
    """フックが部署の会話の指示に足す文。会社と役の 1 行に、役の本文（会社の形に役の項目と本文が有れば）を続ける。"""
    head = f"この会話は会社「{company}」の部署で、役は「{role_name}」。"
    return head + (f"\n{role['instructions']}" if role and role["instructions"] else "")


SETTINGS_FILE = "company-settings.json"


def write_settings(folder, data):
    """部署を起こすときの設定を、部署の worktree の .git の場所（folder。commit されず、部署と一緒に消える）に書いてパスを返す。
    シェルに JSON を直に打ち込まない（Windows のシェルでは二重引用符を渡せない）。"""
    path = os.path.join(folder, SETTINGS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def warnings(role, plugin="works-dispatch"):
    """役の設定が、役を足すフックを持つこのプラグインを切っていれば、その注記。"""
    plugins = ((role or {}).get("settings") or {}).get("enabledPlugins")
    off = [k for k, v in (plugins.items() if isinstance(plugins, dict) else ()) if k.split("@")[0] == plugin and v is False]
    return [f"役 {role['name']} の設定が {', '.join(off)} を切っているので、部署の会話に役の本文が足されない"] if off else []


# 鍵を取り出せなかったときに GH_TOKEN に入れる字（gh が認証に失敗して止まり、ほかのアカウントに落ちない）
NO_TOKEN = "gh-user-not-logged-in"


def env_line(user):
    """SessionStart のフックが CLAUDE_ENV_FILE に足す 1 行。Claude Code は Bash の道具のコマンドごとに、このファイルをシェルのコードとして
    先に走らせる（hooks の文書 "Each Bash command runs the file's contents as shell code before the command itself"）ので、鍵の値は
    書かず、取り出すコマンドを書く。鍵はそのつど gh から取り出され、ファイルにも画面にも残らない。
    取り出せない（そのアカウントでログインしていない）ときは、空にせず使えない字を入れる。空の GH_TOKEN は無いのと同じに扱われ、gh が
    黙って有効なアカウントで動いてしまう（別の人として push やコメントをする）ため。
    起こすコマンドの前に環境変数として置く形は、裏の会話（--bg）に届かなかった（2026-10-16 に 2.1.301 で見た）。"""
    return f'export GH_TOKEN="$(gh auth token --user {shlex.quote(user)} || echo {NO_TOKEN})"'
