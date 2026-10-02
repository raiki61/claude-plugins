#!/usr/bin/env python3
"""destgate — 投稿の宛先を許可一覧で縛る門番(PreToolUse:Bash)。

coldread(通じやすさ)とは別の軸「その宛先へ出してよいか」を検査する。
許可一覧が無ければ眠っている(何も出さず allow)。一覧の管理は人の仕事で、
モデルが自分で追記して通すのは門番の無効化になる——deny 文言でも明示する。

coldread と別フックにしてあるのは、COLDREAD_SKIP=1(通じやすさ検査の逃げ道)で
宛先の検査まで外れる経路を作らないため。宛先の判定は決定的(LLM なし)なので、
この門番自身には逃げ道が無い——通したければ人が一覧へ追記する。それが記録になる。
解析部(トークン化・単純コマンド分割・旗表)は coldread-gate.py から読み込んで共有する。
"""
import collections
import fnmatch
import functools
import importlib.util
import json
import os
import re
import subprocess
import sys

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_spec = importlib.util.spec_from_file_location(
    "coldread_gate",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "coldread-gate.py"),
)
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)

CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
STATE_DIR = os.path.join(CONFIG_DIR, "destgate")
ALLOWLIST = os.path.join(STATE_DIR, "allowlist")
DENY_LOG = os.path.join(STATE_DIR, "denies.log")


def patterns():
    """許可一覧(1 行 1 パターン。owner/repo・owner/*・gist。# 始まりと空行は無視)。"""
    try:
        with open(ALLOWLIST, encoding="utf-8") as f:
            return [ln.strip() for ln in f
                    if ln.strip() and not ln.strip().startswith("#")]
    except OSError:
        return []


def owner_repo(value):
    r"""-R の値や URL から owner/repo を取り出す。取れなければ None。

    gh は OWNER/REPO・HOST/OWNER/REPO・完全 URL(https/ssh)のどれも受けるので、
    末尾 2 セグメントを取り .git を落とす。ssh の別名ホスト(github.com-xxx:o/r)も
    : 以降がパスなので同じ規則で拾える。

    **区切りは `/` だけではない。** Windows の checkout では origin が `C:\...\o\r.git` の形で
    来るので、`/` 固定だと末尾 2 セグメントが取れず、宛先を特定できないまま deny になる(投稿は
    止まるが、正しく書いた投稿が「宛先不明」で止まる)。同じ規則の姉妹は attention の
    changemap.py の REPO_TAIL——2026-09-16 にそちらだけ直して、この写しが `/` 固定で残った。
    """
    v = value.strip().replace("\\", "/").rstrip("/")
    v = re.sub(r"^[a-z+]+://", "", v)
    v = v.split(":", 1)[-1] if ":" in v and "/" not in v.split(":", 1)[0] else v
    parts = [p for p in v.split("/") if p]
    if len(parts) < 2:
        return None
    o, r = parts[-2], parts[-1]
    r = re.sub(r"\.git$", "", r)
    if not o or not r or o.startswith("-"):
        return None
    return f"{o}/{r}"


# GitHub の owner と repo の名前に入る字(英数字と . - _)。コマンドに書かれた宛先はこれで照らす——展開($…・`…`・
# $(…))を含む字を展開前の字のまま許可一覧に照らすと、bash が展開した後の別の宛先へ投稿する
NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
# -R の値に書ける字(OWNER/REPO・HOST/OWNER/REPO・https や ssh の URL)
_REPO_VALUE_RE = re.compile(r"[A-Za-z0-9._:/@+-]+")
# gh api のパスで gh 自身が今のリポジトリに置き換える置き場所
PLACEHOLDERS = ("{owner}", "{repo}")


def command_repo(value):
    """コマンドに書かれた宛先(-R の値・GH_REPO)→ owner/repo。展開や名前に入らない字を含めば None。"""
    v = value.strip()
    repo = owner_repo(v) if _REPO_VALUE_RE.fullmatch(v) else None
    return repo if repo and all(NAME_RE.fullmatch(p) for p in repo.split("/")) else None


def _git_lines(cwd, *argv):
    try:
        return subprocess.run(["git", "-C", cwd or ".", *argv],
                              capture_output=True, encoding="utf-8", timeout=10).stdout.splitlines()
    except Exception:
        return []


