"""use.sh start が test_cmd を Archon に渡す前に、run の worktree と単位の worktree で効かない形を分けて知らせる。

python3 -I works/dev/testcmd_check.py [--allow-checkout] <対象の根> <test_cmd>

run の worktree（Archon が --from の commit から切る）と単位の worktree（修正の段が run の worktree の今の姿の commit から切る）には、
対象の git が無視する物（.venv・node_modules・ビルドの出力・.env など）が無い。形は 2 つに分け、1 行ずつ標準出力へ出す:
- 止める形（行の頭「止める（test_cmd）」。--allow-checkout なら「注意（test_cmd）」）: run の試験が worktree の直しでなく対象の手元
  （元の clone）を走らせ、直しの正誤に関わらず緑になり得る（黙った偽の緑）。
  - 手元を絶対パスで指す語: どの段でも（手元の絶対パスは前の段が worktree の中に作ることが無い。殻の -c の中の段も）、見る語（下）の
    うち絶対パスで、対象の根そのものか根の中の今在る物を指す物（git が無視するかを問わない。cd /手元 && uv run pytest・
    uv sync && /手元/.venv/bin/pytest・pytest /手元/tests・PYTHONPATH=/手元/src）と、最初の段の前の絶対パスの cd の後の相対の
    語のうち git が無視する物
  - 対象の外の環境を絶対パスで指す語: どの段でも、見る語（下）のうち絶対パスで対象の外の物から上へ辿った仮想環境の根（印
    VENV_MARKERS: pyvenv.cfg か conda-meta）に対象が editable で入っている（下の立てた環境と同じ印）（/venvs/proj/bin/pytest・
    PATH=/venvs/proj/bin:$PATH pytest。virtualenvwrapper・poetry・conda の環境を VIRTUAL_ENV なしで指す形）
  - 立てた仮想環境: VIRTUAL_ENV が在りその bin が PATH に在るか、起こした殻の PATH の段から上へ辿った仮想環境の根が在り（conda
    activate は VIRTUAL_ENV を立てない）、その環境に対象が editable で入っていて（site-packages の
    *.dist-info/direct_url.json の editable の url か、*.pth の絶対パスの行が対象の根の中を指す）、test_cmd の段（殻の -c の中も。
    前の NAME=値 と env を除く）のどれかが、組み込み（BUILTINS: cd・echo・export など）でも、頭が uv でサブコマンドが pip でなく
    --active も --no-project も無い段（uv run・uv sync など）でもない。run の中の python・pytest は PATH のその環境を掴む（uv run・
    uv sync は project の .venv を使い VIRTUAL_ENV を見ない。uv run --active・uv run --no-project・uv pip は立てた環境を使う）。対象の入っていない環境（依存だけの
    環境・uv run の使い捨ての環境）は知らせない
- 注意の形（行の頭「注意（test_cmd）」）: 相対の語が、対象に今在り git が無視する物（git check-ignore。パスか、その上のどれかの段が
  無視されていれば無視）を指す。worktree に無いので走らない（落ちて分かる）
見る語: 段（&&・||・;・|・& と改行で割る。改行は ; と同じ。&& などの後ろの改行と \\ と改行は続き。# の注は行の終わりまで）の語（shlex で割る。割れなければ空白で割る）のうち、`/` を含み - で始まらない物と、= を含む語
（NAME=値・--旗=値）の値を : で割った絶対パス。注意の形（相対の語）は最初の段だけを見る（後ろの段は前の段が worktree の中で作った
物を使える）。
所を変える形は辿る:
- 前の段が `cd <先>`・`pushd <先>`（旗 -P・-L などは除く。後ろが && か ;）だけなら、所を変えるだけの段で、その次の段を最初の段とし、
  相対の語を cd の先から読む（cd sub && .venv/bin/pytest は sub/.venv/bin/pytest）。cd の先もパスとして見る（/ が無くても）。
  サブシェルの括弧の中の cd は、括弧を閉じたら戻す
- 最初の段が殻の -c（sh -c '…'・bash -lc "…"。前の NAME=値 と env は許す。旗の終わり --・値を取る -o/+o/-O/+O と
  --rcfile・--init-file の値・ほかの長い旗は飛ばす）なら、その中のコマンドを同じ決まりで読む
- 所を変える旗（CHDIR_FLAGS: make -C・--directory、env -C・--chdir、git・ninja・go の -C、pnpm -C・--dir、npm --prefix、
  yarn --cwd、uv --directory。同じ段にその道具の語が在る時だけ。値は空白で分けても = か -C に繋いでもよい）の値を cd の先と同じに
  パスとして見て、同じ段の後ろの語をそこから読む
書き先（リダイレクト >・>>・>|・&>・&>>・>&・<> の後ろの語と、OUTPUT_FLAGS の旗の後ろの語・= の値）はコマンドが作るので、
手元に前の出力が在っても見ない。
終了コード: 止める形が在れば 3（--allow-checkout でも 3。行の頭だけが替わる）、無ければ 0、引数の誤りは 2。git が効かなければ
git が無視するかは見ない（止める形の手元を絶対パスで指す語は見る）。標準ライブラリだけ・Python 3.9 の構文。

漏れ（知っていて塞がない物。止める形の漏れは run を止めずに偽の緑を通し、注意の形の漏れは知らせが多すぎるか少なすぎる）:
- 書き先を空白で分けた値に取る旗のうち OUTPUT_FLAGS に無い物（-o build/x・道具ごとの旗）は、その値が手元に前の出力として在り
  git が無視すれば名指す（旗が値を取るかは道具ごとに違い、一般には決まらない）。値が手元を指す絶対パスなら止める
- 変数・~・$(…)・` は展開しない（cd の先がこれらなら後ろの相対の語は見ない）。run の中では HOME が利用の家へ隔離されるので、
  ~・$HOME で手元を指す形は run の中で別の所を指して落ちる（偽の緑にはならない）
- 中のコマンドを隠す形は読まない: make（-C の無い）・npm test・tox・nox・just などの台本・試験の殻のファイルの中身・
  sh <ファイル>・eval・xargs・find -exec。その中で手元を絶対パスで指しても見えない
- 所を変える形のうち CHDIR_FLAGS の外の旗（uv run --project・cargo --manifest-path など）は、値が絶対パスで手元を指す時だけ
  見る（相対の値は / が無ければ見ず、後ろの語も根から読む）。相対の語は最初の段より後ろの段では見ない（前の段が作った物か読めない）
- 根の外への絶対パスの cd の後の相対の語（cd /手元の親 && 手元/.venv/bin/pytest）は読めない所として見ない。docker run -v /手元:/w
  のように = でなく : で繋いだ値の中の手元は、語が在るパスでないので見ない
- 立てた環境の判定で、uvx の段は uv の段として数えない（止める）。組み込みでない段は python を起こさなくても
  止める（npm ci && uv run pytest も立てた環境で editable なら止める。止めを外せば今どおり起こす）
- 対象が editable でなく普通に入った（写しを入れた）仮想環境は、絶対パスで指しても立てても editable の印が無いので、
  絶対パスの語としてだけ見る（立てた環境は知らせない）
- 根の印（pyvenv.cfg・conda-meta）の無い入れ先（pip install --target の所・利用者の site-packages（pip install --user -e）・
  素の python の site-packages）に editable で入れた対象は、PYTHONPATH= などで指しても、PATH から掴んでも見えない。対象の外の
  環境を相対のパス（../venvs/proj/bin/pytest）・~・変数で指す形も辿らない（相対の語は根の中だけを見る）
- 起こした殻の PATH の段から辿る環境は、PATH の前の段に同じ名のコマンドが在って run がそちらを掴む形でも止める（どのコマンドを
  掴むかは段ごとに決まらない）
"""
import glob
import io
import json
import os
import re
import shlex
import subprocess
import sys
from urllib.parse import unquote, urlparse

