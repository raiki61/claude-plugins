#!/usr/bin/env python3
"""searchgate — / やホームの全体から探すのを、走る前に止めるゲート(PreToolUse: Bash・Glob・Grep)。

coldread・destgate が外に出る物を守るのに対し、これは手元のマシンの資源を守る。2026-10-24 に、部署の会話が打った
`find / -name …` 2 本(Claude Code は find を bfs に置き換えて走らせる)が 1 時間で計 860% の CPU を使い、負荷が
24 コアで 55〜70 になった。Bash の時間切れの後も親を失って残り、`pkill -f "find / …"` では名が合わず消えなかった。
会社ごとの文書に「探すな」と書いても、ほかの会社・ほかの探し物で同じことが起きるので、全部の会話に 1 つの決まりを当てる。

決まりは 1 つ: 探す起点が WIDE のどれか(/ と、その直下の大きいフォルダ〔macOS の /Users・/System・/Volumes・/private・/opt、
Linux の /home・/usr・/var・/mnt・/media・/root・/srv〕・Windows のドライブのルートとその直下の大きいフォルダ・ホームそのもの)なら止める。
それより下(~/.cache/works-factory など)と作業場の中は通す。深さや時間の上限では縛らない。Windows のドライブは C:/…・C:\…・
Git Bash の /c/…・Cygwin の /cygdrive/c/…・WSL の /mnt/c/… のどれで書いても同じ所と読み、大文字と小文字は区別しない
(macOS と Windows の既定のファイルシステムは区別しないので、/users も /Users と同じ所を探す)。

見るツール: Bash の find・bfs・gfind・fd・rg・grep -r(前置の nice・sudo・xargs・timeout なども越えて読む)と、
Claude Code の Glob・Grep のツール。`bash -c "…"`・`eval`・`$( … )`・`` ` … ` `` の中も読む。起点の変数は、同じコマンドの中の
代入(`D=/; find $D`)と $HOME・~ まで解き、相対の起点は前の `cd <絶対パス> &&` かフックの cwd で解く。
解けない起点(読めない変数・条件の中の代入)は止めない——止める理由が字面に無いので。

止めるのは決定的(LLM なし)で、逃げ道は無い。検査そのものが落ちたら止める(coldread・destgate と同じ倒し方)。
解析部(トークン化・単純コマンド分割・変数と cd の追い方)は coldread-gate.py から読み込んで共有する。
"""
import copy
import json
import os
import posixpath
import re
import shlex
import sys

# `sys.path[0]` に頼らない(coldread-gate.py が claude_auth を読むのと同じ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_shell  # noqa: E402

FIND = {"find", "bfs", "gfind"}
GREP = {"grep", "egrep", "fgrep", "ggrep", "rgrep"}
FD = {"fd", "fdfind"}
RG = {"rg"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
# 後ろに走らせるコマンドを取る前置。coldread の command_start が飛ばす物(env・timeout など)のほかに、ここで越える
# 前置の旗のうち値を取る物(値ごと飛ばす)。旗と数(chrt の優先度・nice -19)を飛ばした次の語を、走るコマンドと見る
HOPS = {"nice": {"-n"}, "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"}, "doas": {"-u", "-C"},
        "xargs": {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "-J", "-R", "-S"}, "caffeinate": {"-t", "-w"},
        "stdbuf": {"-i", "-o", "-e"}, "ionice": {"-c", "-n", "-p"}, "taskpolicy": {"-c", "-t", "-l", "-p"},
        "arch": set(), "chrt": set(), "builtin": set()}
# 前段の粗選別: 探すツールの語もシェルの入れ子も無いコマンドは、解析部を読み込まずに通す(Bash のたびに走るので)
# grep は再帰の旗の在るときだけ読む(`| grep foo` のたびに解析部を読み込まない)。Claude Code の grep は ugrep で走り、
# -NUM(-5・-5r)と --depth も下をたどるので、数の旗も読む。旗を引用符で囲んでも('-r')シェルは同じに渡す
WORD_RE = re.compile(r"(?<![\w.-])(?:find|bfs|gfind|fd|fdfind|rg|rgrep)(?![\w.-])"
                     r"|(?<![\w.-])(?:e?grep|fgrep|ggrep)(?![\w.-]).*?(?:\s['\"]?-[A-Za-z0-9]*[rRd0-9]|--recursive"
                     r"|--dereference-recursive|--directories|--depth)", re.S)
# 入れ子は 8 段まで読む(`bash -c "bash -c '…'"` の深さ。それより深い物はそのまま通す)
MAX_DEPTH = 8


def home():
    """ホーム。Bash のシェルが ~ と $HOME で開く値(HOME)を先に、無ければ Python が引く値。"""
    return os.environ.get("HOME") or os.path.expanduser("~")


def norm(path):
    """起点を比べる形に直す: \\ を / に、.. を畳み、末尾の / を落とす(/ そのものは /)。"""
    p = path.replace("\\", "/")
    drive = re.match(r"([A-Za-z]:)(/.*)\Z", p)
    if drive:   # C:/… は C: の後ろだけを畳む(まとめて畳むと C: を 1 つのフォルダと読み、C:/Users/.. が . になる)
        rest = "/" + posixpath.normpath(drive.group(2)).lstrip("/")
        return drive.group(1) + ("" if rest == "/" else rest)
    p = posixpath.normpath(p) if p else p
    if p.startswith("//"):
        p = "/" + p.lstrip("/")   # normpath は先頭の // を残す(POSIX の決まり)。bfs は / と同じに読む
    return p


