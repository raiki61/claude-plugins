#!/usr/bin/env python3
"""SessionStart のフック: 会話を起こした場所が部署か本社の窓口（--desk）なら、その役の本文を会話の指示に足す（会社の形の設計 4.8）。

起こした場所（フックの入力の cwd）の部署の属性 company.role（git config --worktree）を読み、会社の形（tree.read_info の読み方。
origin の既定の枝に commit された .claude/company.toml、無ければ元の clone の作業ツリーの物、無ければ設定の置き場の companies/ の
中の、そのリポジトリの分）から役の項目を引いて、additionalContext として返す。役の属性の無い場所（--desk を打っていない本社や普通の
clone、git でない場所）では何も出さない。本社（代表の clone）の窓口には、部署ではなく本社の会話と書く。部署の枝が書き換えた物も、
元の clone がたまたま開いている枝の物も読まない（--task が起動の設定を決めたときと同じ物を読む）。
足す文は毎回の起動時の量に入るので、役の本文（instructions）と、部署の名前と同じ name の受ける仕事（[[skills]]。受け持ち）の
説明だけを足す。読めない・形が違うときも会話は止めない（何も足さないか、
訳を 1 行足す）。会話をやり直した（resume・clear・compact）ときにも走り、役が付き直す。

部署の属性 company.gh-user（--task が書く gh のアカウントの名前）があれば、Claude Code がフックに渡す CLAUDE_ENV_FILE に、その鍵を
GH_TOKEN に入れる 1 行（role.env_line）を足す。会話の Bash がコマンドごとに鍵を取り出す（鍵の値はどこにも書かない）。
設定の置き場は、部署の属性 company.config（--task が既定でない dispatch の設定を使ったときに書く）、無ければ既定の決まり。

部署の会話で /clear・compact・resume をすると会話の id が変わる（source が clear・compact・resume のときのフックの入力の
session_id）。そのとき部署の属性 company.session を新しい id に書き直す（refresh_session）。古い id のままだと、--ask が会話の
動き出しを見られず、Stop フックが部署の会話を別の会話と見て納品を促さず、落ちた部署を戻す attach が前の会話を戻した。
新しく起こした会話（startup）では書かない（部署の場所で人が別の会話を開いても、部署の会話を取り違えない）。本社（代表の clone）では、
--desk が書いた会話の処理の番号（company.pid）がこのフックの親の処理に在るときだけ書く（持ち主の会話がほかにも居るので、窓口の
会話と同じ処理の /clear だけを窓口の続きと見る）。

会社の形で役の名前を替え、前の名前を former_names に書いたら、属性 company.role に前の名前を持つ場所は、会話の始まりに今の名前に
書き直す（rename_role）。

UserPromptSubmit（`--prompt`）: 番が始まるたび、その場所の役に今足す文を作り、この会話に前に足した文（会話ごとの控え。TMPDIR の
works-dispatch-role-<会話の id>）と違えば、今の文を足す（会社の形の名前・役・本文を替えたことを、会話を持ち越している部署と本社に
届ける。会話を空にしないので、持ち主との話は消えない）。同じなら何も出さない。控えが無い（この版より前に始まった会話）ときも足す。
待ち受けが会話を起こすとき（wake_hook.py）も、同じ物を起こす字の頭に足す（changed）。
"""

import hashlib
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    import claudex  # noqa: E402
    import config  # noqa: E402
    import gitx  # noqa: E402
    from nodes import provision, role, tree  # noqa: E402
except (ImportError, SyntaxError) as _e:
    # どの会話の始まりにも走るので、PATH の python3 が古い（tomllib の無い 3.10 以前）ときも会話を邪魔しない
    print(f"works-dispatch: 役を足すフックを動かせない（Python 3.11 以上が要る: {_e}）", file=sys.stderr)
    sys.exit(0)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def put_env(attrs, env):
    """部署の gh のアカウントの鍵を、会話の Bash の GH_TOKEN に入れる 1 行を CLAUDE_ENV_FILE に足す（もう在れば足さない）。"""
    path = env.get("CLAUDE_ENV_FILE")
    if not attrs.get("gh-user") or not path:
        return
    line = role.env_line(attrs["gh-user"])
    try:
        with open(path, encoding="utf-8") as f:
            if line in f.read().splitlines():
                return
    except OSError:
        pass
    with open(path, "a", encoding="utf-8", newline="\n") as f:   # bash が走らせるので、Windows でも行末に \r を付けない
        f.write(line + "\n")


# 会話の id が変わるやり直し（SessionStart の source）
RENEWED = ("clear", "compact", "resume")


def refresh_session(payload, cwd, attrs, same=lambda attrs: claudex.in_process(attrs.get("pid"))):
    """部署か本社の窓口の会話をやり直して会話の id が変わったら、属性 company.session を書き直す。書いたら新しい id、書かなければ None。"""
    sid = payload.get("session_id")
    if not (attrs.get("role") and sid and payload.get("source") in RENEWED and attrs.get("session") != sid):
        return None
    here, common = gitx.git_dir(cwd), gitx.common_dir(cwd)
    if not here or not common:
        return None
    if os.path.realpath(here) == os.path.realpath(common) and not same(attrs):
        return None   # 本社（代表の clone）の、窓口でない会話
    provision.mark(cwd, gitx.root_of(common), provision.renew_session(attrs, sid), gitx)
    return sid


def _shape_at(cwd, attrs, env):
    """(会社の根, 会社の情報, 会社の形)。git でなければ None。"""
    common = gitx.common_dir(cwd)
    if not common:
        return None
    root = gitx.root_of(common)
    info = tree.read_info(root, os.path.dirname(config.path_of(attrs.get("config"), env)))
    return root, info, role.load(info["path"], info["text"])