USAGE = "usage: testcmd_check.py [--allow-checkout] <対象の根> <test_cmd>"
STOP_EXIT = 3   # 止める形が在る時の終了コード（--allow-checkout でも同じ。行の頭だけが「注意」になる）
HOW = "worktree の中で環境を作るコマンド（例 uv run pytest -q）にする（works/README.md の「test_cmd と worktree」）"
SEPARATORS = ("&&", "||", ";", "|", "&")
REDIRECTS = (">", ">>", ">|", "&>", "&>>", ">&", "<>")   # 後ろの語が書き先のリダイレクト（< の先は読むので見る）
# 書き先を値に取る旗（よく使う物だけ。空白で分けた値も = で繋いだ値も見ない。ほかの旗の = の値は絶対パスだけ見る）
OUTPUT_FLAGS = frozenset(("--junitxml", "--junit-xml", "--basetemp", "--html", "--report-log", "--result-log", "--alluredir",
                          "--cov-report", "--outputFile", "--coverageDirectory", "--output", "--output-file", "--outdir"))
# 所を変える旗（値が所のフォルダで、同じ段の後ろの語をそこから読む）。道具の名（語の basename）ごと。同じ段に道具の語が在れば効く
CHDIR_FLAGS = {"make": ("-C", "--directory"), "gmake": ("-C", "--directory"), "env": ("-C", "--chdir"), "git": ("-C",),
               "ninja": ("-C",), "go": ("-C",), "pnpm": ("-C", "--dir"), "npm": ("--prefix",), "yarn": ("--cwd",),
               "uv": ("--directory",)}