@functools.lru_cache(maxsize=None)
def remote_repos(cwd):
    """cwd の git の (remote ごとの owner/repo, remote ごとの gh repo set-default の値)。git が読めなければ空。

    読むのは gh が読む 2 つ(git remote -v と remote.<名>.gh-resolved)。子のプロセスは cwd ごとに 1 回ずつ——投稿の gh
    ごとに起こすと、-R の無い投稿を並べた入力でフックの timeout に届き、残りの宛先を見ないまま通る。
    """
    repos = {}
    for line in _git_lines(cwd, "remote", "-v"):
        name, _tab, url = line.partition("\t")   # 「名前<タブ>URL (fetch)」。URL は空白を含みうる(Windows のパス)
        repo = owner_repo(url.rsplit(" (", 1)[0]) if url else None
        if repo:
            repos.setdefault(name, repo)
    resolved = {}
    for line in _git_lines(cwd, "config", "--get-regexp", r"^remote\..*\.gh-resolved$"):
        key, _sp, value = line.partition(" ")
        resolved[key[len("remote."):-len(".gh-resolved")]] = value.strip()
    return repos, resolved


def repos_at(cwd):
    """cwd で -R の無い gh が選びうる宛先。決まらなければ None。

    set-default が在ればそれ(値が base ならその remote、owner/repo の字ならその repo。cli/cli の context.go の
    BaseRepo)、無ければ remote の全部——gh は remote の優先順(upstream が origin より先)の先頭を選ぶが、版ごとの
    順は写さず、どれになっても許可一覧に当たる必要があるとする。
    """
    remotes, resolved = remote_repos(cwd)
    picked = []
    for name, value in resolved.items():
        if not value:
            continue
        if value == "base":
            picked += [remotes[name]] if name in remotes else []
        else:
            repo = command_repo(value)
            if repo is None:
                return None
            picked.append(repo)
    return picked or sorted(set(remotes.values()))


# コマンドの中で書く GH_REPO(gh 自身の前置は除く)。values は字で書いた値、unset は消す形が在るか、undecidable は
# 値を字から読めない形(read・for・printf -v・declare -n・${GH_REPO:=…} など)が在るか
Written = collections.namedtuple("Written", "values unset undecidable")
NOTHING_WRITTEN = Written((), False, False)
# gh 自身の前置(GH_REPO=値・env の旗)。gh_repo は最後に書いた値か None、cleared は環境の GH_REPO を外すか
# (env -u GH_REPO・env -i)、split は env -S(値を env が語に割るので、前置の中身を字から読めない)
CallEnv = collections.namedtuple("CallEnv", "gh_repo cleared split")
NO_ENV = CallEnv(None, False, False)
_GH_REPO_RE = re.compile(r"(?<![A-Za-z0-9_])GH_REPO(?![A-Za-z0-9_])")
# 変数を宣言して値を書く語。引数の GH_REPO=値 は字のまま読む
_DECLARES = {"export", "declare", "typeset", "readonly", "local"}
# ほかに変数を書きうる語。引数に GH_REPO の名前が在れば値を字から読めない(printf は -v を付けたときだけ書く)。
# echo・test・cd など書かない語と、子のプロセスで走る命令(git commit -m 'GH_REPO …')の引数は数えない
_WRITES_VARS = {"read", "mapfile", "readarray", "getopts", "printf", "for", "select", "let", "eval"}
# 命令の位置にあって後ろに命令を取る語のうち、split_commands が読み飛ばさないもの(while read GH_REPO の read・
# builtin export GH_REPO=… の export・builtin cd … の cd を見る)
_LEADS = {"if", "while", "until", "coproc", "builtin"}


def _command(args):
    """単純コマンドの語 → (前置, 命令名からの語)。if・while などの後ろの命令まで進む(語を切り出し直さずに位置で
    進める——切り出すと if を並べた入力で長さの 2 乗になる)。"""
    start = 0
    while True:
        at = cr.read_prefix(args, start).at
        if at < len(args) and args[at] in _LEADS:
            start = at + 1
            continue
        return args[start:at], args[at:]


