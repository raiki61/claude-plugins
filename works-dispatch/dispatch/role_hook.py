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
新しく起こした会話（startup）では書かない（部署の場所で人が別の会話を開いても、部署の会話を取り違えない）。本社（代表の clone）では
書かない（持ち主の会話がほかにも居て、どれが窓口か分からない）。
"""

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
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


def refresh_session(payload, cwd, attrs):
    """部署の会話をやり直して会話の id が変わったら、属性 company.session を書き直す。書いたら新しい id、書かなければ None。"""
    sid = payload.get("session_id")
    if not (attrs.get("role") and sid and payload.get("source") in RENEWED and attrs.get("session") != sid):
        return None
    here, common = gitx.git_dir(cwd), gitx.common_dir(cwd)
    if not here or not common or os.path.realpath(here) == os.path.realpath(common):
        return None   # 本社（代表の clone）
    provision.mark(cwd, gitx.root_of(common), provision.renew_session(attrs, sid), gitx)
    return sid


def text_for(cwd, env=os.environ, attrs=None):
    """その場所で足す文。部署でなければ None。"""
    attrs = gitx.worktree_attrs(cwd) if attrs is None else attrs
    name = attrs.get("role")
    if not name:
        return None
    common = gitx.common_dir(cwd)
    if not common:
        return None
    root = gitx.root_of(common)
    info = tree.read_info(root, os.path.dirname(config.path_of(attrs.get("config"), env)))
    shape = role.load(info["path"], info["text"])
    company = info.get("name") or os.path.basename(os.path.normpath(root))
    duty = next((x for x in info.get("skills", []) if attrs.get("name") and x.get("name") == attrs["name"]), None)
    text = role.context(name, shape["roles"].get(name), company, duty, gitx.is_main_worktree(cwd) is True)
    problems = info.get("problems", []) + shape["problems"]
    if problems:
        text += f"\n（会社の形を読めない所がある: {problems[0]}）"
    return text


def main(stdin=sys.stdin, env=os.environ):
    try:
        payload = json.loads(stdin.read() or "{}") or {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()
    attrs = gitx.worktree_attrs(cwd)
    try:
        refresh_session(payload, cwd, attrs)
    except gitx.GitError as e:
        print(f"works-dispatch: 部署の会話の id を書き直せなかった（{e}）", file=sys.stderr)
    try:
        put_env(attrs, env)
    except OSError as e:
        print(f"works-dispatch: GH_TOKEN を入れる行を書けなかった（{e}）", file=sys.stderr)
    text = text_for(cwd, env, attrs)
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