def flags_now(cwd, attrs, env=os.environ):
    """会社の形の今の値で、この部署を起こすなら付ける {model, effort}（role.launch_flags と同じ決める順。値の無い欄は None）。
    effort の inherit は、起こした会話の effort を受け継ぐ意味なので、起こした後には決めない（None）。"""
    got = _shape_at(cwd, attrs, env) if attrs.get("role") else None
    if not got:
        return {"model": None, "effort": None}
    _, info, shape = got
    the_role = shape["roles"].get(role.current(shape, attrs["role"]))
    duty = next((x for x in info.get("skills", []) if attrs.get("name") and x.get("name") == attrs["name"]), None)
    model, effort, _ = role.launch_flags(the_role, {}, duty)
    return {"model": model, "effort": effort}


def rename_role(cwd, attrs, env=os.environ):
    """属性 company.role が役の前の名前（former_names）なら、今の名前に書き直す。書いたら今の名前、書かなければ None。"""
    if not attrs.get("role"):
        return None
    got = _shape_at(cwd, attrs, env)
    now = got and role.current(got[2], attrs["role"])
    if not now or now == attrs["role"]:
        return None
    provision.mark(cwd, got[0], {"role": now}, gitx)
    return now


def text_for(cwd, env=os.environ, attrs=None):
    """その場所で足す文。部署でなければ None。"""
    attrs = gitx.worktree_attrs(cwd) if attrs is None else attrs
    if not attrs.get("role"):
        return None
    got = _shape_at(cwd, attrs, env)
    if not got:
        return None
    root, info, shape = got
    name = role.current(shape, attrs["role"])
    company = info.get("name") or os.path.basename(os.path.normpath(root))
    duty = next((x for x in info.get("skills", []) if attrs.get("name") and x.get("name") == attrs["name"]), None)
    text = role.context(name, shape["roles"].get(name), company, duty, gitx.is_main_worktree(cwd) is True)
    problems = info.get("problems", []) + shape["problems"]
    if problems:
        text += f"\n（会社の形を読めない所がある: {problems[0]}）"
    return text


def seen_path(sid, env=os.environ):
    """この会話に前に足した文の控え（中身の digest）の置き場。"""
    folder = env.get("TMPDIR") or tempfile.gettempdir()
    return os.path.join(folder, f"works-dispatch-role-{''.join(c for c in sid if c.isalnum() or c == '-')}")


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def remember(sid, text, env=os.environ):
    """この会話に足した文の控えを書く。書けなくても会話は止めない。"""
    if not sid:
        return
    try:
        with open(seen_path(sid, env), "w", encoding="utf-8") as f:
            f.write(_digest(text))
    except OSError:
        pass


# 番の途中で足す文の頭（会話の始まりに足した文を、今の物で読み替えさせる）
CHANGED_HEAD = "会社の形が替わったので、この会話の役を今の物に読み替える（前に足された役の本文より、こちらが先）:"


def changed(payload, env=os.environ, attrs=None):
    """この会話に前に足した文と、その場所の役に今足す文が違えば、足す字（CHANGED_HEAD と今の文）。同じか役の無い場所なら None。"""
    sid, cwd = payload.get("session_id"), payload.get("cwd") or os.getcwd()
    if not sid:
        return None
    attrs = gitx.worktree_attrs(cwd) if attrs is None else attrs
    if not attrs.get("role") or attrs.get("session") and attrs["session"] != sid:
        return None   # 部署でない場所か、場所の属性の会話でない会話（本社の持ち主のほかの会話など）
    text = text_for(cwd, env, attrs)
    if not text:
        return None
    try:
        with open(seen_path(sid, env), encoding="utf-8") as f:
            if f.read().strip() == _digest(text):
                return None
    except OSError:
        pass
    remember(sid, text, env)
    return f"{CHANGED_HEAD}\n{text}"


def _payload(stdin):
    try:
        payload = json.loads(stdin.read() or "{}") or {}
    except ValueError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def prompt(stdin=sys.stdin, env=os.environ):
    """UserPromptSubmit（--prompt）。役の文が替わっていれば、今の文を足す。"""
    payload = _payload(stdin)
    cwd = payload.get("cwd") or os.getcwd()
    attrs = gitx.worktree_attrs(cwd)
    try:
        if rename_role(cwd, attrs, env):
            attrs = gitx.worktree_attrs(cwd)
    except (gitx.GitError, OSError) as e:
        print(f"works-dispatch: 役の名前を書き直せなかった（{e}）", file=sys.stderr)
    text = changed(payload, env, attrs)
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}},
                         ensure_ascii=False))
    return 0


def main(stdin=sys.stdin, env=os.environ):
    payload = _payload(stdin)
    cwd = payload.get("cwd") or os.getcwd()
    attrs = gitx.worktree_attrs(cwd)
    try:
        wrote = [refresh_session(payload, cwd, attrs), rename_role(cwd, attrs, env)]
        if any(wrote):
            attrs = gitx.worktree_attrs(cwd)
    except (gitx.GitError, OSError) as e:
        print(f"works-dispatch: 部署の会話の id か役の名前を書き直せなかった（{e}）", file=sys.stderr)
    try:
        put_env(attrs, env)
    except OSError as e:
        print(f"works-dispatch: GH_TOKEN を入れる行を書けなかった（{e}）", file=sys.stderr)
    text = text_for(cwd, env, attrs)
    if text:
        remember(payload.get("session_id"), text, env)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(prompt() if sys.argv[1:2] == ["--prompt"] else main())