def _simple_commands(analysis):
    """コマンドの全部の字列の単純コマンドを、解けない展開を書かれたとおりの字に戻した語で(展開を含む値は
    command_repo が None にする)。読むのは gh_calls と同じ、値の決まる置換を解いた後の語。"""
    for seg in analysis.words.parsed:
        for c in seg.cmds:
            yield _command(cr.unmark(c.args, analysis.scanned))


def written_gh_repo(analysis):
    """コマンドの中で書く GH_REPO → Written。gh 自身の前置と、gh・子のプロセスの引数の字は数えない。"""
    values, unset, undecidable = [], False, False
    for e in analysis.scanned.exps:
        text = e.span[0][e.span[1]:e.span[2]]
        if e.kind not in cr.COMMAND_KINDS and not cr._PLAIN_PARAM_RE.fullmatch(text) and _GH_REPO_RE.search(text):
            undecidable = True   # ${GH_REPO:=…}・$((GH_REPO=…))
    for prefix, rest in _simple_commands(analysis):
        if not rest:
            values += [a[len("GH_REPO="):] for a in prefix if a.startswith("GH_REPO=")]
            continue
        name, args = rest[0], rest[1:]
        if name in _DECLARES:
            flags = "".join(a for a in args if a.startswith(("-", "+")))
            for a in args:
                if a.startswith(("-", "+")) or not _GH_REPO_RE.search(a):
                    continue
                if a.startswith("GH_REPO=") and "n" not in flags:
                    values.append(a[len("GH_REPO="):])
                elif not (a == "GH_REPO" and name in ("export", "readonly") and "n" not in flags):
                    undecidable = True   # declare -n・GH_REPO+=…・local GH_REPO
        elif name == "unset":
            unset = unset or any(_GH_REPO_RE.search(a) for a in args)
        elif name in _WRITES_VARS and (name != "printf" or any(a.startswith("-v") for a in args)):
            undecidable = undecidable or any(_GH_REPO_RE.search(a) for a in args)
    return Written(tuple(values), unset, undecidable)


def call_env(prefix):
    """gh 自身の前置の語 → CallEnv。"""
    p = cr.read_prefix(list(prefix))
    values = [a[len("GH_REPO="):] for a in p.assigns if a.startswith("GH_REPO=")]
    return CallEnv(
        values[-1] if values else None,
        any((f in ("-u", "--unset") and v == "GH_REPO") or f in ("-i", "--ignore-environment", "-") for f, v in p.flags),
        any(f in ("-S", "--split-string") for f, _v in p.flags),
    )


def moves(analysis):
    """コマンドの中の cd・pushd・env -C の行き先(書かれたとおりの字)。書いた位置とどの命令に効くかは推さない——
    Ambient が全部の和で照らす。"""
    out = []
    for prefix, rest in _simple_commands(analysis):
        out += [v for f, v in cr.read_prefix(prefix).flags if f in cr.WRAPPER_CHDIR]
        if rest[:1] in (["cd"], ["pushd"]):
            targets = [a for a in rest[1:] if not (a.startswith("-") and a != "-")]   # -P・-L・-e・-@・--
            out.append(targets[0] if targets else ("~" if rest[0] == "cd" else "-"))
    return out


def _place(target, cwd, alone):
    """cd の行き先の字 → 絶対パス。字のまま決まらなければ None(展開・cd -・pushd +N・~user・ほかの cd に続きうる
    相対パス)。"""
    if target == "~" or target.startswith("~/"):
        target = os.path.expanduser("~") + target[1:]
    if target in ("", "-") or target.startswith(("+", "~")) or cr._EXPANDED_PATH_RE.search(target):
        return None
    if os.path.isabs(target):
        return os.path.normpath(target)
    if alone and cwd and os.path.isabs(cwd):
        return os.path.normpath(os.path.join(cwd, target))
    return None