CD_WORDS = ("cd", "pushd")
CD_OPTS = ("-P", "-L", "-e", "-@", "-n")   # cd・pushd の旗（値を取らない）
SHELLS = ("sh", "bash", "zsh", "dash", "ksh")   # -c '<コマンド>' の中を同じ決まりで読む殻
# 立てた環境の判定で見ない段の頭（所を変える・出すだけで python を起こさない殻の組み込み）
BUILTINS = frozenset(("cd", "pushd", "popd", "echo", "printf", "true", "false", ":", "set", "export", "unset"))
UV_COMMANDS = frozenset(("run", "sync", "pip", "lock", "add", "remove", "venv", "tool", "python", "build", "export", "tree",
                         "init", "version", "cache", "self", "publish", "format"))
_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
PUNCT = "();<>|&\n"   # shlex の句読（改行も。改行は ; と同じ段の区切り）
SHELL_VALUE_OPTS = frozenset(("--rcfile", "--init-file"))   # 殻の長い旗のうち値を取る物
VENV_MARKERS = ("pyvenv.cfg", "conda-meta")   # 仮想環境の根の印（venv・virtualenv・poetry・uv は pyvenv.cfg、conda は conda-meta）


class _KeepNewline(io.StringIO):
    """shlex の注（# の後）が行の終わりの改行まで食べないようにする流れ（改行は段の区切りなので残す）"""

    def readline(self, size=-1):
        rest = self.getvalue()[self.tell():]
        end = rest.find("\n")
        return self.read(len(rest) if end < 0 else end)


def _join_lines(cmd):
    """\\ と改行（行の続き）を殻と同じに消す（一重引用符の中は字のまま。二重引用符の中と外は消す）"""
    out, i, quote = [], 0, None
    while i < len(cmd):
        c = cmd[i]
        if c == "\\" and quote != "'" and i + 1 < len(cmd):
            if cmd[i + 1] != "\n":
                out.append(cmd[i:i + 2])
            i += 2
            continue
        if c in "'\"":
            quote = c if quote is None else None if quote == c else quote
        out.append(c)
        i += 1
    return "".join(out)


def _words(cmd):
    """shlex の語の並び（行の続き \\ と改行は先に消す。改行は 1 語 "\n"。句読の連なりに挟まった改行も分ける）。割れなければ
    ValueError"""
    lex = shlex.shlex(_KeepNewline(_join_lines(cmd)), posix=True, punctuation_chars=PUNCT)
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    out = []
    for w in lex:
        if "\n" in w and set(w) <= set(PUNCT):
            for k, part in enumerate(w.split("\n")):
                if k:
                    out.append("\n")
                if part:
                    out.append(part)
        else:
            out.append(w)
    return out


def _segments(cmd):
    """段の並び（&&・||・;・|・& と改行で割る。改行は ; と数え、&& などの後ろ・空の行の改行は続きとして飛ばす）と、段の間の
    区切りの並び。段は (語の並び, 前で開くサブシェルの数, 後ろで閉じる数)。shlex で割れなければ空白で割った全部を 1 段にする"""
    try:
        words = _words(cmd)
    except ValueError:
        return [(cmd.split(), 0, 0)], []
    segs, seps = [[[], 0, 0]], []
    for w in words:
        if w == "\n":
            if segs[-1][0] or segs[-1][2]:
                segs.append([[], 0, 0])
                seps.append(";")
        elif w == "(":
            segs[-1][1] += 1
        elif w == ")":
            segs[-1][2] += 1
        elif w in SEPARATORS:
            segs.append([[], 0, 0])
            seps.append(w)
        else:
            segs[-1][0].append(w)
    return [tuple(x) for x in segs], seps


