#!/usr/bin/env python3
"""SessionStart のフック: 会話を起動した場所が部署か本社の窓口（--desk）なら、その役の本文を会話の指示に足す（会社の形の設計 4.8）。

起動した場所（フックの入力の cwd）の部署の属性 company.role（git config --worktree）を読み、会社の形（tree.read_info の読み方。
origin の既定のブランチに commit された .claude/company.toml、無ければ元の clone の作業ツリーの物、無ければ設定の置き場の companies/ の
中の、そのリポジトリの分）から役の項目を引いて、additionalContext として返す。役の属性の無い場所（--desk を打っていない本社や普通の
clone、git でない場所）では何も出さない。本社（代表の clone）の窓口には、部署ではなく本社の会話と書く。部署のブランチが書き換えた物も、
元の clone がたまたま開いているブランチの物も読まない（--task が起動の設定を決めたときと同じ物を読む）。
足す文は毎回の起動時の量に入るので、役の本文（instructions）と、会社の共通の本文（会社の形の頭の shared_instructions。部署だけ）と、
部署の名前と同じ name の受ける仕事（[[skills]]。受け持ち）の説明だけを足す。読めない・形が違うときも会話は止めない（何も足さないか、
訳を 1 行足す）。会話をやり直した（resume・clear・compact）ときにも走り、役が付き直す。

部署の属性 company.gh-user（--task が書く gh のアカウントの名前）があれば、Claude Code がフックに渡す CLAUDE_ENV_FILE に、その鍵を
GH_TOKEN に入れる 1 行（role.env_line）を足す。会話の Bash がコマンドごとに鍵を取り出す（鍵の値はどこにも書かない）。
設定の置き場は、部署の属性 company.config（--task が既定でない dispatch の設定を使ったときに書く）、無ければ既定の決まり。

部署の会話で /clear・compact・resume をすると会話の id が変わる（source が clear・compact・resume のときのフックの入力の
session_id）。そのとき部署の属性 company.session を新しい id に書き直す（refresh_session）。古い id のままだと、--ask が会話の
動き出しを見られず、Stop フックが部署の会話を別の会話と見て納品を促さず、落ちた部署を戻す attach が前の会話を戻した。
新しく起動した会話（startup）では書かない（部署の場所で人が別の会話を開いても、部署の会話を取り違えない）。本社（代表の clone）では、
--desk が書いた会話の処理の番号（company.pid）がこのフックの親の処理に在るときだけ書く（持ち主の会話がほかにも居るので、窓口の
会話と同じ処理の /clear だけを窓口の続きと見る）。

会社の形で役の名前を替え、前の名前を former_names に書いたら、属性 company.role に前の名前を持つ場所は、会話の始まりに今の名前に
書き直す（rename_role）。

UserPromptSubmit（`--prompt`）: ターンが始まるたび、その場所の役に今足す文を作り、この会話に前に足した文（会話ごとの控え。TMPDIR の
works-dispatch-role-<会話の id>）と違えば、今の文を足す（会社の形の名前・役・本文を替えたことを、会話を引き継いでいる部署と本社に
届ける。会話を空にしないので、持ち主との話は消えない）。同じなら何も出さない。控えが無い（この版より前に始まった会話）ときも足す。
待ち受けが会話を再開させるとき（wake_hook.py）も、同じ物を再開させる字の頭に足す（changed）。

会社（会社の形の在るリポジトリ。読み方は上と同じ tree.read_info）の場所で、役の本文を足さない会話（部署の属性の無い作業場の会話、
本社の窓口でない会話）には、ほかの会社への頼み方の 1 行（HINT。--ask <会社の名前> でその会社の窓口に届く）を足す。SendMessage で
頼むと受付の台帳に頼み元が残らず、受けた側が返し先を覚えておくしかなかった（2026-10-17 に guided-resolver のブランチの会話が my_notes の
段取りに頼んだ）。会社になる前から動いている会話にも届くよう、UserPromptSubmit でも、この会話にまだ何も足していなければ足す
（会社でない場所では何も書かないので、会社になった後のターンで届く。その代わり、会社でない git の場所の会話ではターンごとに会社の形を
読み直す git が 2〜3 回走る）。会社でないリポジトリの会話には何も足さない。
"""