class Ambient:
    """-R の無い投稿で gh が使う宛先の候補を、部品(宛先の tuple)の列で返す。どの部品の宛先も許可一覧に当たる必要がある。

    gh は GH_REPO を git remote より先に使う。コマンドの中で書いた GH_REPO の位置・export の有無・cd の順は推さず、
    なりうるものの和で照らす(和は移る前の cwd の remote を含むので、BASE が止めた投稿を通さない)。
    大きくなりうる部品(コマンドの中で書いた GH_REPO の値・移った先の remote・それを埋めた api のパス)はコマンドにつき
    1 回だけ作って同じ tuple を返し、kept に載せる——gh の呼び出しごとに作り直すか照らし直すと、gh と GH_REPO・cd を
    並べた入力で重さが 2 乗になり、上限の無い destgate がフックの timeout で外れる。
    """

    def __init__(self, cwd, written=NOTHING_WRITTEN, moved=()):
        self.cwd, self.written, self.moved = cwd, written, tuple(moved)
        self.memo, self.kept = {}, set()

    def _once(self, key, make):
        if key not in self.memo:
            value = self.memo[key] = make()
            if value is not None:
                self.kept.add(id(value))
        return self.memo[key]

    def _written(self):
        if self.written.undecidable:
            return None
        got = tuple(command_repo(v) for v in self.written.values)
        return None if None in got else got

    def _outside(self):
        value = os.environ.get("GH_REPO")
        repo = command_repo(value) if value else None
        return () if not value else (repo,) if repo else None

    def _remotes(self):
        out = []
        for place in (self.cwd,) + tuple(_place(t, self.cwd, len(self.moved) == 1) for t in self.moved):
            got = repos_at(place) if place is not None else None
            if got is None:
                return None
            out += got
        return tuple(sorted(set(out)))

    def parts(self, env=NO_ENV):
        """gh 自身の前置 env の下の候補の部品の列。決まらなければ None。"""
        if env.split:
            return None
        own = command_repo(env.gh_repo) if env.gh_repo is not None else None
        if env.gh_repo is not None and (own is None or not env.cleared):
            return None if own is None else [(own,)]
        parts = [self._once("written", self._written)] + ([(own,)] if own else [])
        outside = () if env.cleared else self._once("outside", self._outside)
        parts.append(outside)
        if not outside or self.written.unset:
            parts.append(self._once("remotes", self._remotes))
        return None if any(p is None for p in parts) else parts

    def filled(self, part, owner, repo):
        """api のパスの {owner}・{repo} を部品の宛先で埋めた部品。名前に入らない字になれば None。"""
        def make():
            got = []
            for dest in part:
                o, r = dest.split("/")
                got.append(_name_pair(owner.replace("{owner}", o).replace("{repo}", r),
                                      repo.replace("{owner}", o).replace("{repo}", r)))
            return None if None in got else tuple(got)
        return self._once(("filled", id(part), owner, repo), make) if id(part) in self.kept else make()


def dest_parts(args, env, ambient):
    """gh の引数列 → 投稿の宛先の部品の列(どの宛先も許可一覧に当たる必要がある)。分からなければ None。"""
    sub = cr.subcommand(args)
    if sub is None:
        return None   # サブコマンドより前の知らない旗: 宛先が api のパスか -R かも決まらない
    # -R / --repo が最優先(gh 自身の解決順もこれが勝つ)。2 つ以上書けば gh は最後の値を使うので、全部を照らす
    explicit = tuple(command_repo(v) for v in cr.repo_flags(args, sub))
    if None in explicit:
        return None
    if sub[:1] == ("api",):
        # gh api の宛先はパスが決める(-R は照らす側に足すだけ)
        path = _api_parts(sub, env, ambient)
        return None if path is None else [explicit] + path
    if explicit:
        return [explicit]
    if sub[:1] == ("gist",):
        return [("gist",)]
    return ambient.parts(env)


def dest_of(args, cwd, env=NO_ENV, written=NOTHING_WRITTEN, moved=()):
    """1 つの gh の呼び出しの宛先の列(dest_parts を平らにしたもの)。分からなければ None。"""
    parts = dest_parts(args, env, Ambient(cwd, written, moved))
    return None if parts is None else [dest for part in parts for dest in part]


def _api_parts(sub, env, ambient):
    path = cr.api_path(sub)
    seg = [p for p in (path or "").split("/") if p]
    if len(seg) >= 3 and seg[0] == "repos":
        owner, repo = seg[1], seg[2]
    elif len(seg) >= 2 and seg[0] == "orgs":
        owner, repo = seg[1], "*"
    else:
        return None  # graphql・users/... 等は宛先を特定できない
    if not any(p in owner or p in repo for p in PLACEHOLDERS):
        dest = _name_pair(owner, repo)
        return [(dest,)] if dest else None
    parts = ambient.parts(env)
    if parts is None:
        return None
    if not any(parts):
        # 今のリポジトリが分からない: gh の置き換えの前の字のまま照らす(* の一覧なら通る)
        return [(f"{owner}/{repo}",)] if (owner, repo) == PLACEHOLDERS else None
    filled = [ambient.filled(part, owner, repo) for part in parts]
    return None if any(p is None for p in filled) else filled