def _cd(root, cwd, target):
    """cd の先の、根からの相対（"" は根）。読めない先（$・~・` を含む・- か + で始まる旗か cd -・前の所が読めない相対）と根の外は
    None"""
    if target.startswith(("-", "+", "~")) or "$" in target or "`" in target:
        return None
    if os.path.isabs(target):
        return "" if os.path.realpath(target) == root else _inside(root, target)
    if cwd is None:
        return None
    new = os.path.normpath(os.path.join(cwd or ".", target))
    if new == ".":
        return ""
    return None if new == ".." or new.startswith(".." + os.sep) else new


def _move(root, at, target):
    """読む所 at（根からの相対, 絶対パスの cd を通った時の絶対パス）から target へ所を変えた後の読む所"""
    rel = _cd(root, at[0], target)
    base = os.path.normpath(target) if os.path.isabs(target) else \
        os.path.normpath(os.path.join(at[1], target)) if at[1] else None
    return rel, base if rel is not None else None


def _cd_target(words):
    """cd・pushd だけの段（旗 -P などを除いて先が 1 語）なら先の語、そうでなければ None"""
    if not words or words[0] not in CD_WORDS:
        return None
    rest = words[1:]
    while rest and rest[0] in CD_OPTS:
        rest = rest[1:]
    return rest[0] if len(rest) == 1 else None


def _strip_env(words):
    """前の NAME=値 と、旗の無い env を除いた語の並び"""
    while words and (_ASSIGN.match(words[0]) or words[0] == "env"):
        words = words[1:]
    return words


def _shell_c(words):
    """殻の -c の段（sh -c '<コマンド>'・bash -lc …。前の NAME=値 と env は許す）なら (殻の前の語, <コマンド>)、そうでなければ
    None"""
    rest = _strip_env(words)
    if not rest or os.path.basename(rest[0]) not in SHELLS:
        return None
    i, found = 1, False
    while i < len(rest):
        w = rest[i]
        i += 1
        if w == "--":   # 旗の終わり（bash -c -- '…'）
            break
        if w.startswith("--"):   # 長い旗（--norc・--login など。--rcfile <ファイル> は値も飛ばす）
            i += w in SHELL_VALUE_OPTS
            continue
        if len(w) < 2 or w[0] not in "-+":
            i -= 1
            break
        found = found or "c" in w[1:]
        i += sum(ch in "oO" for ch in w[1:])   # -o pipefail・+o posix・-O extglob・-eo pipefail は値を取る
    if not found or i >= len(rest):
        return None
    return words[:len(words) - len(rest)], rest[i]


def _lead(root, cmd, at=("", None), depth=0):
    """前の段の cd を辿った最初の段 ——（cd の先の語と、それを読む所の並び, 最初の段の語, 最初の段を読む所）。読む所は
    (根からの相対（"" は根・None は読めない）, 絶対パスの cd を通った時のその所の絶対パス（通らなければ None）)。cd・pushd だけの段
    （後ろが && か ;）は所を変えるだけで、次の段を最初の段とする（サブシェルの括弧の中の cd は、括弧を閉じたら戻す）。最初の段が
    殻の -c なら、その中のコマンドを同じ決まりで読む（殻の前の NAME=値 は最初の段の語に残す）"""
    segs, seps = _segments(cmd)
    cds, stack = [], []
    for i, (words, opens, closes) in enumerate(segs):
        stack.extend([at] * opens)
        target = _cd_target(words)
        if target is not None and i < len(seps) and seps[i] in ("&&", ";"):
            cds.append((target, at))
            at = _move(root, at, target)
            for _ in range(min(closes, len(stack))):
                at = stack.pop()
            continue
        inner = _shell_c(words) if depth < 4 else None
        if inner is not None:
            c2, w2, at2 = _lead(root, inner[1], at, depth + 1)
            return cds + c2, inner[0] + w2, at2
        return cds, words, at
    return cds, [], at


