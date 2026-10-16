#!/usr/bin/env python3
"""role ノード: 会社の形のファイル（tree.read_info が見つけた物）から、役の項目と gh のアカウントを読み、部署に渡す物を組み立てる。書くのは、部署を起こすときの設定のファイル 1 つ（write_settings）だけ。

会社の形の設計（docs/specs/2026-10-16-company-shape-design.md）の 4.7（役ごとに起動時の文脈を絞る）と 4.8（役の渡し方）に当たる。
役は会社の形の [[roles]] に 1 つずつ書く。欄は次のとおりで、知らない欄は読み飛ばす。
- name: 役の名前（部署の属性 company.role と同じ字）
- instructions: 部署の会話の指示に足す役の本文。SessionStart のフックが毎回の起動で足すので短くし、AGENTS.md と同じことは書かない
- model: 部署を起こすときの --model
- settings: 部署を起こすときの --settings に渡す Claude Code の設定（表）。enabledPlugins・permissions.deny・skillOverrides など。
  その会話にだけ効き、利用者の全体の設定とリポジトリの設定は触らない
- deliver: その役が納品する要約の必須の項目（空でない文字列の並び）。省けば既定の項目（deliver ノードが持つ）
- resident: true なら、その役の部署は常設（--resident を付けたのと同じ）。担当のように受け持ちに常設の役に書く。役で宛てた頼み
  （--ask 会社/役）で部署がまだ無いときに --resident を付け忘れると、都度の部署が立って次の頼みがその部署を見つけないため
- fresh: true なら、その役の部署は頼みごとに空の会話で受ける（前の頼みを納品し終えていれば、--ask が新しい頼みを打つ前に /clear を
  打つ）。省けば会話を持ち越す。resident とは別の軸で、常設の席（順番を 1 本にする・宛先の名前・決まった窓）は残したまま、
  前の頼みの記憶を持ち越さない（記憶は太るうえ、覚えた中身で書き直すと、ほかの部署が入れた行を消す。まっさらな環境での 2 回目の試し）
役ごとの項目を名前で引く表（[roles."役"]）の形は読まず、[[roles]] に移すよう problems に書く（TOML では同じ鍵 roles を
表の並びと表の両方で書けず、二つの形を混ぜると片方が黙って効かないため）。
会社の形の頭の gh_user は、その会社の gh のアカウント（部署の会話の Bash に GH_TOKEN として入れる。env_line）。
会社の形の頭の default_role は、--task で --role を省いたときの役（[[roles]] のどれかの name）。省けば入口の既定（作業）。

入口の dispatch.py --task が起こすときに load・pick・settings_for・write_settings・gh_user・warnings を呼び、プラグインのフック
role_hook.py が context と env_line を呼ぶ。
"""

import json
import os
import shlex
import tomllib

# 頼みごとに空の会話で受ける部署の属性 company.fresh の値（役の fresh = true を写す。無ければ会話を持ち越す）
FRESH = "true"

# 部署を起こすときに必ず効かせる設定の鍵。役の設定より強い（裏の会話が自分で worktree を作らず、先に作った作業場で働くため）
FIXED = {"worktree": {"bgIsolation": "none"}}


def seat(residency, fresh):
    """部署の席の見え方（herdr の表示名と --tree に役の後ろへ添える字）。常設なら会話の持ち越し方も添える。"""
    if residency == "resident":
        return "常設・毎回空" if fresh else "常設・持ち越し"
    return "都度"


def _empty():
    return {"roles": {}, "gh_user": None, "default_role": None, "problems": []}