# ドライブの書き方(C:・C:/…・/c/…・/cygdrive/c/…・WSL の /mnt/c/…)。norm の後の形(\\ は / に、C:/ は C: に畳まれている)
DRIVE_RE = re.compile(r"(?:([A-Za-z]):|/(?:cygdrive/|mnt/)?([A-Za-z]))(/.*)?\Z")
# / の直下の大きいフォルダ(macOS・Linux)。/System/Volumes/Data は macOS で /Users などの実体が載る場所(firmlink)で、
# / の全体と同じ重さになる
ROOT_DIRS = ("/Users", "/System", "/System/Volumes/Data", "/Volumes", "/private", "/opt",
             "/home", "/usr", "/var", "/mnt", "/media", "/root", "/srv")
# ドライブのルートの直下の大きいフォルダ(Windows)
DRIVE_DIRS = ("/Users", "/Windows", "/Program Files", "/Program Files (x86)", "/ProgramData")


def key(path):
    """norm の後の形 → 比べる形: ドライブの書き方を /c/… に揃え、大文字と小文字を畳む。"""
    m = DRIVE_RE.match(path)
    if m:
        path = "/" + (m.group(1) or m.group(2)).lower() + (m.group(3) or "")
    return path.casefold()


def wide_set():
    h = norm(home())
    drives = ["/" + chr(c) for c in range(ord("a"), ord("z") + 1)]
    base = {"/", h, *ROOT_DIRS, *drives, *(d + sub for d in drives for sub in DRIVE_DIRS)}
    base |= {"/System/Volumes/Data" + p for p in (h, "/Users") if p.startswith("/")}
    return {key(p) for p in base}


WIDE = wide_set()
# 止めたときに見せる一覧(WIDE は比べる形なので、読める形を別に持つ)
WIDE_TEXT = "・".join(("/",) + ROOT_DIRS) + "・ドライブのルート(C:/・/c/ など)とその下の " + "・".join(
    d.lstrip("/") for d in DRIVE_DIRS) + "・ホームそのもの(%s)" % norm(home())


def is_abs(path):
    """/ で始まるか、ドライブで始まる(C:/…)。"""
    return path.startswith("/") or re.match(r"[A-Za-z]:(?:/|\Z)", path) is not None


def user_home(name):
    """~名前 のホーム(シェルと同じく利用者の台帳で引く)。引けなければ、名前がホームのフォルダの名前と同じときだけホーム。"""
    try:
        import pwd
        return pwd.getpwnam(name).pw_dir
    except (ImportError, KeyError):
        h = norm(home())
        return h if posixpath.basename(h) == name else None


def expand_home(value):
    """~・~/…・~名前・$HOME・${HOME} をホームに置き換える(Bash のシェルと同じ利用者・同じ HOME で起動されるので)。"""
    h = home().rstrip("/") or "/"
    if value == "~" or value.startswith("~/"):
        value = h + value[1:]
    else:
        m = re.match(r"~([A-Za-z0-9._][A-Za-z0-9._-]*)(?=/|\Z)", value)
        d = m and user_home(m.group(1))
        if d:
            value = (d.rstrip("/") or "/") + value[m.end():]
    return re.sub(r"\$(?:\{HOME\}|HOME(?![A-Za-z0-9_]))", lambda m: h, value)