def _name_pair(owner, repo):
    ok = NAME_RE.fullmatch(owner) and (repo == "*" or NAME_RE.fullmatch(repo))
    return f"{owner}/{repo}" if ok else None


def _first_time(part, kept, checked):
    """部品を照らすか。コマンドにつき 1 つの部品(kept)は 2 度目から飛ばす。その場で作った部品は毎回照らす。"""
    if id(part) not in kept:
        return True
    if id(part) in checked:
        return False
    checked.add(id(part))
    return True


def main():
    allow_patterns = patterns()
    raw = json.load(sys.stdin)
    if raw.get("tool_name") != "Bash":
        return
    command = raw.get("tool_input", {}).get("command", "")
    if not allow_patterns or not cr.GH_WORD_RE.search(command):
        return
    # 解析の入口は coldread と同じ cr.analyze・cr.gh_calls。ここで独自に組むと、片方だけ
    # 別の読みになって宛先検査が黙って外れる(行継続の穴のとき現にそうなっていた)。
    # ファイルは開かない(read_files を渡さない)——投稿かどうかは開かなくても決まる
    analysis = cr.analyze(command)
    if analysis is None:
        # 解析できない形には bash が走らせる形も在る(置換の中の括弧で囲まない case の枝・深い入れ子)。coldread は
        # 短いコマンドと COLDREAD_SKIP=1 では通すので、ここで通すと許可一覧の外へ無検査で出る
        cr.log_line(DENY_LOG, "deny 解析不能: " + command[:150].replace("\n", " "))
        cr.deny(
            "外部投稿ゲート(destgate): 宛先の許可制が有効だが、このコマンドは解析できないので投稿の宛先を確かめられない"
            "(COLDREAD_SKIP=1 ではこの門番は外れない)。引用を閉じる・置換の中の case の枝の型を (型) と括る等で"
            "書き直して再実行すること。"
        )
    calls = cr.gh_calls(command, analysis=analysis)
    ambient = Ambient(raw.get("cwd") or "", written_gh_repo(analysis), moves(analysis))
    checked = set()   # 照らし終えた、コマンドにつき 1 つの部品(Ambient.kept)
    for call in calls:
        if not call.candidates and not call.blocked:
            continue  # 投稿の形をしていない
        parts = dest_parts(call.args, call_env(call.prefix), ambient)
        if parts is None or not any(parts):
            cr.log_line(DENY_LOG, "deny 宛先不明: " + command[:150].replace("\n", " "))
            cr.deny(
                "外部投稿ゲート(destgate): 宛先の許可制が有効だが、この投稿の宛先をコマンドから特定できない"
                "(展開や名前に入らない字を含む宛先・字のまま書いていない値の GH_REPO・行き先が字のまま決まらない cd や "
                "env -C・env -S の前置・サブコマンドより前の知らない旗)。-R owner/repo で宛先を字のまま明示して"
                "再実行すること。"
            )
        for dest in (d for part in parts if _first_time(part, ambient.kept, checked) for d in part):
            if not any(fnmatch.fnmatchcase(dest.lower(), pat.lower()) for pat in allow_patterns):
                cr.log_line(DENY_LOG, f"deny {dest}: " + command[:150].replace("\n", " "))
                cr.deny(
                    f"外部投稿ゲート(destgate): この投稿の宛先 {dest} は許可一覧に無い。\n"
                    f"許可一覧は {ALLOWLIST}(owner/repo か owner/* を 1 行ずつ)。\n"
                    "一覧の管理は人の仕事——この deny を受けたモデルは一覧を自分で編集せず、"
                    "宛先を許してよいか人に確認すること。"
                )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 検査できないものを黙って通さない(coldread と同じ倒し方)
        cr.deny("外部投稿ゲート(destgate): 検査自体に失敗した(%s)。" % str(exc)[:150])