def _chdir_flag(word, tools):
    """所を変える旗なら (旗, = か -C に繋いだ値か None)。同じ段に出た道具の語（tools）の旗だけ"""
    flags = {f for t in tools for f in CHDIR_FLAGS[t]}
    if word in flags:
        return word, None
    name, eq, val = word.partition("=")
    if eq and name in flags and name.startswith("--"):
        return name, val
    if word.startswith("-C") and len(word) > 2 and "-C" in flags:
        return "-C", word[2:]
    return None


def _path_words(root, cmd):
    """見る語と、それを読む所の並び: cd・所を変える旗の先（/ が無くてもパス）と、最初の段の
    語のうち / を含み、- で始まらず = を含まない物。= を含む語（NAME=値・--旗=値）は値を : で割った絶対パスだけを見る。
    書き先（リダイレクト > など の先・OUTPUT_FLAGS の旗の後ろの語と = の値）はコマンドが作るので見ない。所を変える旗
    （make -C など）の後ろの語は、その先から読む"""
    cds, words, at = _lead(root, cmd)
    out = list(cds) + _scan(words, at, root)
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _scan(words, at, root):
    """1 つの段の語のうち見る物と、それを読む所の並び（_path_words の決まり。所を変える旗の後ろは読む所を移す）"""
    out = []
    skip, chdir, tools = False, False, set()
    for w in words:
        if skip:
            skip = False
            continue
        if chdir:
            chdir = False
            out.append((w, at))
            at = _move(root, at, w)
            continue
        if w in REDIRECTS or w in OUTPUT_FLAGS:
            skip = True
            continue
        if os.path.basename(w) in CHDIR_FLAGS and "=" not in w:
            tools.add(os.path.basename(w))
        flag = _chdir_flag(w, tools)
        if flag is not None:
            if flag[1] is None:
                chdir = True
            else:
                out.append((flag[1], at))
                at = _move(root, at, flag[1])
            continue
        if "=" in w:
            name, _, val = w.partition("=")
            if name not in OUTPUT_FLAGS:
                out.extend((v, at) for v in val.split(os.pathsep) if os.path.isabs(v))
            continue
        if "/" in w and not w.startswith("-"):
            out.append((w, at))
    return out


def _all_segments(cmd, depth=0):
    """全部の段の語の並び。殻の -c の段は中のコマンドの段に開く（殻の前の NAME=値・env は別の段にする）"""
    out = []
    for words, _, _ in _segments(cmd)[0]:
        inner = _shell_c(words) if depth < 4 else None
        if inner is None:
            out.append(words)
            continue
        if inner[0]:
            out.append(inner[0])
        out.extend(_all_segments(inner[1], depth + 1))
    return out


def _absolute_words(root, cmd):
    """全部の段の、見る語のうち絶対パスの物（手元の絶対パスは前の段が worktree の中に作ることが無いので、段を問わない）"""
    out = []
    for words in _all_segments(cmd):
        for w, _ in _scan(words, ("", None), root):
            if os.path.isabs(w) and w not in out:
                out.append(w)
    return out


def _under(root, path):
    """path（正規化した絶対パス）が根の中なら根からの相対（根そのもの・外は None）"""
    rel = os.path.relpath(path, root)
    if rel in (".", "..") or rel.startswith(".." + os.sep):
        return None
    return rel


def _within(root, path):
    """path（実パス）が根そのものか根の中か"""
    return path == root or _under(root, path) is not None


def _inside(root, word):
    """word が対象の根の中を指すなら根からの相対、外なら None。相対の語は根から読む。絶対の語は上の段を順に実パスに直し、
    根と同じ実パスの段が在ればその下を相対にする（/tmp・/var のようなリンクを通った綴りでも拾う。語そのものは解かない:
    .venv/bin/python はリンクで、解くと外の python を指す）"""
    if not os.path.isabs(word):
        return _under(root, os.path.normpath(os.path.join(root, word)))
    head = os.path.normpath(word)
    tail = []
    while True:
        head, name = os.path.split(head)
        if not name:
            return None
        tail.insert(0, name)
        if os.path.realpath(head) == root:
            return os.path.join(*tail)