import hashlib
import json
import os
import pathlib
import shlex
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    from ports import chat, term  # noqa: E402
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

DISPATCH_PY = str(pathlib.Path(__file__).resolve().parent / "dispatch.py")
# 会話に「この字で頼め」と渡す dispatch.py の起動コマンド（orders.RUN と同じ作り。この会話のフックは orders を読み込まずに済ませる）
RUN = " ".join(shlex.quote(pathlib.Path(x).as_posix()) for x in (sys.executable, DISPATCH_PY))

# 部署でない会話に足す、ほかの会社への頼み方（毎回の起動の量に入るので 1 行に保つ）
HINT = ("works-dispatch: ここは会社「{company}」のリポジトリだが、この会話は部署ではない。ほかの会社に頼むときは SendMessage でなく "
        "`{run} --ask <会社の名前> --text <頼み>` を打つ（その会社の窓口に届き、受付の台帳に頼み元が残って、納品はこの会話の "
        f"{term.NAME} の窓に返る。会社と仕事ごとの宛て方は同じコマンドの `--tree`）。")


def put_env(attrs, env):
    """部署の gh のアカウントの鍵を、会話の Bash の GH_TOKEN に入れる 1 行を CLAUDE_ENV_FILE に足す（もう在れば足さない）。"""
    path = env.get(chat.ENV_FILE)
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


def refresh_session(payload, cwd, attrs, same=lambda attrs: chat.in_process(attrs.get("pid"))):
    """部署か本社の窓口の会話をやり直して会話の id が変わったら、属性 company.session を書き直す。書いたら新しい id、書かなければ None。"""
    sid = payload.get("session_id")
    if not (attrs.get("role") and sid and payload.get("source") in RENEWED and attrs.get("session") != sid):
        return None
    here, common = gitx.git_dir(cwd), gitx.common_dir(cwd)
    if not here or not common:
        return None
    if provision.desk_seat(here, common, attrs) and not same(attrs):
        return None   # 窓口の席（本社か、本社の属性が写った作業場）の、窓口でない会話
    provision.mark(cwd, gitx.root_of(common), provision.renew_session(attrs, sid), gitx)
    return sid


def seated(payload, cwd, attrs, running=None, same=None):
    """この会話に、その場所の役の本文を足してよいか。部署の worktree なら足す。窓口の席（本社〔代表の clone〕か、本社の属性が写って
    残った作業場。provision.desk_seat）では、窓口の席に座る会話だけ:
    属性の会話（company.session）か、--desk を打った会話と同じ処理（company.pid。/clear の後）か、窓口の会話が動いていない
    ときに窓口の名前（company.name か前の名前）を付けて起動した会話（claude --name）。代表の clone で起きた試しや裏の 1 回きりの処理
    （claude -p。名前が無い）と、窓口が動いている間に起きたほかの会話には足さない（それらが窓口として振る舞い、--desk で席を
    取った。53d5d1・6be241）。"""
    if not provision.desk_seat(gitx.git_dir(cwd), gitx.common_dir(cwd), attrs):
        return True
    running = running or chat.running
    same = same or (lambda attrs: chat.in_process(attrs.get("pid")))
    sid = payload.get("session_id")
    if sid and sid == attrs.get("session") or same(attrs):
        return True
    if running(attrs.get("pid")):
        return False
    title = payload.get("session_title")
    return bool(title) and title in [attrs.get("name"), *gitx.former_names(attrs)]


def _shape_at(cwd, attrs, env):
    """(会社のルート, 会社の情報, 会社の形)。git でなければ None。"""
    common = gitx.common_dir(cwd)
    if not common:
        return None
    root = gitx.root_of(common)
    info = tree.read_info(root, os.path.dirname(config.path_of(attrs.get("config"), env)))
    return root, info, role.load(info["path"], info["text"])