def substitutions(text, bare=True, heredoc=False):
    """引用の単一の外にある $( … ) と ` … ` の中身。二重引用の中も読む(シェルが展開する)。bare が偽なら、引用の外の $( … ) は
    返さない(トークン化がその中を単純コマンドに割り、外のコマンドの cd と代入の中で見るので)。heredoc が真なら、text は
    区切りを引用しないヒアドキュメントの本文で、' と " は引用でなく字(シェルは本文の中のどこの $( … ) も走らせる)。"""
    out, i, quote, n = [], 0, None, len(text)
    while i < n:
        c = text[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == "\\":
            i += 1
        elif c == "'" and quote is None and not heredoc:
            quote = "'"
        elif c == '"' and not heredoc:
            quote = None if quote == '"' else '"'
        elif text.startswith("$(", i) and not text.startswith("$((", i):
            depth, j = 1, i + 2
            while j < n and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            if bare or quote == '"':
                out.append(text[i + 2:j - 1])
            i = j
            continue
        elif c == "`":
            j = text.find("`", i + 1)
            if j < 0:
                break
            out.append(text[i + 1:j])
            i = j
        i += 1
    return out


def scan(args, short_val, long_val):
    """旗と位置引数を分ける → (旗の (名前, 値) の列, 位置引数の列)。-abc の束ね・--x=v・-- の後を読む。"""
    opts, pos, i, rest = [], [], 0, False
    while i < len(args):
        a = args[i]
        if rest or a == "-" or not a.startswith("-"):
            pos.append(a)
        elif a == "--":
            rest = True
        elif a.startswith("--"):
            name, eq, val = a.partition("=")
            if not eq and name in long_val:
                i += 1
                val = args[i] if i < len(args) else ""
            opts.append((name, val))
        else:
            for j in range(1, len(a)):
                if a[j] in short_val:
                    val = a[j + 1:]
                    if not val:
                        i += 1
                        val = args[i] if i < len(args) else ""
                    opts.append(("-" + a[j], val))
                    break
                opts.append(("-" + a[j], ""))
        i += 1
    return opts, pos


# find の式のうち値を取る物(値は起点でない)。-newerXY は FIND_NEWER_RE で見る。-fprintf は値を 2 つ取る
FIND_VALUE = {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-lname", "-ilname", "-type", "-xtype",
              "-newer", "-anewer", "-cnewer", "-mnewer", "-Bnewer", "-maxdepth", "-mindepth", "-perm", "-size", "-user",
              "-group", "-uid", "-gid", "-regex", "-iregex", "-regextype", "-printf", "-fprint", "-fprint0", "-fls",
              "-samefile", "-inum", "-links", "-atime", "-ctime", "-mtime", "-Btime", "-amin", "-cmin", "-mmin", "-Bmin",
              "-used", "-context", "-files0-from", "-fstype", "-flags", "-xattrname", "-limit"}
FIND_NEWER_RE = re.compile(r"-newer[aBcmt][aBcmt]")
FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir"}


def find_starts(args):
    """find・bfs・gfind の起点。前の旗(-H -L -P -E -X -d -s -x -O3 -j8・値を取る -D -S・BSD の -f <起点>)の後、
    式(- か ( か ! で始まる語)の前までの語。起点が無ければ . (GNU と bfs の既定)。

    式の後ろの語も起点と読む: Claude Code は find を bfs で走らせ、bfs はどこに書いた起点もたどる(`find . -name x /`)。
    式の中では、値を取る旗の値(FIND_VALUE。`-path "/Users/me/*"` の型は起点でない)と、-exec などの後ろの ; か + までを飛ばす。"""
    starts, i = [], 0
    while i < len(args) and args[i].startswith("-") and args[i] != "-":
        a = args[i]
        if a == "--":   # 旗の終わり(BSD・GNU・bfs の find)。後ろは起点
            i += 1
            break
        if a in ("-D", "-S", "-f"):
            if a == "-f" and i + 1 < len(args):
                starts.append(args[i + 1])
            i += 2
        elif re.fullmatch(r"-[HLPEXdsx]+|-O\d*|-j\d+", a):
            i += 1
        else:
            break
    while i < len(args):
        a = args[i]
        if a in FIND_EXEC:
            i += 1
            while i < len(args) and args[i] not in (";", "+"):
                i += 1
        elif a in FIND_VALUE or FIND_NEWER_RE.fullmatch(a):
            i += 1
        elif a == "-fprintf":
            i += 2
        elif not a.startswith(("-", "(", "!", ")")) and a != ",":
            starts.append(a)
        i += 1
    return starts or ["."]


def find_execs(args):
    """find の -exec・-ok(cwd で走る)と -execdir・-okdir(見つけた物の所で走る)の後ろのコマンド → (語の列, 所で走るか) の列。"""
    out, i = [], 0
    while i < len(args):
        if args[i] in FIND_EXEC:
            j = i + 1
            while j < len(args) and args[j] not in (";", "+"):
                j += 1
            out.append((args[i + 1:j], args[i].endswith("dir")))
            i = j
        i += 1
    return out


FD_SHORT = set("etEdjSocxX")
FD_LONG = {"--extension", "--type", "--exclude", "--max-depth", "--min-depth", "--exact-depth", "--threads", "--size",
           "--owner", "--color", "--changed-within", "--changed-before", "--max-results", "--ignore-file",
           "--path-separator", "--batch-size", "--format", "--search-path", "--base-directory", "--exec", "--exec-batch"}
RG_SHORT = set("ABCefgtTmjMEdr")
RG_LONG = {"--after-context", "--before-context", "--context", "--regexp", "--file", "--glob", "--iglob", "--type",
           "--type-not", "--type-add", "--type-clear", "--max-count", "--threads", "--max-columns", "--encoding",
           "--max-depth", "--replace", "--sort", "--sortr", "--pre", "--pre-glob", "--context-separator",
           "--field-context-separator", "--field-match-separator", "--path-separator", "--max-filesize",
           "--dfa-size-limit", "--regex-size-limit", "--engine", "--colors", "--color", "--ignore-file",
           "--hyperlink-format", "--hostname-bin"}
GREP_SHORT = set("efmABCdD")
GREP_LONG = {"--regexp", "--file", "--max-count", "--after-context", "--before-context", "--context", "--directories",
             "--devices", "--include", "--exclude", "--exclude-dir", "--exclude-from", "--label", "--binary-files", "--depth"}


def starts_of(name, args, piped, xargs=False):
    """ツール name の引数 args から起点を返す。探さない形(grep の再帰でない・stdin を読む)なら []。

    piped は前がパイプのとき(rg は起点の無いとき stdin を読み、cwd を探さない。grep -r は前がパイプでも cwd を探す
    〔GNU grep の -r の説明と macOS の grep で確かめた〕)。xargs は xargs の後ろのとき(起点は標準入力から足されるので、
    起点の無い grep -r も cwd を探さない)。"""
    if "--help" in args or "--version" in args or (name in FD | RG and {"-h", "-V"} & set(args)):
        return []   # 使い方と版を出すだけ
    if name in FIND:
        return find_starts(args)
    if name in FD:
        for k, a in enumerate(args):
            if a in ("-x", "-X", "--exec", "--exec-batch") or a.startswith(("--exec=", "--exec-batch=")):
                args = args[:k + 1]   # 後ろは fd が走らせるコマンド
                break
        opts, pos = scan(args, FD_SHORT, FD_LONG)
        base = next((v for o, v in opts if o == "--base-directory"), None)
        paths = pos[1:] + [v for o, v in opts if o == "--search-path"]
        paths = paths or ["."]
        return [posixpath.join(base, p) for p in paths] if base else paths
    if name in RG:
        opts, pos = scan(args, RG_SHORT, RG_LONG)
        given = any(o in ("-e", "--regexp", "-f", "--file", "--files", "--type-list") for o, _ in opts)
        paths = pos if given else pos[1:]
        return paths or ([] if piped else ["."])
    if name in GREP:
        opts, pos = scan(args, GREP_SHORT, GREP_LONG)
        # Claude Code の grep は ugrep で走り、-NUM(-5・-5r・-i5)は下をたどる深さ、--depth も同じ。rgrep は grep -r
        recursive = name == "rgrep" or any(
            o in ("-r", "-R", "--recursive", "--dereference-recursive", "--depth") or re.fullmatch(r"-\d", o)
            for o, _ in opts) or any(o in ("-d", "--directories") and v == "recurse" for o, v in opts)
        if not recursive:
            return []
        given = any(o in ("-e", "--regexp", "-f", "--file") for o, _ in opts)
        paths = pos if given else pos[1:]
        return paths or ([] if xargs else ["."])
    return []


class Hit(Exception):
    """止める起点が見つかった(args[0] はツールの名前、args[1] は起点の正規の形)。"""


def resolve(value, cwd):
    """起点の語 → 比べる形の絶対パス。決まらなければ None(止めない)。"""
    if value is None:
        return None
    v = expand_home(value).replace("\\", "/")
    if "$" in v or "`" in v:
        return None
    if any(ch in v for ch in "*?["):
        # シェルが開く型(~/*・/Users/*)は、型を含む区切りの前のフォルダの中を全部探すのと同じ
        head = []
        for part in v.split("/"):
            if any(ch in part for ch in "*?["):
                break
            head.append(part)
        v = "/".join(head) or ("/" if v.startswith("/") else ".")
    if not is_abs(v):   # C:\x も C:/x と同じく絶対(cwd に繋がない)
        if not cwd:
            return None
        v = posixpath.join(cwd.replace("\\", "/"), v)
    return norm(v)


def check_path(tool, value, cwd):
    p = resolve(value, cwd)
    if p is not None and key(p) in WIDE:
        raise Hit(tool, p)


# ${名前} のうち、中に引用も置換も持たない物(without_quoted_bodies が読み飛ばせる形)
_PLAIN_BRACE_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_CASE_RE = re.compile(r"(?<![\w.-])(?:case|esac)(?![\w.-])")
_HERE_HEAD_RE = re.compile(r"<<(-)?[ \t]*")


def _closes_in(text, s, end, comments):
    """s の `$(` を、bash 3.2 のように括弧と引用符を数えて閉じる ) が、end より前に在るか。3.2 は置換の中のヒアドキュメントを
    知らずに数えるので、本文の中の ) で置換を閉じ、本文の後ろの字をコマンドとして走らせる(`x=$(cat <<'E'` の次の行の
    `a) echo RAN` は 3.2 で echo が走る)。comments が真なら、語の頭の # から行の終わりまでを数えない。"""
    depth, i = 1, s + 2
    while i < end:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                return False
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            while j < len(text) and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if comments and c == "#" and (i == 0 or text[i - 1] in " \t\n;&|("):
            nl = text.find("\n", i)
            i = len(text) if nl < 0 else nl
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if not depth:
                return True
        i += 1
    return False


def without_quoted_bodies(cr, command):
    """区切りを引用したヒアドキュメント(`<<'EOF'`・`<<"EOF"`・`<<\\EOF`・`<<E"OF"`)の本文を除いたコマンド。シェルはその本文を
    展開も実行もしないので、本文の中の字は探すツールの語でない。除く本文が無いか、読み切れない形(閉じない引用・バッククォート・
    `$((`・`$'`・中身の在る `${ }`・case・迷う #・終わりの行の無い本文・bash 3.2 が本文の中で置換を閉じる形)なら None。

    区切りを引用しない本文は除かない(シェルが中の `$( )` を走らせる)。開始行が \\ で次の行へつながるときは、つないだ行の後から
    本文を読む(bash と同じ。つないだ行はコマンドとして残る)。置換の中では、終わりの語に ) を続けた行(`EOF)`)でも本文を閉じる
    (bash 5 の読み。zsh は `EOF` だけの行で閉じるので、zsh の本文はこれより長く、除く字はどちらでも本文の中に在る)。"""
    stack, pending, spans = [], [], []
    i, n, escaped = 0, len(command), -1
    while i < n:
        c = command[i]
        top = stack[-1][0] if stack else None
        if c == "\\":
            escaped = i + 1
            i += 2
            continue
        if c == "`" or command.startswith(("$((", "$'", '$"'), i):
            return None
        if command.startswith("${", i):
            m = _PLAIN_BRACE_RE.match(command, i)
            if m is None:
                return None
            i = m.end()
            continue
        if command.startswith("$(", i):
            stack.append(("$(", i))
            i += 2
            continue
        if top == '"':
            if c == '"':
                stack.pop()
            i += 1
            continue
        if c == "'":
            j = command.find("'", i + 1)
            if j < 0:
                return None
            i = j + 1
            continue
        if c == '"':
            stack.append(('"', i))
        elif c == "(":
            if command.startswith("((", i):
                return None
            stack.append(("(", i))
        elif c == ")":
            if not stack:
                return None
            stack.pop()
        elif c == "#":
            prev = command[i - 1] if i else "\n"
            if i - 1 != escaped and prev in " \t\n;&|":
                nl = command.find("\n", i)
                i = n if nl < 0 else nl
                continue
            if i - 1 != escaped and prev in "()<>":
                return None   # zsh はパターンの字と読みうる(`(#i)`)
        elif c in "ce" and _CASE_RE.match(command, i):
            return None   # 型の閉じの ) を括弧と数えてしまう
        elif command.startswith("<<<", i):
            i += 3
            continue
        elif command.startswith("<<", i):
            head = _HERE_HEAD_RE.match(command, i)
            j, parts = head.end(), []
            while True:
                p = cr._DELIM_PART_RE.match(command, j)
                if p is None:
                    break
                parts.append(p.group(0))
                j = p.end()
            delim = "".join(w[1:] if w[0] == "\\" else w[1:-1] if w[0] in "'\"" else w for w in parts)
            if not cr._DELIM_RE.fullmatch(delim) or not cr._WORD_END_RE.match(command, j):
                return None
            pending.append((any(w[0] in "\\'\"" for w in parts), bool(head.group(1)), delim,
                            [at for kind, at in stack if kind == "$("], top == "$("))
            i = j
            continue
        elif c == "\n" and pending:
            i += 1
            for quoted, dash, delim, subs, in_sub in pending:
                start, close = i, None
                while close is None:
                    if i >= n:
                        return None   # 終わりの行が無い
                    nl = command.find("\n", i)
                    end = n if nl < 0 else nl
                    line = command[i:end]
                    word = line.lstrip("\t") if dash else line
                    if word.rstrip("\r") == delim:
                        close = end + 1
                    elif in_sub and word.startswith(delim + ")"):
                        if len(pending) > 1:
                            return None
                        close = i + len(line) - len(word) + len(delim)   # ) からはコマンド
                    else:
                        i = end + 1
                if any(_closes_in(command, s, i, comments) for s in subs for comments in (True, False)):
                    return None
                if quoted and i > start:
                    spans.append((start, i))
                i = close
            pending = []
            continue
        i += 1
    if stack or pending or not spans:
        return None
    out, at = [], 0
    for start, end in spans:
        out.append(command[at:start])
        at = end
    return "".join(out) + command[at:]


def check_command(cr, command, cwd, depth=0, outer=None):
    """Bash のコマンド 1 本を見る。止める起点が在れば Hit を投げる。outer は、このコマンドが外のコマンドの $( … )・bash -c・eval・
    ヒアドキュメントの中身のとき、外の Scope(その単純コマンドの位置に合わせた物)。中で解けない変数を外の代入で解く。"""
    if depth > MAX_DEPTH or not command.strip():
        return
    text, bodies = cr.prepare(command)
    if text is None:
        # 正規化で読めない形(`$[`・`$$(`・`<<\EOF` など。prepare が None を返す)は、どのコマンドがどこで走るかを決められない
        # ので止める(検査自体の失敗として)。字面の find だけを拾うと、`: $[0]; rg foo /`・`: $[0]; cd / && find .` を通す。
        # ただし、探すツールの語が、区切りを引用したヒアドキュメントの本文(シェルが展開も実行もしない字)の中にしか無ければ
        # 通す(前は `git commit -m "$(cat <<'EOF'` の本文の「grep -r」「find (x)」の字で止めていた)
        rest = without_quoted_bodies(cr, command)
        if rest is not None and not WORD_RE.search(rest.replace("\\n", "\n").replace("\\t", "\t")):
            return
        raise ValueError("コマンドを読めない形(`$[ ]`・`<<\\EOF` など)なので、探す起点を決められない")
    tokens = cr.tokenize(text)
    if tokens is None:
        # 引用が閉じないなどで読めない: 素の find / だけは字面で拾う(シェルもたいてい走らせないが、落とすと黙って通る)
        m = re.search(r"(?:^|[\s;&|(`])(?:find|bfs|gfind)\s+(?:-[HLP]\s+)*(\S+)", text)
        if m:
            check_path(m.group(0).split()[0].lstrip(";&|(`"), m.group(1).strip("'\""), cwd)
        return
    cmds = cr.split_commands(tokens)
    files = Scope(cmds, cwd, bodies, text, tokens)
    files.outer = outer
    seen, places, ticks = set(), {cwd}, set()
    for k, c in enumerate(cmds):
        at = cr.command_start(c.args)
        heres = files.at(k, c.args[:at]).cwds_here()
        places.update(heres)
        if any("`" in a for a in c.args):
            ticks.update(heres)
        inners = {x for a in c.args for x in substitutions(a)}
        # 区切りを引用しないヒアドキュメントの本文の $( … ) と ` … ` は、どのコマンドの本文でも、そのコマンドの場所で走る
        # (前は本文をシェルに渡すときだけ読み、`cat <<EOF > out.txt` の次の行の `$(find / …)` を通していた)。
        # 区切りを引用した本文(Expands でない)は展開しないので読まない
        inners |= {x for b in cr.own_heredocs(c.args, bodies) if isinstance(b, cr.Expands)
                   for x in substitutions(b, heredoc=True)}
        seen |= inners
        for here in heres:
            # 1 語に残った $( … )(二重引用の中)は、その語を持つコマンドの cwd と、外の代入で見る(前はフックの cwd だけで見て、
            # `cd / && echo "$(find . …)"` を通し、`cd /tmp && echo "$(find . …)"` をホームの cwd で止めていた)
            for inner in inners:
                check_command(cr, inner, here, depth + 1, files.at(k, c.args[:at]))
            check_simple(cr, files.at(k, c.args[:at]), cmds, k, c.args[at:], bodies, here, depth)
    # 語に割れなかった中身(` … ` など)は、どのコマンドの中かを語の列から決められないので、` を語に持つコマンドの走りうる
    # 場所のどれでも見る(` の語が無ければ、フックの cwd と各コマンドの cwd)。前はフックの cwd だけで見て、
    # `cd / && a=`find . …`` を通していた。後ろの cd の行き先では見ない(`cd ~/p && n=`find .` && cd ~` を止めない)。
    # 引用の外の $( … ) はトークン化が単純コマンドに割って上で見た
    if cmds:
        files.at(len(cmds) - 1, ())   # 変数は、このコマンドの中のどの代入からでも解く
    for inner in substitutions(text, bare=False):
        if inner not in seen:
            for place in ticks or places:
                check_command(cr, inner, place, depth + 1, files if cmds else outer)


def command_words(cr, words):
    """前置を越えた語の列と、xargs の後ろか。前置(nice -n 19 find …・xargs -0 rg …)の後の env・timeout なども越える
    (nice -n 19 timeout 300 find …)。パスで書いた前置(/usr/bin/time・/usr/bin/env)も名前で越える。"""
    hops = False
    while words:
        base = os.path.basename(words[0])
        if base in HOPS:
            hops = hops or base == "xargs"
            words = after_hop(words)
        elif base in cr.WRAPPERS and base != words[0]:
            words = [base] + words[1:]
        else:
            break
        words = words[cr.command_start(words):]
    return words, hops


def glued_find_args(cmds, k):
    r"""find の引数。式の \( \) と -exec の後ろの \; はトークン化で区切りと読まれ、後ろが別のコマンドに割れるので、
    括弧だけ(または開いた -exec の後の ; だけ)で続くコマンドを繋ぎ直す。閉じる括弧が開いた数を超えたら(本物のサブシェルの
    閉じ)そこで止める。"""
    args, open_ = list(cmds[k].args), 0
    for m in range(k + 1, len(cmds)):
        ops = [op for op, _ in cmds[m].ops]
        exec_open = any(a in FIND_EXEC for a in args) and not any(
            a in (";", "+") for a in args[max(i for i, a in enumerate(args) if a in FIND_EXEC):])
        if ops == [";"] and exec_open:
            args += [";"] + cmds[m].args
            continue
        if not ops or not all(op in "()" for op in ops):
            break
        for op in ops:
            open_ += 1 if op == "(" else -1
            if open_ < 0:
                return args
        args += ops + cmds[m].args
    return args


def shell_stdin(args):
    """bash・sh などが標準入力のスクリプトを走らせるか(-c が無く、スクリプトのファイルを取らないか、-s が在る)。"""
    args = [a for a in args if not re.fullmatch(r"__HEREDOC\d+__", a)]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return i + 1 == len(args)
        if not a.startswith(("-", "+")):
            return False   # スクリプトのファイル
        if not a.startswith("--"):
            if "c" in a[1:]:
                return False
            if "s" in a[1:]:
                return True
            if a[-1:] in ("o", "O"):
                i += 1   # 値を取る旗(-o pipefail)
        i += 1
    return True


def stdin_scripts(cr, cmds, k, c, bodies):
    """k 番目のコマンド(標準入力を読むシェル)が読むスクリプト: 自分のヒアドキュメント・<<< の文字列・前の echo・printf からの
    パイプの中身。"""
    out = list(cr.own_heredocs(c.args, bodies)) + [t for op, t in c.redirects if op == "<<<"]
    if k and any(op == "|" for op, _ in c.ops):
        words, _ = command_words(cr, cmds[k - 1].args[cr.command_start(cmds[k - 1].args):])
        if words[:1] in (["echo"], ["printf"]):
            rest = [w for w in words[1:] if not re.fullmatch(r"-[neE]+", w)]
            out.append(" ".join(rest).replace("\\n", "\n"))
    return out


def check_simple(cr, files, cmds, k, words, bodies, here, depth):
    """k 番目の単純コマンド(前置の環境変数と env などを除いた語 words)を、cwd が here のときとして見る。"""
    words, hops = command_words(cr, words)
    c = cmds[k]
    at = cr.command_start(c.args)
    if not words or ("command" in c.args[:at] and {"-v", "-V"} & set(c.args[:at])):
        return   # command -v rg は在るかを引くだけ
    name = os.path.basename(words[0])
    if name in SHELLS:
        script = shell_script(words[1:])
        if script is not None:
            check_command(cr, script, here, depth + 1, before_scope(cr, cmds, k, files, bodies, script))
        elif shell_stdin(words[1:]):
            for script in stdin_scripts(cr, cmds, k, c, bodies):
                check_command(cr, script, here, depth + 1, before_scope(cr, cmds, k, files, bodies, script))
        return
    if name == "eval":
        check_command(cr, " ".join(words[1:]), here, depth + 1, before_scope(cr, cmds, k, files, bodies, " ".join(words[1:])))
        return
    args = words[1:]
    if name in FIND:
        args = glued_find_args(cmds, k)[len(c.args) - len(words) + 1:]
        for run, in_place in find_execs(args):
            check_command(cr, shlex.join(run), None if in_place else here, depth + 1, files)
    piped = any(op == "|" for op, _ in c.ops)
    for start in starts_of(name, args, piped, hops):
        if "$" in start:
            start = files.var(start)
        check_path(name, start, here)


def before_scope(cr, cmds, k, files, bodies, inner):
    """k 番目の eval・bash -c・殻の標準入力の中身 inner の変数を解く Scope。coldread の Scope は eval が在ると全部の変数を
    解かず、inner の中の引用(`bash -c 'find $D'`)や `\\$` の後の $ を字のままと見るが、eval と中の殻はそれも展開する。
    そこで k 番目をただの代入(前置の代入 `D=/ bash -c …` は中の殻の環境に入る)か : に替えた列で、inner の $ を生きた物として
    解く(前は `D=/; eval 'find $D'`・`export D=/; bash -c 'find $D'`・`D=/ bash -c 'find $D'` を通していた)。
    export しない代入も中の殻に渡ると見る(止める側に倒す)。"""
    c = cmds[k]
    stubs = []
    # 前置の語のうち代入だけ(`D=/ timeout 60 bash -c …`・`env D=/ sh -c …` の timeout・env は除く)
    for args in ([a for a in c.args[:cr.command_start(c.args)] if cr.ENV_PREFIX_RE.match(a)], [":"]):
        if args:
            stubs.append(copy.copy(c))
            stubs[-1].args = args
    line = cmds[:k] + stubs
    # 語は二重引用で包んで並べる(`echo "it's"` の ' で引用が割れ、どの変数も解けなくなるのを防ぐ。$ は生きたまま)
    live = "; ".join(" ".join('"%s"' % re.sub(r'(["\\`])', r"\\\1", a) for a in cc.args) for cc in line) + "; " + inner
    before = Scope(line, files.cwd, bodies, live).at(len(line) - 1, [])
    before.outer = files.outer
    return before


def after_hop(words):
    """前置(words[0])の旗と、値を取る旗の値と、数を飛ばした残り。"""
    values, i = HOPS[os.path.basename(words[0])], 1
    while i < len(words):
        w = words[i]
        if w in values:
            i += 2
        elif w.startswith("-") or w.isdigit() or re.match(r"[A-Za-z_][A-Za-z0-9_]*=", w):
            i += 1
        else:
            break
    return words[i:]


def shell_script(args):
    """bash・sh などの引数から -c の文字列を返す。-c が無ければ None(ファイルか stdin を走らせる)。"""
    i, has_c = 0, False
    while i < len(args):
        a = args[i]
        if not a.startswith(("-", "+")):
            return a if has_c else None
        if not a.startswith("--"):
            has_c = has_c or "c" in a[1:]
            if a[-1] in "oO":
                i += 1   # 値を取る旗(-o pipefail・-euo pipefail)
        i += 1
    return None


def glob_root(pattern):
    """Glob の型から、字のまま決まる頭の部分(最初の *?[{ を含む区切りの前まで)。"""
    parts = pattern.replace("\\", "/").split("/")
    head = []
    for part in parts:
        if any(ch in part for ch in "*?[{"):
            break
        head.append(part)
    if len(head) == len(parts):
        head = head[:-1]   # 型に字の物しか無ければ、最後はファイルの名前
    root = "/".join(head)
    return root or ("/" if pattern.startswith("/") else ".")


def check_tool(tool, args, cwd):
    """Glob・Grep のツールを見る。path が無ければ会話の cwd から探す。"""
    path = args.get("path") or "."
    if tool == "Glob":
        pattern = args.get("pattern") or ""
        if not any(ch in pattern for ch in "*?[{"):
            return   # 字だけの型は 1 つのパスを見るだけで、下をたどらない
        root = glob_root(pattern)
        if not (is_abs(root) or root.startswith(("~", "$"))):
            base = resolve(path, cwd)
            if base is None:
                return   # 起点の path が決まらない
            root = posixpath.join(base, root)
        path = root
    check_path(tool, path, cwd)


def deny(cr, tool, start):
    gate_shell.refuse(
        cr, "searchgate", "deny %s %s" % (tool, start),
        "searchgate: %s の起点 %s は / やホームの全体なので止めた。全体を探すとマシン全体が重くなり"
        "（2026-10-24 に / からの find 2 本で 1 時間に CPU 860%%）、時間切れの後も残る。"
        "作業場の中か、探す物の置き場（例: ~/.cache/<ツール>/・~/src/<リポジトリ>）を起点にして打ち直すこと。"
        "置き場が分からなければ、先にそのツールの文書か設定を読む。止める起点は %s で、それより下は通る。"
        "このゲートに逃げ道は無い。" % (tool, start, WIDE_TEXT)
    )


def main():
    raw = json.load(sys.stdin)
    tool = raw.get("tool_name")
    args = raw.get("tool_input") or {}
    cwd = raw.get("cwd") or None
    if not isinstance(args, dict):
        raise ValueError("tool_input が object でない")
    if tool == "Bash":
        command = args.get("command", "")
        if not isinstance(command, str):
            raise ValueError("tool_input.command が文字列でない")
        if not WORD_RE.search(command.replace("\\n", "\n").replace("\\t", "\t")):
            return   # 探すツールの語が無い(bash -c・eval・$( ) の中も字としては同じ文字列に在る。printf 'cd /\nfind .' | sh の \n は改行と見る)
    elif tool not in ("Glob", "Grep"):
        return
    cr = load_coldread()
    try:
        if tool == "Bash":
            check_command(cr, command, cwd)
        else:
            check_tool(tool, args, cwd)
    except Hit as hit:
        deny(cr, hit.args[0], hit.args[1])


def layout(cr, tokens):
    """単純コマンドごと(split_commands と同じ順)の (囲むブロックの道, 括弧の深さ, 直前の区切り((演算子, 深さ) の列), 語の頭)。
    split_commands と数が合わなければ None。

    道は外から順の (ブロックの番号, 区画の番号, 条件の区画か)。区画は if の条件・then・elif の条件・else、繰り返しの条件と do の後、
    case の ;; ごとに分ける。case の型の閉じ `a)` は括弧に数えない(coldread の深さはそこで負になり、cd が届くかを読み違える)。"""
    out, stack, ops, depth, cur, head, nid = [], [], [], 0, [], None, 0

    def close():
        if cur:
            out.append(head)
            cur.clear()

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok and all(ch in cr.OP_CHARS for ch in tok):
            if tok in cr.REDIRECT_OPS:
                if cur and cur[-1].isdigit():
                    cur.pop()
                i += 2
                continue
            close()
            for op in cr._OP_RE.findall(tok):
                top = stack[-1] if stack else None
                if top and top[1] == "case" and top[4] and op in "()":
                    top[4] = op == "("   # 型の頭の ( と閉じの ): 括弧ではない
                    continue
                if op == ";;" and top and top[1] == "case":
                    top[2], top[4] = top[2] + 1, True
                if op == ")":
                    depth -= 1
                ops.append((op, depth))
                if op == "(":
                    depth += 1
            i += 1
            continue
        if not cur and tok in cr.RESERVED:
            top = stack[-1] if stack else None
            if tok in ("if", "while", "until"):
                nid += 1
                stack.append([nid, tok, 0, True, False])
            elif top and tok in ("then", "do", "else"):
                top[2], top[3] = top[2] + 1, False
            elif top and tok == "elif":
                top[2], top[3] = top[2] + 1, True
            i += 1
            continue
        if not cur:
            head = (tuple((e[0], e[2], e[3]) for e in stack), depth, ops, tok)
            ops = []
            if tok in ("for", "select", "case"):
                nid += 1
                stack.append([nid, tok, 1 if tok == "case" else 0, False, tok == "case"])
            elif tok in ("fi", "done", "esac") and stack:
                stack.pop()
        cur.append(tok)
        i += 1
    close()
    return out


def load_coldread():
    cr = gate_shell.load_coldread()
    global Scope

    class Scope(cr.BodyFiles):
        """変数と cd の追い方は coldread と同じ 1 本。~ と $HOME だけ先にホームへ開く(coldread は本文のパスでしか開かない)。"""

        outer = None   # 外のコマンドの Scope(このコマンドが $( … )・bash -c・eval・ヒアドキュメントの中身のとき)

        def assigned(self):
            if self._assigned is None:
                table = super().assigned()
                if "HOME" not in table:   # 代入の値の中の ~・$HOME も開く(D=$HOME; find $D)
                    self._assigned = {n: v and (expand_home(v[0]), v[1]) for n, v in table.items()}
            return self._assigned

        def var(self, value):
            got = super().var(expand_home(value) if "HOME" not in self.assigned() else value)
            if got is None and self.outer is not None:
                got = self.outer.var(value)   # 中で解けない変数は外の代入で解く(D=/; bash -c "find $D")
            return got

        def __init__(self, cmds, cwd, heredocs, norm, tokens=()):
            super().__init__(cmds, cwd, heredocs, norm, tokens)
            # 代入は、if・繰り返しの中でも解く(走ったときの値を起点として見る。止める側に倒す)。前は 1 つでも在れば
            # コマンド全体で変数と cd を解かず、`for f in *; do n=$f; done; cd / && find .` を通していた。
            # cd が走るかは、cd ごとに cwds_here で見る
            self.conditional = False
            lay = layout(cr, tokens)
            self.lay = lay if lay is not None and len(lay) == len(cmds) else None

        def _reaches(self, j, k):
            """j 番目の cd の効果が k 番目に届くか(同じシェルの中か)。届かないのは、パイプの中・& で後ろに回した・
            サブシェル(`( … )`・`$( … )`)が k より前に閉じたとき。"""
            _, d, ops, _ = self.lay[j]
            if any(op == "|" and dep == d for op, dep in ops):
                return False
            if any(op in ("|", "&") and dep == d for op, dep in self.lay[j + 1][2]):
                return False
            for m in range(j + 1, k + 1):
                if any(op == ")" and dep < d for op, dep in self.lay[m][2]):
                    return False
            return self.lay[k][1] >= d

        def _surely(self, j, k):
            """届く cd(j 番目)が、k 番目が走るときには必ず走ったか。前の区切りが ; 改行 && だけ(&& なら k までも && だけ)で、k までに || が無い
            (`cd x || exit 1` の || は除く)うえ、cd を囲むブロックがどれも k も囲むか、k が後ろに在る if・繰り返しの条件の中のとき。"""
            path, d, ops, _ = self.lay[j]
            if any(op not in (";", "\n", "&&") for op, _ in ops if op not in "()"):
                return False
            if any(op == "&&" for op, _ in ops):
                # `test -d sub && cd sub; find .` の cd は前が落ちると走らず、; の後ろの find はそれでも走る。&& の後の cd は、
                # k までが && だけで繋がる(同じ深さ以浅に ; 改行 & が無い)ときだけ必ず走った
                for m in range(j + 1, k + 1):
                    if any(op in (";", "\n", "&") and dep <= d for op, dep in self.lay[m][2]):
                        return False
            for m in range(j + 1, k + 1):
                for op, dep in self.lay[m][2]:
                    if op == "||" and dep <= d and not (m == j + 1 and self.lay[m][3] in ("exit", "return")):
                        return False
            kpath = self.lay[k][0]
            same = 0
            while same < min(len(path), len(kpath)) and path[same] == kpath[same]:
                same += 1
            return all(cond for _, _, cond in path[same:])

        def cwds_here(self, k=None):
            """k 番目(既定は今のコマンド)が走りうる cwd の列(None は決まらない)。前の cd を順にたどる: 必ず走る cd は行き先、
            走るとは限らない cd(if・繰り返し・|| の中)は行き先と前の場所の両方、効果が届かない cd(サブシェル・パイプ)は
            前の場所のまま。行き先の読めない cd(`cd -`・`cd $X`)の行き先は決まらない(走るとは限らない cd なら前の場所も見る。
            前は `cd /; if [ -n "$X" ]; then cd "$X"; fi; find .` を通していた)。相対の行き先は、そこまでに
            決まった場所に繋ぐ(`cd .. && find .`)。"""
            k = self.k if k is None else k
            if self.moved:
                return [None]
            places = [self.cwd]
            for j in range(k):
                c = self.cmds[j]
                if not any(t in cr.CD_WORDS for t in c.args):
                    continue
                reach, surely = (self._reaches(j, k), self._surely(j, k)) if self.lay else (True, False)
                if not reach:
                    continue
                new = []
                for place in places:
                    dest = self.cd_dest(c.args[cr.command_start(c.args):], place)
                    dest = cr.native_path(dest) if dest else None
                    if not (dest and os.path.isabs(dest)):
                        new += [None] if surely else [None, place]
                    else:
                        new += [dest] if surely else [dest, place]
                places = list(dict.fromkeys(new))
                if len(places) > PLACES_MAX:
                    # 走るとは限らない cd が続くと場所は倍々に増える(20 個で時間切れになり、時間切れは通す)。広い場所は
                    # 浅いので、浅い物から残す
                    places = sorted(places, key=lambda p: len(p or ""))[:PLACES_MAX]
            return places

        def cd_dest(self, args, base=None):
            """`cd <行き先>`・`pushd <行き先>` の行き先。引数の無い cd はホーム。相対の行き先は base に繋ぐ。読めなければ None。"""
            while args[:1] in (["builtin"], ["command"]):
                args = args[1:]
            if args[:1] not in (["cd"], ["pushd"]):
                return None
            rest = args[1:]
            if args[0] == "cd":
                while rest[:1] and rest[0] in ("-P", "-L", "-e", "-@", "-Pe", "-eP"):
                    rest = rest[1:]
                if rest[:1] == ["--"]:
                    rest = rest[1:]
                if not rest:
                    return home()
            if len(rest) != 1 or rest[0] == "-" or rest[0].startswith(("-", "+")) and args[0] == "pushd":
                return None
            dest = self.var(rest[0])
            if dest is None:
                return None
            if os.path.isabs(dest):
                return dest
            if dest.startswith("~") or not base or not os.path.isabs(base):
                return None
            return os.path.normpath(os.path.join(base, dest))

    return cr


Scope = None
PLACES_MAX = 32   # 1 つのコマンドが走りうる cwd を覚える数の上限(cwds_here)


if __name__ == "__main__":
    gate_shell.run(main, lambda why: "searchgate: 探す起点の検査自体に失敗した(%s)。" % why)