def load(path, text=None):
    """会社の形のファイルから {roles: 名前 → {name, instructions, model, settings, deliver, resident, fresh}, gh_user, default_role, problems}。
    path が None なら空。
    text を渡せば、それを中身として読む（tree.read_info が読んだ物。path は注記に出す場所の札）。
    形の違う役は problems に書いて外し、ほかの役は読む。"""
    out = _empty()
    if not path:
        return out
    try:
        if text is None:
            with open(path, "rb") as f:
                raw = tomllib.load(f)
        else:
            raw = tomllib.loads(text)
    except (OSError, tomllib.TOMLDecodeError) as e:
        out["problems"].append(f"{path}: TOML として読めない（{e}）")
        return out
    gh_user = raw.get("gh_user")
    if gh_user is not None and not (isinstance(gh_user, str) and gh_user):
        out["problems"].append(f"{path}: gh_user が文字列で無い")
    elif gh_user:
        out["gh_user"] = gh_user
    roles = raw.get("roles", [])
    if isinstance(roles, dict):
        out["problems"].append(f"{path}: 役を [roles.\"役\"] の形で書いている（{', '.join(roles)}）。この形は読まないので、"
                               f"[[roles]] の項目（name = \"役\"）に移す")
        return out
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
        bad += [k for k in ("resident", "fresh") if k in r and not isinstance(r[k], bool)]
        if "deliver" in r and not (isinstance(r["deliver"], list) and r["deliver"]
                                   and all(isinstance(x, str) and x.strip() for x in r["deliver"])):
            bad.append("deliver")
        if bad:
            out["problems"].append(f"{where}（{r['name']}）: {', '.join(bad)} の形が違う（instructions・model は文字列、settings は表、"
                                   f"deliver は空でない文字列の並び、resident・fresh は true か false）")
            continue
        if isinstance(r.get("settings"), dict) and "deliver" in r["settings"]:
            out["problems"].append(f"{where}（{r['name']}）: deliver が [roles.settings] の中に入っている（deliver は [roles.settings] "
                                   f"より前に書く）")
        if r["name"] in out["roles"]:
            out["problems"].append(f"{where}: 役 {r['name']} が 2 度書かれている（先の物を使う）")
            continue
        out["roles"][r["name"]] = {"name": r["name"], "instructions": (r.get("instructions") or "").strip() or None,
                                   "model": r.get("model") or None, "settings": r.get("settings") or None,
                                   "deliver": [x.strip() for x in r["deliver"]] if "deliver" in r else None,
                                   "resident": r.get("resident") is True, "fresh": r.get("fresh") is True}
    default = raw.get("default_role")
    if default is not None and not (isinstance(default, str) and default):
        out["problems"].append(f"{path}: default_role が文字列で無い")
    elif default and default not in out["roles"]:
        out["problems"].append(f"{path}: default_role の役 {default} が [[roles]] に無い（在る役: {', '.join(out['roles']) or 'なし'}）")
    elif default:
        out["default_role"] = default
    return out


def default(shape, builtin):
    """--role を省いたときの役の名前と注記。会社の形の default_role を先に、無ければ builtin。会社の形に役が書かれていて、
    その役が無ければ注記にする（止めない。役の本文と起動の設定が付かないことを知らせる）。"""
    name = shape.get("default_role") or builtin
    if shape["roles"] and name not in shape["roles"]:
        return name, (f"--role を省いたので役は既定の {name} だが、会社の形に無いので、役の本文と起動の設定が付かない"
                      f"（--role で名指すか、会社の形の頭に default_role = \"<役>\" を書く。在る役: {', '.join(shape['roles'])}）")
    return name, None


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


def context(role_name, role, company, duty=None):
    """フックが部署の会話の指示に足す文。会社と役の 1 行に、受け持ち（duty。部署の名前と同じ name の受ける仕事 [[skills]] の項目が
    有れば）と、役の本文（会社の形に役の項目と本文が有れば）を続ける。受け持ちを足すのは、役を 1 つ（担当）にして、受け持ちごとの
    中身を部署の名前で引くため。"""
    head = f"この会話は会社「{company}」の部署で、役は「{role_name}」。"
    if duty and duty.get("description"):
        head += f"受け持ちは「{duty['name']}」（{duty['description']}）。"
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