def _prefixes(root, rel):
    """rel の上の段から rel まで（リンクの段で止める。git check-ignore はリンクの先のパスを渡すと 128 で全部を落とす）"""
    parts = rel.split(os.sep)
    out = []
    for i in range(1, len(parts) + 1):
        p = os.sep.join(parts[:i])
        out.append(p)
        if os.path.islink(os.path.join(root, p)):
            break
    return out


def _ignored(root, paths):
    """paths のうち git が無視する物。まとめて問い、git が落ちたら（サブモジュールの中のパスなど。1 本が全部を落とす）
    1 本ずつ問い直す（落ちたパスは無視でないと数える）"""
    if not paths:
        return set()
    try:
        r = subprocess.run(["git", "-C", root, "check-ignore", "-z", "--stdin"], input="\0".join(paths) + "\0",
                           capture_output=True, text=True, encoding="utf-8", errors="surrogateescape")
    except OSError:
        return set()
    if r.returncode in (0, 1):
        return set(filter(None, r.stdout.split("\0")))
    if len(paths) == 1:
        return set()
    return set().union(*(_ignored(root, [p]) for p in paths))


def _inside_or_root(root, word):
    """絶対パスの word が根そのものなら ""、根の中なら根からの相対、外なら None"""
    return "" if os.path.realpath(word) == root else _inside(root, word)


def path_notes(root, cmd):
    """パスの知らせ (止める形か, 文) の並び。対象の手元を絶対パスで指す語（根そのもの・追跡する物も。絶対パスの cd の後で git が
    無視する相対の語も）は止める形、git が無視するパスを相対で指す語は注意の形"""
    found = []
    for w in _absolute_words(root, cmd):   # どの段でも、対象の手元の在る物を指す（無視するかを問わない）
        rel = _inside_or_root(root, w)
        if rel is not None and os.path.lexists(os.path.join(root, rel)):
            found.append((w, True, None))
    for w, (at, base) in _path_words(root, cmd):
        if os.path.isabs(w):   # 上で見た
            continue
        if at is None:   # 読めない cd の後の相対は見ない
            continue
        if base:   # 絶対パスの cd の後の相対は、対象の手元を絶対パスで指す
            rel, absolute = _inside(root, os.path.join(at, w)), True
            shown = f"{w}（cd の後の {os.path.normpath(os.path.join(base, w))}）"
        elif at == "":
            rel, shown, absolute = _inside(root, w), w, False
        else:
            rel, absolute = _inside(root, os.path.join(at, w)), False
            shown = f"{w}（cd の後の {os.path.normpath(os.path.join(at, w))}）"
        if rel is not None and os.path.lexists(os.path.join(root, rel)):
            found.append((shown, absolute, _prefixes(root, rel)))
    hit = _ignored(root, sorted({p for _, _, ps in found if ps for p in ps}))
    notes = []
    for w, absolute, ps in found:
        if ps is not None and not hit.intersection(ps):
            continue
        if absolute:
            notes.append((True, f"test_cmd の {w} は対象の手元（{root}）を絶対パスで指す: run・単位の worktree からも手元の物を"
                                f"使い、worktree の直しでなく対象の手元のコードを試し得る（直しの正誤に関わらず緑になる）。{HOW}"))
        else:
            notes.append((False, f"test_cmd の {w} は対象の git が無視するパスで、run・単位の worktree に無い（commit から切るので"
                                 f"写らない。前の段で作らない限り走らない）。{HOW}"))
    return notes