def launch_key(cwd, attrs, env=os.environ):
    """その場所の部署を今起動するなら属性 company.launched に書く字（role.launch_key）。会社の形を読めない・役が無いときは None
    （読めないのを「model・effort を外した」と取り違えて起動し直さない）。"""
    got = attrs.get("role") and _shape_at(cwd, attrs, env)
    if not got:
        return None
    _, info, shape = got
    the_role = shape["roles"].get(role.current(shape, attrs["role"]))
    if the_role is None or shape["problems"] or info.get("problems"):
        return None
    here, common = gitx.git_dir(cwd), gitx.common_dir(cwd)
    if here and common and os.path.realpath(here) == os.path.realpath(common):
        return role.launch_key(the_role)   # 窓口は部署でないので受け持ちを引かない（--move の _move_desk が起動する値と揃える）
    return role.launch_key(the_role, role.duty_of(info.get("skills", []), attrs.get("name")))


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
    text = role.context(name, shape["roles"].get(name), company, duty, gitx.is_main_worktree(cwd) is True, attrs.get("lifecycle"),
                        shape["shared"])
    problems = info.get("problems", []) + shape["problems"]
    if problems:
        text += f"\n（会社の形を読めない所がある: {problems[0]}）"
    return text


def hint_for(cwd, env=os.environ, attrs=None):
    """部署でない会話に足す頼み方の 1 行（HINT）。会社の場所でなければ None。"""
    common = gitx.common_dir(cwd)
    if not common:
        return None
    attrs = gitx.worktree_attrs(cwd) if attrs is None else attrs
    root = gitx.root_of(common)
    info = tree.read_info(root, os.path.dirname(config.path_of(attrs.get("config"), env)))
    if not info.get("source"):
        return None
    return HINT.format(company=tree.company_name(root, info), run=RUN)


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


# ターンの途中で足す文の頭（会話の始まりに足した文を、今の物で読み替えさせる）
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


def late_hint(payload, cwd, attrs, env=os.environ, seated_=None):
    """この会話にまだ何も足していない（控えが無い）、役の本文を受けない会話で、場所が会社なら HINT。足したら控えを書く。
    会社になる前から動いている会話に、会社になった後のターンで届ける。"""
    sid = payload.get("session_id")
    if not sid or os.path.exists(seen_path(sid, env)):
        return None
    if attrs.get("role") and (seated_ or seated)(payload, cwd, attrs):
        return None   # 部署か窓口の会話（役の本文は changed が足す）
    text = hint_for(cwd, env, attrs)
    if text:
        remember(sid, text, env)
    return text


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
    text = changed(payload, env, attrs) or late_hint(payload, cwd, attrs, env)
    if text:
        print(chat.added_context(chat.PROMPT, text))
    return 0


def main(stdin=sys.stdin, env=os.environ):
    payload = _payload(stdin)
    cwd = payload.get("cwd") or os.getcwd()
    attrs = gitx.worktree_attrs(cwd)
    wrote = [None, None]
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
    text = text_for(cwd, env, attrs) if attrs.get("role") and seated(payload, cwd, attrs) else hint_for(cwd, env, attrs)
    if text:
        # 控えるのは引き継ぎの一行を付ける前の本文（次の発言の changed は text_for と比べるので、一行込みで控えると「会社の形が
        # 替わった」と役の本文を足し直す）
        remember(payload.get("session_id"), text, env)
    if text and wrote[0] and gitx.is_main_worktree(cwd) is True:
        # 本社の窓口の会話が /clear などで会話の id を替えた: 席はこのフックが引き継いだと会話に知らせる（窓口が空にした後に毎回
        # --desk --dry-run を打って確かめなくてよい。c52730 の 6）
        text += (f"\n（窓口 {attrs.get('name') or '-'} の席はこの会話に引き継いだ: 属性の会話の id（company.session）をこの会話の id に"
                 "書き直した。--desk を打ち直さなくてよい）")
    if text:
        print(chat.added_context(chat.START, text))
    return 0


if __name__ == "__main__":
    sys.exit(prompt() if sys.argv[1:2] == ["--prompt"] else main())