def _editable_target(venv, root):
    """venv に対象が editable で入っているか（PEP 610 の direct_url.json の editable の url か、.pth の絶対パスの行が根の中）"""
    sites = glob.glob(os.path.join(venv, "lib", "python*", "site-packages")) + [os.path.join(venv, "Lib", "site-packages")]
    for site in sites:
        for f in glob.glob(os.path.join(site, "*.dist-info", "direct_url.json")):
            try:
                with open(f, encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            info = d.get("dir_info") if isinstance(d, dict) else None
            if not (isinstance(info, dict) and info.get("editable") is True):
                continue
            u = urlparse(str(d.get("url", "")))
            if u.scheme == "file" and _within(root, os.path.realpath(unquote(u.path))):
                return True
        for f in glob.glob(os.path.join(site, "*.pth")):
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    lines = [ln.strip() for ln in fh]
            except OSError:
                continue
            if any(os.path.isabs(ln) and _within(root, os.path.realpath(ln)) for ln in lines):
                return True
    return False


def _venv_free(words):
    """段が立てた環境を使わないか: 空・組み込み（BUILTINS）の段と、頭が uv で、サブコマンドが pip でなく --active も無い段
    （uv run・uv sync は project の .venv を使い VIRTUAL_ENV を見ない）"""
    if not words or words[0] in BUILTINS:
        return True
    if os.path.basename(words[0]) != "uv" or "--active" in words or "--no-project" in words:
        return False
    sub = next((w for w in words[1:] if w in UV_COMMANDS), None)
    return sub is not None and sub != "pip"


def _venv_root(path):
    """path そのものか、その上の段のうち仮想環境の根（VENV_MARKERS の印の在る所）。無ければ None（語そのものは解かない:
    .venv/bin/python はリンクで、解くと外の python を指す）"""
    p = os.path.normpath(path)
    while True:
        if any(os.path.lexists(os.path.join(p, m)) for m in VENV_MARKERS):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def venv_notes(root, cmd, environ):
    """立てた・指した環境の知らせ。対象の外の環境（対象の中の物は path_notes が手元を指す語として見る）のうち対象が editable で
    入った物: (1) test_cmd の絶対パスの語（NAME=値・--旗=値 の値も。PATH= の段も）から上へ辿った環境の根は段を問わず止める
    (2) 起こした殻の VIRTUAL_ENV（その bin が PATH に在る時）と、PATH の段から上へ辿った環境の根（conda activate のように
    VIRTUAL_ENV を立てない形）は、test_cmd に立てた環境を使わない段（_venv_free）だけなら止めない"""
    notes, seen = [], set()
    for w in _absolute_words(root, cmd):
        if _inside_or_root(root, w) is not None:   # 対象の中は path_notes が見る
            continue
        venv = _venv_root(w)
        if venv is None or venv in seen or _within(root, os.path.realpath(venv)):
            continue
        seen.add(venv)
        if _editable_target(venv, root):
            notes.append((True, f"test_cmd の {w} は対象の外の仮想環境（{venv}）を指し、対象がそこへ editable で入っている: run の中の"
                                f" test_cmd はその環境の python・pytest で、worktree の直しでなく対象の手元のコードを試す（直しの正誤に"
                                f"関わらず緑になる）。{HOW}"))
    if all(_venv_free(_strip_env(words)) for words in _all_segments(cmd)):
        return notes
    entries = [os.path.normpath(p) for p in environ.get("PATH", "").split(os.pathsep) if os.path.isabs(p)]
    venv = environ.get("VIRTUAL_ENV", "")
    if venv and os.path.normpath(os.path.join(venv, "bin")) in entries:
        venv = os.path.normpath(venv)
        seen.add(venv)
        if _editable_target(venv, root):
            notes.append((True, f"VIRTUAL_ENV（{venv}）を立てたまま起こし、対象がそこへ editable で入っている: run の中の test_cmd の"
                                f" python・pytest はその環境を PATH から掴み、worktree の直しでなく対象の手元のコードを試す（直しの正誤に"
                                f"関わらず緑になる）。{HOW}"))
    for entry in entries:
        venv = _venv_root(entry)
        if venv is None or venv in seen:
            continue
        seen.add(venv)
        if _editable_target(venv, root):
            notes.append((True, f"起こした殻の PATH の {entry} は仮想環境（{venv}）の中で、対象がそこへ editable で入っている: run の中の"
                                f" test_cmd の python・pytest はその環境を PATH から掴み、worktree の直しでなく対象の手元のコードを試す"
                                f"（直しの正誤に関わらず緑になる）。{HOW}"))
    return notes


def main(argv):
    allow = bool(argv) and argv[0] == "--allow-checkout"
    if allow:
        argv = argv[1:]
    if len(argv) != 2:
        print(USAGE, file=sys.stderr)
        return 2
    root, cmd = os.path.realpath(argv[0]), argv[1].strip()
    if not cmd:
        return 0
    notes = path_notes(root, cmd) + venv_notes(root, cmd, os.environ)
    for stop, line in notes:
        print(f"{'止める' if stop and not allow else '注意'}（test_cmd）: {line}")
    return STOP_EXIT if any(stop for stop, _ in notes) else 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
