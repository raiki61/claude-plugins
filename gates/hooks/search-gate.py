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
import bisect
import copy
import itertools
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
        # xargs は GNU と BSD の値を取る旗(GNU の長い形も)。-e・-i・-l と --eof・--replace・--max-lines の値は
        # = か語に付けてだけ渡る
        "xargs": {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "-J", "-R", "-S", "--arg-file", "--delimiter",
                  "--max-args", "--max-procs", "--max-chars", "--process-slot-var"},
        "caffeinate": {"-t", "-w"},
        # GNU parallel。後ろのコマンドの引数は ::: の後ろの値を足した物(parallel_words)。旗は parallel の
        # options_completion_hash の =s・=i の物と、:s の -i・-e・--replace・--eof(Getopt::Long は次の語を値に取る)。
        # :f の -l・--max-lines は数のときだけ次の語を取る(数は after_hop が飛ばす)ので入れない
        "parallel": {"-a", "-B", "-C", "-D", "-d", "-E", "-e", "-H", "-I", "-i", "-J", "-j", "-L", "-N", "-n", "-P",
                      "-S", "-s", "-U", "-W", "--arg-file", "--arg-file-sep", "--arg-sep", "--argfile", "--argfilesep",
                      "--argsep", "--basefile", "--basenameextensionreplace", "--basenamereplace", "--bf", "--bin",
                      "--block", "--block-size", "--block-timeout", "--blocksize", "--blocktimeout", "--bner", "--bnr",
                      "--bt", "--col-sep", "--colsep", "--combine-exec", "--combine-executable", "--combineexec",
                      "--combineexecutable", "--compressprogram", "--ctag-string", "--ctagstring", "--debug",
                      "--decompressprogram", "--delay", "--delimiter", "--dirnamereplace", "--dnr", "--env", "--eof",
                      "--er", "--extensionreplace", "--filter", "--group-by", "--groupby", "--halt", "--halt-on-error",
                      "--haltonerror", "--header", "--id", "--jl", "--joblog", "--jobs", "--limit",
                      "--linkinputsource", "--load", "--match", "--max-args", "--max-chars", "--max-procs",
                      "--max-replace-args", "--maxargs", "--maxchars", "--maxprocs", "--maxreplaceargs", "--memfree",
                      "--memsuspend", "--milestone", "--min-version", "--minversion", "--ms", "--nice", "--parens",
                      "--process-slot-var", "--processslotvar", "--profile", "--recend", "--recstart", "--replace",
                      "--res", "--result", "--results", "--retries", "--return", "--rpl", "--rsync-opts",
                      "--rsyncopts", "--semaphore-name", "--semaphore-timeout", "--semaphorename",
                      "--semaphoretimeout", "--seqreplace", "--shard", "--shell-completion", "--shellcompletion",
                      "--slf", "--slotreplace", "--sql", "--sql-and-worker", "--sql-master", "--sql-worker",
                      "--sqlandworker", "--sqlmaster", "--sqlworker", "--ssh", "--ssh-delay", "--sshdelay",
                      "--sshlogin", "--sshloginfile", "--st", "--tag-string", "--tagstring", "--tempdir", "--template",
                      "--term-seq", "--termseq", "--tf", "--timeout", "--tmpdir", "--tmpl", "--total", "--total-jobs",
                      "--totaljobs", "--transfer-file", "--transfer-files", "--transferfile", "--transferfiles",
                      "--trc", "--trim", "--usecompressprogram", "--usedecompressprogram", "--wd", "--work-dir",
                      "--workdir", "--xapplyinputsource"},
        "stdbuf": {"-i", "-o", "-e"}, "ionice": {"-c", "-n", "-p"}, "taskpolicy": {"-c", "-t", "-l", "-p"},
        "arch": set(), "chrt": set(), "builtin": set()}
# 前段の粗選別: 探すツールの語もシェルの入れ子も無いコマンドは、解析部を読み込まずに通す(Bash のたびに走るので)
# grep は再帰の旗の在るときだけ読む(`| grep foo` のたびに解析部を読み込まない)。Claude Code の grep は ugrep で走り、
# -NUM(-5・-5r)と --depth も下をたどるので、数の旗も読む。旗を引用符で囲んでも('-r')シェルは同じに渡す
WORD_RE = re.compile(r"(?<![\w.-])(?:find|bfs|gfind|fd|fdfind|rg|rgrep)(?![\w.-])"
                     r"|(?<![\w.-])(?:e?grep|fgrep|ggrep)(?![\w.-]).*?(?:\s['\"]?-[A-Za-z0-9]*[rRd0-9]|--recursive"
                     r"|--dereference-recursive|--directories|--depth)", re.S)
# 入れ子は 8 段まで読む(`bash -c "bash -c '…'"` の深さ。それより深い中身は、探すツールの語が在れば読み切れないとして止める)
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


def _close(text, i):
    """i の $( を閉じる ) の次の位置を、中の単一引用・二重引用・\\・` … `・入れ子の $( ) を見て決める。閉じなければ None。"""
    depth, j, n = 1, i + 2, len(text)
    while j < n:
        c = text[j]
        if c == "\\":
            j += 1
        elif c == "'":
            j = text.find("'", j + 1)
            if j < 0:
                return None
        elif c == "`":
            j = _tick_end(text, j)
            if j is None:
                return None
        elif c == '"':
            j += 1
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    j += 1
                elif text.startswith("$(", j):
                    j = _close(text, j)
                    if j is None:
                        return None
                    continue
                elif text[j] == "`":
                    j = _tick_end(text, j)
                    if j is None:
                        return None
                j += 1
            if j >= n:
                return None
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if not depth:
                return j + 1
        j += 1
    return None


def _tick_end(text, i):
    """i の ` を閉じる ` の位置(\\ の後の字は飛ばす)。閉じなければ None。"""
    j = i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
        elif text[j] == "`":
            return j
        else:
            j += 1
    return None


def substitutions(text, bare=True, heredoc=False):
    """引用の単一の外にある $( … ) と ` … ` の中身。二重引用の中も読む(シェルが展開する)。bare が偽なら、引用の外の $( … ) は
    返さない(トークン化がその語に中身を subs として残すか、閉じる所を言い切れなければ単純コマンドに割り、外のコマンドの cd と
    代入の中で見るので)。heredoc が真なら、text は
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
            # 引用の中の ) では閉じない(前は引用を見ずに数え、`x=$(echo ')' `rg foo /`)` の ' の中の ) で閉じたと読んで、後ろの
            # ` … ` を単一引用の中と見て通していた)。引用を見て閉じる所が決まれば、引用を見ない数え方と遠い方まで中身にする
            j = max(j, _close(text, i) or 0)
            if bare or quote == '"':
                out.append(text[i + 2:j - 1])
            elif "`" in text[i + 2:j - 1]:
                # 中に ` が在る引用の外の $( … ) は、トークン化が語に留めず単純コマンドに割る。割った語は ` の中身を持たないので、
                # 中の ` … ` をここで拾う(前は $( … ) ごと飛ばし、`x=$(echo `rg foo /`)` を通していた)
                out.extend(substitutions(text[i + 2:j - 1], bare=False))
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
            i = exec_end(args, i)
        elif a in FIND_VALUE or FIND_NEWER_RE.fullmatch(a):
            i += 1
        elif a == "-fprintf":
            i += 2
        elif not a.startswith(("-", "(", "!", ")")) and a != ",":
            starts.append(a)
        i += 1
    return starts or ["."]


def exec_end(args, i):
    r"""args[i] の -exec などを閉じる語(; か、{} の直後の +)の位置。閉じが無ければ len(args)。+ は {} の直後でだけ閉じる
    (前は + の語で閉じたと見て、`find . -exec rg + -newer / \;` の / を見落とした。glued_find_args と同じ読み方)。"""
    j = i + 1
    while j < len(args) and not (args[j] == ";" or (args[j] == "+" and args[j - 1] == "{}")):
        j += 1
    return j


def find_execs(args):
    """find の -exec・-ok(cwd で走る)と -execdir・-okdir(見つけた物の所で走る)の後ろのコマンド → (語の列, 所で走るか) の列。"""
    out, i = [], 0
    while i < len(args):
        if args[i] in FIND_EXEC:
            j = exec_end(args, i)
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


# fd の -x・-X の後ろのコマンドの、見つけた物に置き換える印(fd の README の「Placeholder syntax」)
FD_PLACEHOLDER_RE = re.compile(r"\{(?:/|//|\.|/\.)?\}")


def fd_split(args):
    """fd の引数 → (fd そのものの引数, -x・-X・--exec・--exec-batch の後ろの走らせるコマンドの語の列の列)。走らせるコマンドは、
    ; の語か fd の引数の終わりまで(fd は ; の後ろをまた fd の引数と読む)。"""
    own, runs, i, rest = [], [], 0, False
    while i < len(args):
        a, start = args[i], None
        if rest or a == "-" or not a.startswith("-"):
            own.append(a)
        elif a == "--":
            rest = True
            own.append(a)
        elif a.startswith("--"):
            name, eq, val = a.partition("=")
            if name in ("--exec", "--exec-batch"):
                start = [val] if eq else []
            else:
                own.append(a)
                if not eq and name in FD_LONG and i + 1 < len(args):
                    i += 1
                    own.append(args[i])
        else:
            for j in range(1, len(a)):
                if a[j] in "xX":
                    start = [a[j + 1:]] if a[j + 1:] else []
                    if j > 1:
                        own.append(a[:j])
                    break
                if a[j] in FD_SHORT:
                    own.append(a)
                    if j + 1 == len(a) and i + 1 < len(args):
                        i += 1
                        own.append(args[i])
                    break
            else:
                own.append(a)
        if start is not None:
            j = i + 1
            while j < len(args) and args[j] != ";":
                j += 1
            runs.append(start + args[i + 1:j])
            i = j
        i += 1
    return own, runs


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
        args, _ = fd_split(args)   # -x・-X の後ろは fd が走らせるコマンド
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


# 標準入力や置換の中身をスクリプトとして走らせうる語(bash <<'EOF'・ssh host bash <<'EOF'・bash -c "$(cat <<'EOF'"・eval)
_SHELL_WORD_RE = re.compile(r"(?<![\w.-])(?:bash|sh|zsh|dash|ksh|eval|source)(?![\w.-])")


def _opening_lines(command, at, start):
    """at の `<<` を書いた開始行(\\ で前の行からつながるなら、つないだ行の全部)から、本文の前(start)まで。"""
    head = command.rfind("\n", 0, at) + 1
    while head > 1 and command[head - 2] == "\\" and (head < 3 or command[head - 3] != "\\"):
        head = command.rfind("\n", 0, head - 1) + 1
    return command[head:start]


def without_quoted_bodies(cr, command):
    """区切りを引用したヒアドキュメント(`<<'EOF'`・`<<"EOF"`・`<<\\EOF`・`<<E"OF"`)の本文を除いたコマンド。シェルはその本文を
    展開も実行もしないので、本文の中の字は探すツールの語でない。除く本文が無いか、読み切れない形(閉じない引用・バッククォート・
    `$((`・`$'`・中身の在る `${ }`・case・迷う #・終わりの行の無い本文・bash 3.2 が本文の中で置換を閉じる形)なら None。

    区切りを引用しない本文は除かない(シェルが中の `$( )` を走らせる)。開始行(\\ でつないだ行を含む)にシェル・eval・source の語が
    在る本文も除かない(`bash <<'EOF'`・`ssh host bash <<'EOF'`・`bash -s <<'EOF'` の本文はシェルが走らせるスクリプト。前は除いて、
    `x=$[1+1]; bash <<'EOF'` の本文の `find / -name x` を通していた)。開始行が \\ で次の行へつながるときは、つないだ行の後から
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
                            [at for kind, at in stack if kind == "$("], top == "$(", i))
            i = j
            continue
        elif c == "\n" and pending:
            i += 1
            for quoted, dash, delim, subs, in_sub, at in pending:
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
                if quoted and i > start and not _SHELL_WORD_RE.search(_opening_lines(command, at, start)):
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


def check_command(cr, command, cwd, depth=0, outer=None, held=None):
    """Bash のコマンド 1 本を見る。止める起点が在れば Hit を投げる。outer は、このコマンドが外のコマンドの $( … )・bash -c・eval・
    ヒアドキュメントの中身のとき、外の Scope(その単純コマンドの位置に合わせた物)。中で解けない変数を外の代入で解く。held は、
    command が外のコマンドの $( … )・<( … )・` … ` の中身のとき、外の prepare が抜いたヒアドキュメントの本文の並び。"""
    if depth > MAX_DEPTH:
        # 読む段の終わりより深い中身(二重引用の中の $( )・bash -c・eval など)に探すツールの語が在れば、読み切れないとして止める
        # (前は黙って通し、9 段より深い `$(echo …"$(rg foo /)"…)`・`$(… bash -c 'rg foo /' …)` を通していた)
        if WORD_RE.search(command.replace("\\n", "\n").replace("\\t", "\t")):
            raise ValueError("$( )・bash -c などの入れ子が深く、探す場所を読み切れない")
        return
    if not command.strip():
        return
    if depth == 0:
        SPENT.update(reads=0, walks=0, steps=0)
    else:
        SPENT["reads"] += len(command) + READ_COST   # 中身の読み直しは掛け算で増えうる(READS_MAX)
        if SPENT["reads"] > READS_MAX:
            raise ValueError("入れ子の $( ) と cd が多く、探す場所を読み切れない")
    text, bodies = cr.prepare(command)
    if held and not bodies:
        # 外の prepare が本文を印(__HEREDOC0__)に替えた後の中身なので、中の印は外の本文を指す(前は本文を持たずに読み直し、
        # `x=$(bash <<'EOF'` の本文の rg foo /・`$(cat <<EOF` の本文の `$(find / …)` を通していた)
        bodies = held
    if text is None:
        # 正規化で読めない形(`$[`・`$$(`・`<<\EOF` など。prepare が None を返す)は、どのコマンドがどこで走るかを決められない
        # ので止める(検査自体の失敗として)。字面の find だけを拾うと、`: $[0]; rg foo /`・`: $[0]; cd / && find .` を通す。
        # ただし、探すツールの語が、区切りを引用したヒアドキュメントの本文(シェルが展開も実行もしない字)の中にしか無ければ
        # 通す(前は `git commit -m "$(cat <<'EOF'` の本文の「grep -r」「find (x)」の字で止めていた)
        rest = without_quoted_bodies(cr, command)
        if rest is not None and not WORD_RE.search(rest.replace("\\n", "\n").replace("\\t", "\t")):
            return
        raise ValueError("コマンドを読めない形(`$[ ]`・`<<\\EOF` など)なので、探す起点を決められない")
    # 引用の外の $( … ) は 1 段ごとに中を読み直すので、読む段の終わり(MAX_DEPTH)では、前の割り方(中も単純コマンドに割る)で
    # 読む。語に留めたままだと、9 段より深い `$(echo $(…$(rg foo /)…))` の中を読まずに通す
    tokens = cr.tokenize(text, words=depth < MAX_DEPTH)
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
        # 引用の外の $( … )・<( … ) などは、tokenize が 1 語に留めて中身を語の subs に残す(リダイレクトの行き先の `< <(…)` も)。
        # 語の残りの字(二重引用の中の $( … ) と ` … `)は語から読む
        # 代入だけのコマンド(`D=/ x=$(rg foo $D)`)は、bash が左から順に代入するので、語の中の置換は前の語の代入を見る
        # (前は同じコマンドの代入を見ず、起点の $D を解けずに通していた)。中身ごとに、前の語までの代入を足した Scope で見る。
        # その語の置換は inners に入れない(前の語までの代入を足した Scope は、files.at の解く変数も解く。前は両方で読み、
        # 置換ごとに読む数が 2 倍になって、長いスクリプトで読む字の上限に当たっていた)
        # 頭に並んだ代入の語(`D=/ x=$(rg foo $D) true` の x=…)も同じ(前は代入だけのコマンドでしか前の語を見ず、通していた)
        lead = next((i for i, a in enumerate(c.args) if not cr.ENV_PREFIX_RE.match(a)), len(c.args))
        chained = range(1, lead)
        assigns = [(x, before_scope(cr, cmds, k, files, bodies, x, upto=i)) for i in chained
                   for x in dict.fromkeys(tuple(getattr(c.args[i], "subs", ())) + tuple(word_substitutions(c.args[i])))]
        own = [a for i, a in enumerate(c.args) if i not in chained]
        inners = {x for a in own + [d for _, d in c.redirects] for x in getattr(a, "subs", ())}
        inners |= {x for a in own for x in word_substitutions(a)}
        # 区切りを引用しないヒアドキュメントの本文の $( … ) と ` … ` は、どのコマンドの本文でも、そのコマンドの場所で走る
        # (前は本文をシェルに渡すときだけ読み、`cat <<EOF > out.txt` の次の行の `$(find / …)` を通していた)。
        # 区切りを引用した本文(Expands でない)は展開しないので読まない
        inners |= {x for b in cr.own_heredocs(c.args, bodies) if isinstance(b, cr.Expands)
                   for x in substitutions(b, heredoc=True)}
        seen |= inners
        seen.update(x for x, _ in assigns)
        for here in heres:
            # 1 語に残った $( … )(二重引用の中)は、その語を持つコマンドの cwd と、外の代入で見る(前はフックの cwd だけで見て、
            # `cd / && echo "$(find . …)"` を通し、`cd /tmp && echo "$(find . …)"` をホームの cwd で止めていた)
            for inner in inners:
                check_command(cr, inner, here, depth + 1, files.at(k, c.args[:at]), bodies)
            for inner, before in assigns:
                check_command(cr, inner, here, depth + 1, before, bodies)
            check_simple(cr, files.at(k, c.args[:at]), cmds, k, c.args[at:], bodies, here, depth)
    # 語に割れなかった中身(` … ` など)は、どのコマンドの中かを語の列から決められないので、` を語に持つコマンドの走りうる
    # 場所のどれでも見る(` の語が無ければ、フックの cwd と各コマンドの cwd)。前はフックの cwd だけで見て、
    # `cd / && a=`find . …`` を通していた。後ろの cd の行き先では見ない(`cd ~/p && n=`find .` && cd ~` を止めない)。
    # 引用の外の $( … ) は、トークン化が語の subs に残したか単純コマンドに割ったかで、上で見た
    if cmds:
        files.at(len(cmds) - 1, ())   # 変数は、このコマンドの中のどの代入からでも解く
    for inner in substitutions(text, bare=False):
        if inner not in seen:
            for place in ticks or places:
                check_command(cr, inner, place, depth + 1, files if cmds else outer, bodies)


def word_substitutions(word):
    """語に残った置換(二重引用の中の $( … ) と ` … `)の中身。引用の外の $( … ) は語の subs に在るので、残りの字から探す。"""
    return substitutions(word if getattr(word, "rest", None) is None else word.rest)


def command_words(cr, words):
    """前置を越えた語の列と、xargs・parallel の後ろか(parallel の後ろなら "parallel")。前置(nice -n 19 find …・xargs -0 rg …)の
    後の env・timeout なども越える(nice -n 19 timeout 300 find …)。パスで書いた前置(/usr/bin/time・/usr/bin/env)も名前で越える。
    語の列は元の語の列の後ろの部分のまま返す(find の引数を元の語の列から取り直すので)。コマンド名の位置の展開だけの語
    (`$(true) find …`・`$SUDO rg …`・`` `true` rg …``)も越える: 展開は空にも前置にもなりうるので、後ろの語をコマンドと見て読む
    (前はその語をコマンド名と読み、後ろの find・rg を見ずに通していた)。"""
    hops = False
    words = words[cr.command_start(words, skipped=[]):]
    while words:
        base = os.path.basename(words[0])
        if base in HOPS:
            hops = "parallel" if base == "parallel" else hops or base == "xargs"
            words = after_hop(words)
        elif base in cr.WRAPPERS and base != words[0]:
            words = [base] + words[1:]
        else:
            break
        words = words[cr.command_start(words, skipped=[]):]
    return words, hops


def glued_find_args(cmds, k):
    r"""find の引数。式の \( \) と -exec の後ろの \; はトークン化で区切りと読まれ、後ろが別のコマンドに割れるので、
    括弧と、開いた -exec の後の ; だけで続くコマンドを繋ぎ直す。区切りは 1 つずつ読む(`\; \)`・`\; \(` のように閉じの ; と
    括弧が並んでも繋ぐ。前は区切りの組で見て、`find . \( -name a -exec true \; \) -exec rg x / \;`・
    `find . -exec true \; \( -exec rg x / \; \)` の rg を見落とした)。-exec は `{} +` の + か ; でだけ閉じる(前は + の語で閉じたと見て、
    `find . -exec echo + \; -exec rg x / \;` の rg を見落とした)。閉じる括弧が開いた数を超えたら、find を囲むサブシェルが在れば
    (本物のサブシェルの閉じ)そこで止め、無ければ引用符で囲んだ字と見て繋ぐ(前はどちらも止め、`find fd -name ')' -exec rg x / \;`
    の rg を見落とした)。式の括弧か -exec が開いたまま、ほかの区切りで止まったら(読み切れない)、後ろに探すツールの語が在れば止める
    (投稿の前のゲート〔coldread-gate.py の glued_find〕と同じ読み方)。"""
    args, open_, closed = [], 0, True

    def add(words):
        nonlocal closed
        for w in words:   # 足した語だけを見る(繋ぐたびに全体を読み直さない)
            if w in FIND_EXEC:
                closed = False
            elif w == ";" or (w == "+" and args[-1:] == ["{}"]):
                closed = True
            args.append(w)

    add(cmds[k].args)
    for m in range(k + 1, len(cmds)):
        for op, _ in cmds[m].ops:
            if op == ";" and not closed:
                add([";"])
            elif op in ("(", ")"):
                open_ += 1 if op == "(" else -1
                if open_ < 0 and cmds[k].depth > 0:
                    return args
                open_ = max(open_, 0)   # 囲むサブシェルの無い所の閉じ括弧は、引用符で囲んだ字(`-name ')'`・`\)`)
                args.append(op)
            else:
                if (open_ > 0 or not closed) and any(WORD_RE.search(" ".join(c.args)) for c in cmds[m:]):
                    raise ValueError("find の式の括弧か -exec が開いたまま区切りが来て、find の引数を読み切れない")
                return args
        if not cmds[m].ops:
            break
        add(cmds[m].args)
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
    if hops == "parallel":
        lines = parallel_lines(words)
        if lines is not None:
            for line in lines:
                check_command(cr, line, here, depth + 1, files)
            return
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
    if hops == "parallel":
        args = parallel_words(args)
    if name in FIND:
        for run, in_place in find_execs(args):
            check_command(cr, shlex.join(run), None if in_place else here, depth + 1, files)
    if name in FD:
        # fd の -x・-X の後ろのコマンドは fd の cwd で走る(前は読まず、`fd foo -x rg y / {}` を通していた)
        for run in fd_split(args)[1]:
            if run:
                # 置き換えの印({}・{/}・{//}・{.}・{/.})の無いコマンドには、fd が終わりに {} を足す(見つけた物だけを渡す。前は
                # 足さずに読み、`fd . src -X rg TODO` をホームで打つと rg がホーム全体を探すと読んで止めていた)
                if not any(FD_PLACEHOLDER_RE.search(w) for w in run[1:]):
                    run = run + ["{}"]
                check_command(cr, shlex.join(run), here, depth + 1, files)
    piped = any(op == "|" for op, _ in c.ops)
    for start in starts_of(name, args, piped, hops):
        if "$" in start:
            start = files.var(start)
        check_path(name, start, here)


def before_scope(cr, cmds, k, files, bodies, inner, upto=None):
    """k 番目の eval・bash -c・殻の標準入力の中身 inner の変数を解く Scope。coldread の Scope は eval が在ると全部の変数を
    解かず、inner の中の引用(`bash -c 'find $D'`)や `\\$` の後の $ を字のままと見るが、eval と中の殻はそれも展開する。
    そこで k 番目をただの代入(前置の代入 `D=/ bash -c …` は中の殻の環境に入る)か : に替えた列で、inner の $ を生きた物として
    解く(前は `D=/; eval 'find $D'`・`export D=/; bash -c 'find $D'`・`D=/ bash -c 'find $D'` を通していた)。
    export しない代入も中の殻に渡ると見る(止める側に倒す)。upto が在れば、k 番目は代入だけのコマンドで、inner はその upto 番目の
    語の中の置換: 前の語(c.args[:upto])の代入だけを足す。"""
    c = cmds[k]
    stubs = []
    # 前置の語のうち代入だけ(`D=/ timeout 60 bash -c …`・`env D=/ sh -c …` の timeout・env は除く)
    prefix = c.args[:cr.command_start(c.args)] if upto is None else c.args[:upto]
    for args in ([a for a in prefix if cr.ENV_PREFIX_RE.match(a)], [":"]):
        if args:
            stubs.append(copy.copy(c))
            stubs[-1].args = args
            stubs[-1].redirects = []   # リダイレクト(`D=/ bash -c 'find $D' > log`)は代入の届き方を変えない
    line = cmds[:k] + stubs
    # 語は二重引用で包んで並べる(`echo "it's"` の ' で引用が割れ、どの変数も解けなくなるのを防ぐ。$ は生きたまま)
    live = "; ".join(" ".join('"%s"' % re.sub(r'(["\\`])', r"\\\1", a) for a in cc.args) for cc in line) + "; " + inner
    before = Scope(line, files.cwd, bodies, live).at(len(line) - 1, [])
    before.outer = files.outer
    return before


def parallel_words(words):
    """GNU parallel の後ろのコマンドの語。::: の後ろの値は、コマンドに {} が在ればそこに、無ければ後ろに足して走らせるので、
    ::: の印を除いて後ろに並べる(`parallel rg foo ::: / ~` は rg foo / と rg foo ~ を走らせる)。:::: の後ろは値を読むファイル
    なので、決まらない値の印 {} に替える。"""
    out, files = [], False
    for w in words:
        if w in (":::", ":::+", "::::", "::::+"):
            files = w.startswith("::::")
            if files:
                out.append("{}")   # ファイルから読む値(字面では決まらない)
        elif not files:
            out.append(w)
    return out


def parallel_lines(words):
    """GNU parallel が、後ろのコマンドを 1 語の文字列で渡されたとき(`parallel "rg foo {}" ::: /`)・シェルか eval に渡すとき
    (`parallel bash -c 'find {} -name x' ::: /`)・コマンドを持たないとき(`parallel ::: "find / -name x"`。値そのものを走らせる)に、
    シェルが走らせるコマンドの文字列の列(でなければ None)。parallel は ::: の後ろの値を {} に入れるか後ろに足し、シェルに
    渡して走らせる(前は 1 語のコマンドを名前と読み、どれも通していた)。:::: の後ろ(値を読むファイル)と標準入力の値は
    決まらないので {} のまま残す。値の組は PARALLEL_MAX 個までにし、超えたら値を 1 つずつ入れる。"""
    marks = (":::", ":::+", "::::", "::::+")
    cut = next((i for i, w in enumerate(words) if w in marks), len(words))
    cmd = words[:cut]
    if not (not cmd or len(cmd) == 1 and re.search(r"\s", cmd[0])
            or os.path.basename(cmd[0]) in SHELLS or os.path.basename(cmd[0]) == "eval"):
        return None
    template = cmd[0] if len(cmd) == 1 else shlex.join(cmd)
    groups, files = [], False
    for w in words[cut:]:
        if w in marks:
            files = w.startswith("::::")
            groups.append(["{}"] if files else [])
        elif not files:
            groups[-1].append(w)
    groups = [g for g in groups if g]
    if not groups:
        return [template] if template else []
    count = 1
    for g in groups:
        count *= len(g)
    combos = itertools.product(*groups) if count <= PARALLEL_MAX else [(v,) for g in groups for v in g]
    lines = []
    for combo in combos:
        values = " ".join(combo)
        lines.append(template.replace("{}", values) if "{}" in template else (template + " " + values).strip())
    return lines


def after_hop(words):
    """前置(words[0])の旗と、値を取る旗の値と、数を飛ばした残り。1 字の旗を束ねた語(`-0n 2`・`-kS host`)は、値を取る旗が
    語の終わりに在れば次の語を値に取る(語の途中に在れば残りの字が値)。"""
    values, i = HOPS[os.path.basename(words[0])], 1
    while i < len(words):
        w = words[i]
        if w in values:
            i += 2
        elif re.fullmatch(r"-[A-Za-z0-9]{2,}", w) and next(
                (k for k, c in enumerate(w[1:], 1) if "-" + c in values), None) == len(w) - 1:
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


def layout(cr, tokens, kinds=None, negs=None, braces=None):
    """単純コマンドごと(split_commands と同じ順)の (囲むブロックの道, 括弧の深さ, 直前の区切り((演算子, 深さ) の列), 語の頭)。
    split_commands と数が合わなければ None。kinds を渡せば、ブロックの番号 → 頭の語(if・while・for など)を書き込む。
    negs を渡せば、`!` で終わりの値を裏返したコマンドの番号 → True を書き込む(`if ! cd x`)。`!` の後に `{`・`(`・if・while・
    until・`!` が続くときは、裏返すのが中の 1 つのコマンドか分からないので、続く頭のコマンドに "?" を書き込む。braces を渡せば、
    `{ }` のまとまりの最初のコマンドの番号 → 閉じの `}` の番号を書き込む。

    道は外から順の (ブロックの番号, 区画の番号, 条件の区画か)。区画は if の条件・then・elif の条件・else、繰り返しの条件と do の後、
    case の ;; ごとに分ける。case の型の閉じ `a)` は括弧に数えない(coldread の深さはそこで負になり、cd が届くかを読み違える)。"""
    out, stack, ops, depth, cur, head, nid, neg, opened = [], [], [], 0, [], None, 0, None, []
    taken = ([], None)   # 今のコマンドの頭で取った前の区切りと `!`(`time` を捨てるときに戻す)

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
                # 行き先が、shlex が区切りに割ったプロセス置換(`< <(…)`)なら、split_commands と同じく `(` をサブシェルの開きに数える
                i += 1 if cr.procsub_split(tokens[i + 1:i + 2]) else 2
                continue
            close()
            if neg and "(" in tok:
                neg = "?"
            for op in cr._OP_RE.findall(tok):
                top = stack[-1] if stack else None
                if top and top[1] == "case" and top[4] and op in "()":
                    top[4] = op == "("   # 型の頭の ( と閉じの ): 括弧ではない
                    continue
                if op == ";;" and top and top[1] == "case":
                    top[2], top[4] = top[2] + 1, True
                if op == ")" and not depth:
                    continue   # 開いていない閉じ括弧は引用符で囲んだ字(`echo ')'`。トークン化で引用符が落ちる)。区切りでない
                if op == ")":
                    depth -= 1
                ops.append((op, depth))
                if op == "(":
                    depth += 1
            i += 1
            continue
        brk = cr.head_break(cur, tok)
        if brk == "time":
            # split_commands と同じく `time`・`time -p` を捨てて、後ろの予約語からをコマンドにする。`time` の頭で取った前の区切りと
            # `!` は後ろのコマンドに戻す(`[ -d x ] && time { cd x; }` の cd の前は &&)
            cur.clear()
            ops, neg = taken
            if negs is not None:
                negs.pop(len(out), None)
        elif brk == "function":
            close()   # `function f { …; }` の `function f` は 1 つのコマンド(`f() { …; }` と同じ)
        if not cur and tok in cr.RESERVED:
            top = stack[-1] if stack else None
            if tok == "{":
                opened.append(len(out))
            if tok == "!":
                neg = True if neg is None else "?"
            elif neg and tok in ("{", "if", "while", "until"):
                neg = "?"
            if tok in ("if", "while", "until"):
                nid += 1
                stack.append([nid, tok, 0, True, False])
                if kinds is not None:
                    kinds[nid] = tok
            elif top and tok in ("then", "do", "else"):
                top[2], top[3] = top[2] + 1, False
            elif top and tok == "elif":
                top[2], top[3] = top[2] + 1, True
            i += 1
            continue
        if not cur:
            head = (tuple((e[0], e[2], e[3]) for e in stack), depth, ops, tok)
            taken = (ops, neg)
            ops = []
            if neg and negs is not None:
                negs[len(out)] = neg
            neg = None
            if tok == "}" and opened:
                at = opened.pop()
                if braces is not None:
                    braces[at] = len(out)
            if tok in ("for", "select", "case"):
                nid += 1
                stack.append([nid, tok, 1 if tok == "case" else 0, False, tok == "case"])
                if kinds is not None:
                    kinds[nid] = tok
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
            self.kinds = {}   # ブロックの番号 → 頭の語
            self.negs = {}   # `!` で裏返したコマンドの番号 → True か "?"(layout)
            self.braces = {}   # `{ }` のまとまりの最初のコマンドの番号 → 閉じの `}` の番号(layout)
            # cwds_here の控え: (cd, k) → (届くか, 必ず走ったか)・(cd, 前の場所) → 行き先・繰り返しの番号 → 中のコマンド・回の頭の場所
            self._flow, self._dests, self._insides, self._tops = {}, {}, {}, {}
            self._passes, self._afters = {}, {}   # (繰り返し, 1 回目の頭の場所) → 回の頭の場所・(繰り返し, 場所, k) → 抜けた後の場所
            self._ends = {}   # 条件の中の cd の番号 → then・do の後ろのコマンドの番号(_then_end)
            self._units = {}   # cd の番号 → まとめて走る組の後ろのコマンドの番号(_unit_end)
            self._facts = {}   # cd の番号 → k に依らない届き方の控え(_fact)
            self._moves = {}   # (cd の番号, 前の場所だけが来るか, 前の場所の列) → 後の場所の列(_walk)
            self._cds = {m for m, c in enumerate(cmds) if any(t in cr.CD_WORDS for t in c.args)}
            self._via = False   # _surely の中で、cd が落ちた側が後ろの cd を飛ばして k に来ると見たか(_skips_pass)
            lay = layout(cr, tokens, self.kinds, self.negs, self.braces)
            self.lay = lay if lay is not None and len(lay) == len(cmds) else None

        def _reaches(self, j, k):
            """j 番目の cd の効果が k 番目に届くか(同じシェルの中か)。届かないのは、パイプの中・& で後ろに回した・
            サブシェル(`( … )`・`$( … )`)が k より前に閉じたとき。cd を囲む `{ }` のまとまりがパイプの中か & で後ろに回したとき
            も、まとまりは別のシェルで走るので、閉じの `}` より後ろには届かない(前は届くと見て、`{ cd proj; } | cat; rg x .` を
            ホームで打つと ~/proj で探すと読んで通していた)。"""
            cut, _, _, _, _ = self._fact(j)
            return cut > k and self.lay[k][1] >= self.lay[j][1]

        def _fact(self, j):
            """j 番目の cd の、後ろのコマンド(k)に依らない届き方の控え: (届かなくなる最初のコマンドの番号〔0 は、パイプの中か & で
            後ろに回して、どこにも届かない〕, 前の区切りが ; 改行 && だけか, 前の区切りに && が在るか, j より後ろで同じ深さ以浅に ; 改行 &
            が来る最初の番号, 同じ深さ以浅に || が来る番号の列)。届かなくなるのは、cd を囲む `{ }` のまとまりがパイプの中か & で後ろに
            回したときの閉じの `}` の次と、囲むサブシェル(`( … )`・`$( … )`)の閉じる所。cd ごとに 1 度だけ引く(前は _reaches・_surely の
            たびに k までを読み直し、長いスクリプトで cd の数 × コマンドの数 × コマンドの数の時間がかかっていた)。"""
            if j not in self._facts:
                _, d, ops, _ = self.lay[j]
                n = len(self.lay)
                cut = n
                if (any(op == "|" and dep == d for op, dep in ops)
                        or any(op in ("|", "&") and dep == d for op, dep in self.lay[j + 1][2])):
                    cut = 0
                for start, end in self.braces.items():
                    if start <= j < end < n - 1 and (
                            any(op == "|" and dep == self.lay[start][1] for op, dep in self.lay[start][2])
                            or any(op in ("|", "&") and dep == self.lay[end][1] for op, dep in self.lay[end + 1][2])):
                        cut = min(cut, end + 1)
                cut = min(cut, next((m for m in range(j + 1, n) if any(op == ")" and dep < d for op, dep in self.lay[m][2])), n))
                # cd を囲む `{ }` のまとまりは、頭の前の && || で全部が走るか決まるので、頭の前の区切りも cd の物と見る(前は見ず、
                # `[ -d proj ] && { echo found; cd proj; }; rg foo .` の cd を必ず走ると読み、ホームで打つと通していた)
                ops = list(ops) + [op for start, _ in self._groups(j) for op in self.lay[start][2]]
                plain = not any(op not in (";", "\n", "&&") for op, _ in ops if op not in "()")
                chained = any(op == "&&" for op, _ in ops)
                sep = next((m for m in range(j + 1, n) if any(op in (";", "\n", "&") and dep <= d for op, dep in self.lay[m][2])), n)
                ors = [m for m in range(j + 1, n) if any(op == "||" and dep <= d for op, dep in self.lay[m][2])]
                self._facts[j] = (cut, plain, chained, sep, ors)
            return self._facts[j]

        def _surely(self, j, k):
            """届く cd(j 番目)が、k 番目が走るときには必ず走ったか。前の区切りが ; 改行 && だけ(&& なら k までも && だけ)で、k までに || が無い
            (`cd x || exit 1`・繰り返しの中の `cd x || continue` のような逃げ口〔_escapes〕の || は除く)うえ、cd を囲むブロックがどれも
            k も囲むか、cd が if・elif・while・until の条件の中で、k が cd の移れたときにだけ走る所に在るとき(_by_condition)。"""
            path, d, _, _ = self.lay[j]
            _, plain, chained, sep, ors = self._fact(j)
            if not plain:
                return False
            kpath = self.lay[k][0]
            same = 0
            while same < min(len(path), len(kpath)) and path[same] == kpath[same]:
                same += 1
            rest = path[same:]
            # 条件の中の cd から、同じブロックの後ろの区画の k を見るときは、&& の繋がりを条件の終わりまでで見る(_by_condition。
            # `if [ -d x ] && cd x; then find .; fi` の then の前の ; は、条件が通ったときにだけ then へ進む)
            in_block = len(rest) == 1 and rest[0][2] and len(kpath) > same and kpath[same][0] == rest[0][0]
            if chained and not in_block and sep <= k:
                # `test -d sub && cd sub; find .` の cd は前が落ちると走らず、; の後ろの find はそれでも走る。&& の後の cd は、
                # k までが && だけで繋がる(同じ深さ以浅に ; 改行 & が無い)ときだけ必ず走った
                return False
            escape = self._escapes(j, k)
            # 逃げ口の中(cd が落ちたときにだけ走る)の || は除いて、k までに || が在れば必ず走ったとは限らない
            at = bisect.bisect_right(ors, j if escape is None else max(j, escape))
            if at < len(ors) and ors[at] <= k:
                return False
            if not rest:
                return True
            bid, sec, cond = rest[0]
            return len(rest) == 1 and cond and self._by_condition(j, k, bid, sec, same)

        def _by_condition(self, j, k, bid, sec, at):
            """ブロック bid(if・while・until)の区画 sec の条件の中の cd(j 番目。囲むブロックの道の at 番目が bid)が、k 番目の走る
            ときに必ず移れたか。条件の値が cd の値で決まるのは、cd の後ろが && だけで条件の終わりまで繋がる(条件が通れば cd は移れた)
            か、`!` で裏返した cd が条件の最後で、必ず走る(条件が落ちれば cd は移れた)とき。

            条件が通れば移れた cd は、then・while の do で必ず移れた。条件が落ちれば移れた cd(`if ! cd x`・`until ! cd x`)は、
            then より後ろの elif・else・until の do で必ず移れた。ブロックの後ろでは、cd が落ちたときに走る区画がシェルを抜ける
            (exit・return で終わるか、continue・break で k を飛ばす〔_exits〕)とき(`if ! cd x; then exit 1; fi`・`if cd x; then :; else exit 1; fi`)と、cd が移れるまで
            回る繰り返し(`until cd x; do …; done`・`while ! cd x; do …; done`。中に break が無い)の後ろで必ず移れた(前は条件の中の
            cd を then・do の中でだけ移れたと見て、これらの後ろの探すコマンドを止め、`if ! cd x; then find .; fi` の then を移れた
            後と見て通していた)。"""
            kind = self.kinds.get(bid)
            neg = self.negs.get(j)
            if kind not in ("if", "while", "until") or neg == "?":
                return False
            _, d, ops, _ = self.lay[j]
            inside = self._inside(bid)
            section = [m for m in inside if self.lay[m][0][at:at + 1] == ((bid, sec, True),)]
            tail = [m for m in section if m > j]
            # 条件が通れば移れた: 裏返さず、後ろが && だけで条件の終わりまで繋がる
            held = not neg and not any(op in (";", "\n", "&") and dep <= d for m in tail for op, dep in self.lay[m][2])
            # 条件が落ちれば移れた: 裏返して条件の最後に在り、必ず走る(前の && は、cd が条件の頭ならブロックの前の物)
            failed = neg is True and not tail and (section[0] == j or not any(op == "&&" for op, _ in ops))
            kpath = self.lay[k][0]
            if len(kpath) > at and kpath[at][0] == bid:   # k はこのブロックの中
                ksec = kpath[at][1]
                if kind == "if":
                    return held if ksec == sec + 1 else failed and ksec > sec + 1
                return ksec == 1 and (held if kind == "while" else failed)
            # k はブロックの後ろ。ブロックは必ず走り(前が && || でない)、パイプ・& の中でない
            end = inside[-1]
            if k <= end or any(op in ("&&", "||") and dep <= d for op, dep in self.lay[inside[0]][2]):
                return False
            if any(op in ("|", "&") and dep <= d for op, dep in self.lay[end + 1][2]):
                return False
            if kind == "if":
                if sec != 0:
                    return False   # 前の then を通った後ろにも来る
                if failed:
                    return self._exits(bid, 1, at, d, k)
                sections = {self.lay[m][0][at][1:] for m in inside}
                return held and sections == {(0, True), (1, False), (2, False)} and self._exits(bid, 2, at, d, k)
            if any(self.lay[m][3] == "break" for m in inside):
                return False
            return held if kind == "until" else failed

        def _exits(self, bid, sec, at, d, k):
            """ブロック bid の区画 sec が、必ずシェルを抜けるか、k 番目を走らせずに飛ばすか: その区画のじかの(入れ子のブロック・
            サブシェル・パイプ・&& || の中でない)exit・return か、k を飛ばす continue・break(_skips_pass)が在る(前は exit・return
            だけを見て、`for d in */; do if ! cd "$d"; then continue; fi; rg x .; cd ..; done` の cd を移れたと限らないと見て止めていた)。"""
            inside = self._inside(bid)
            for m in inside[:-1]:
                p, dep, ops, head = self.lay[m]
                if (len(p) == at + 1 and p[at] == (bid, sec, False) and dep == d
                        and (head in ("exit", "return") or self._skips_pass(m, k, [x for x in inside if x < m and
                                                                                   self.lay[x][0][at:at + 1] == p[at:]]))
                        and all(op in (";", "\n") for op, _ in ops)
                        and not any(op in ("|", "&") for op, _ in self.lay[m + 1][2])):
                    return True
            return False

        def _skips_pass(self, m, k, before):
            """m 番目のコマンドが continue・break(引数が無いか 1)で、cd が落ちたときに k を走らせないか(before は、cd が落ちたときに
            m の前に走るコマンドの番号の列)。continue はその繰り返しのこの回の残り、break は繰り返しの全部を飛ばすので、k が m を囲む
            いちばん内の繰り返しの中の、閉じの done より前に在るとき。k がその done(次の回の頭の場所を引くとき。_heads)なら、break は
            done に来させず、continue は cd の前の場所のまま done に来させる(_walk はそれを、移れた場所の列とは別に足す。self._via に
            印を付ける)。continue のこの形は、before に cd が在れば取らない(落ちた側の場所が cd の前の場所でなくなる)。"""
            if self.lay[m][3] not in ("continue", "break") or self.cmds[m].args[1:] not in ([], ["1"]):
                return False
            loop = self._loop_of(m)
            if loop is None:
                return False
            inside = self._inside(loop)
            if k in inside and k < inside[-1] or k == inside[-1] and self.lay[m][3] == "break":
                return True
            if k != inside[-1] or any(t in cr.CD_WORDS for x in before for t in self.cmds[x].args):
                return False
            self._via = True
            return True

        def _loop_of(self, m):
            """m 番目を囲むいちばん内の繰り返しの番号(無ければ None)。"""
            return next((bid for bid, _, _ in reversed(self.lay[m][0]) if self.kinds.get(bid) in LOOPS), None)

        def _escapes(self, j, k, leaves=("exit", "return")):
            """j 番目の cd の後ろの `|| <コマンド>`・`|| { …; <コマンド>; }` が、cd が落ちたときに k 番目を走らせない逃げ口なら、
            逃げ口の最後のコマンドの番号(でなければ None)。逃げ口は、exit・return(シェルを抜ける)と、continue・break(その繰り返しの
            この回の残り〔break は繰り返しの全部〕を飛ばす。_skips_pass)。
            `{ }` のまとまりは、最後のじかのコマンドが逃げ口なら逃げ口(前は exit・return だけを、`{ }` で囲まずに書いたときだけ見て、
            `for d in */; do cd "$d" || continue; rg x .; cd ..; done` の cd を走るとは限らないと見て、動かなかった場所からの `cd ..` で
            / やホームに届いたと読み、`cd proj || { echo no; exit 1; }; rg foo .` も止めていた)。サブシェルの中の exit
            (`|| ( exit 1 )`)はサブシェルを抜けるだけなので逃げ口でない。逃げ口の後ろが & やパイプなら、cd ごと別のシェルで走る。
            leaves は、逃げ口と見る最後のコマンドの頭の語(continue・break のほかに)。"""
            m = j + 1
            if m >= len(self.lay) or not any(op == "||" for op, _ in self.lay[m][2]):
                return None
            d = self.lay[j][1]
            end = self.braces.get(m)
            last = m if end is None else end - 1
            if end is not None and (self.lay[last][0] != self.lay[m][0] or self.lay[end][0] != self.lay[m][0]
                                    or any(op not in (";", "\n") for op, _ in self.lay[end][2])):
                return None
            stop = last if end is None else end
            if stop + 1 < len(self.lay) and any(op in ("|", "&") and dep <= d for op, dep in self.lay[stop + 1][2]):
                return None
            mpath, mdepth, ops, head = self.lay[last]
            ops = [op for op, _ in ops]
            if last == m:
                ops.remove("||")
            if mdepth != d or any(op not in (";", "\n") for op in ops) or k <= stop:
                return None
            return stop if head in leaves or self._skips_pass(last, k, range(m, last)) else None

        def cwds_here(self, k=None):
            """k 番目(既定は今のコマンド)が走りうる cwd の列(None は決まらない)。前の cd を順にたどる: 必ず走る cd は行き先、
            走るとは限らない cd(if・繰り返し・|| の中)は行き先と前の場所の両方、効果が届かない cd(サブシェル・パイプ)は
            前の場所のまま。行き先の読めない cd(`cd -`・`cd $X`)の行き先は決まらない(走るとは限らない cd なら前の場所も見る。
            前は `cd /; if [ -n "$X" ]; then cd "$X"; fi; find .` を通していた)。相対の行き先は、そこまでに
            決まった場所に繋ぐ(`cd .. && find .`)。

            k が繰り返し(for・while・until・select)の中なら、2 回目からは、前の回の終わりの場所から回の頭に戻って走る。そこで、
            回の頭の走りうる場所(_top)から、回の頭から k の前までの cd をたどった場所も足す(前は k より前の cd だけを見て、
            `for d in a b; do find .; cd ..; done` の 2 回目の find が 1 つ上で走るのを見落とした)。"""
            k = self.k if k is None else k
            if self.moved:
                return [None]
            return self._places(k)

        def _places(self, k, skip=None):
            """k 番目が走りうる cwd の列(cwds_here の中身)。繰り返しの番号 skip と、その中の繰り返しの 2 回目からは足さない
            (_top が skip の回の頭の 1 回目の場所を引くとき)。"""
            places = self._walk(range(k), [self.cwd], k)
            if not self.lay:
                return places
            for bid, _, _ in self.lay[k][0]:   # 外の繰り返しから順に
                if bid == skip:
                    break
                if self.kinds.get(bid) not in LOOPS:
                    continue
                top = self._top(bid)
                inside = self._inside(bid)
                places = _shallow(list(dict.fromkeys(places + self._walk([m for m in inside if m < k], top, k))))
            return places

        def _inside(self, bid):
            """番号 bid のブロックの中の単純コマンドの番号の列(最後は閉じの done。ブロックの道は閉じる前に取る)。"""
            if bid not in self._insides:
                self._insides[bid] = [m for m in range(len(self.cmds)) if any(e[0] == bid for e in self.lay[m][0])]
            return self._insides[bid]

        def _top(self, bid):
            """繰り返し bid の回の頭の、走りうる cwd の列(1 回目と、前の回の終わりから戻った 2 回目から)。回の中身の cd を、場所が
            増えなくなるまで繰り返してたどる。1 回で浅くなるのは .. の数だけなので、/ に届くまでの回数は、いちばん深い場所の区切りの
            数で足りる(絶対の行き先の cd は 1・2 回で増えなくなる)。前に落とした深い場所は、また出ても新しいと数えない(数えると
            増え続けて時間切れになる)。"""
            if bid not in self._tops:
                self._tops[bid] = self._heads(bid, self._places(self._inside(bid)[0], skip=bid))
            return self._tops[bid]

        def _heads(self, bid, places):
            """1 回目の回の頭の場所の列 places から、繰り返し bid の回の頭の走りうる cwd の列(_top の中身)。cd は場所ごとに
            別々に効くので、場所ごとに引いて控える(入れ子の繰り返しで、外の回ごとに中の繰り返しを引き直すと時間切れになる)。"""
            inside = self._inside(bid)
            out = []
            for place in places:
                if (bid, place) not in self._passes:
                    seen = [place]
                    ever, frontier = set(seen), seen
                    for _ in range(min(PLACES_MAX, 2 + (place or "").count("/"))):
                        SPENT["walks"] += len(inside)
                        if SPENT["walks"] > WALKS_MAX:
                            raise ValueError("繰り返しの入れ子の cd が多く、探す場所を読み切れない")
                        frontier = [p for p in self._walk(inside[:-1], frontier, inside[-1], bid) if p not in ever]
                        if not frontier:
                            break
                        ever.update(frontier)
                        seen = _shallow(seen + frontier)
                    self._passes[bid, place] = seen
                out += self._passes[bid, place]
            return _shallow(list(dict.fromkeys(out)))

        def _through(self, bid, places, k):
            """places から繰り返し bid に入り、抜けて k 番目に来るまでの場所の列。for・select は回の頭で抜けるので回の頭の走りうる
            場所(_heads)、while・until は回の頭から条件をたどった場所。中の cd が k に届かなければ(サブシェル・パイプの中)入る前の
            場所のまま。break・continue 2 などで回の途中から抜けうるときと、届き方が cd ごとに違うときは、回の頭から回の中身を、
            どの cd も走るとは限らないとしてたどる(途中で抜けた場所も入る)。"""
            inside = self._inside(bid)
            cds = [m for m in inside if any(t in cr.CD_WORDS for t in self.cmds[m].args)]
            reach = {self._reaches(m, k) for m in cds}
            if reach == {False}:
                return places
            out = []
            for place in places:
                if (bid, place, k) not in self._afters:
                    heads = self._heads(bid, [place])
                    if (reach != {True} or any(self.lay[m][3] == "break" or self.lay[m][3] == "continue"
                                               and self.cmds[m].args[1:] not in ([], ["1"]) for m in inside)):
                        after = self._walk(inside[:-1], heads, k, bid)
                    elif self.kinds.get(bid) in ("while", "until"):
                        after = self._walk([m for m in inside if (bid, 0, True) in self.lay[m][0]], heads, k, bid)
                    else:
                        after = heads
                    # 前の読み方(回の中身を 1 回だけ、どの cd も走るとは限らないとしてたどる)の場所も足す(if の中の cd と同じく、
                    # `for d in a b; do cd $d; make; cd ..; done; rg y .` を ~/src で止めるのは変えない)
                    after = after + self._walk(inside, [place], k, bid)
                    self._afters[bid, place, k] = _shallow(list(dict.fromkeys(after)))
                out += self._afters[bid, place, k]
            return _shallow(list(dict.fromkeys(out)))

        def _closed(self, j, k, within):
            """j 番目を囲む繰り返しのうち、繰り返し within(None は無し)の中で k より前に閉じる、いちばん外の物の番号(無ければ None)。"""
            path = [bid for bid, _, _ in self.lay[j][0]]
            path = path[path.index(within) + 1:] if within in path else path
            return next((bid for bid in path if self.kinds.get(bid) in LOOPS and self._inside(bid)[-1] < k), None)

        @staticmethod
        def _spend(steps):
            """_walk がたどった数を足し、1 つのコマンドの検査の全体で STEPS_MAX を超えたら読み切れないとして止める。"""
            SPENT["steps"] += steps
            if SPENT["steps"] > STEPS_MAX:
                raise ValueError("コマンドと cd が多く、探す場所を読み切れない")

        def _walk(self, js, places, k, within=None):
            """js の順の単純コマンドのうちの cd を、places から k 番目までたどった場所の列(届くか・必ず走ったかは k から見る)。
            k より前に閉じる繰り返しの中の cd は、回の頭の走りうる場所(_heads。回ごとに cd が重なる)から回の中身をたどった場所に
            する(_through。前は 1 回だけたどり、`for i in 1 2; do cd ..; done; find .` の 2 回目の cd .. を見落として通していた)。js が繰り返し
            within の中身なら、within そのものはまとめない。"""
            closed = -1   # 回の頭からまとめてたどった繰り返しの、閉じの done の番号
            passed = []   # cd が落ちて、後ろの cd を飛ばして k に来る場所
            stays = []    # 条件の中の cd が落ちて、then・do を飛ばす場所と、then・do の後ろのコマンドの番号の組の列(_then_end)
            entered = set()   # 入らなかった側の場所を stays に回した区画の道(後ろの cd の場所は、どれも区画に入った側の物)
            escape = -1   # 前の cd の逃げ口(_escapes)の最後のコマンドの番号。逃げ口の中の cd は k に届かない
            self._spend(len(js))
            for j in js:
                if stays and j >= stays[0][0]:
                    places = _shallow(list(dict.fromkeys(places + [p for r, p in stays if r <= j])))
                    stays = [(r, p) for r, p in stays if r > j]
                if j <= closed or j <= escape:
                    continue
                c = self.cmds[j]
                if (within is not None and self.lay[j][3] == "continue" and c.args[1:] in ([], ["1"])
                        and k == self._inside(within)[-1] and self._loop_of(j) == within):
                    passed += places   # この繰り返しの continue は、そこまでの場所のまま次の回の頭に来る(_heads)
                if j not in self._cds:
                    continue
                loop = self._closed(j, k, within) if self.lay else None
                if loop is not None:
                    places, closed = self._through(loop, places, k), self._inside(loop)[-1]
                    continue
                if (j, k) not in self._flow:
                    self._spend(STEP_COST)   # 届き方を k ごとに引く(_reaches・_surely・_escapes)
                    self._via = False
                    flow = (self._reaches(j, k), self._surely(j, k)) if self.lay else (True, False)
                    via = flow[1] and self._via
                    # 逃げ口(`cd x || { cd ..; exit 1; }`)は、cd が落ちたときに走って抜けるので、中の cd は k に来る場所を変えない
                    # (前は中の `cd ..` を移れた側の場所にも当て、`cd sub || { cd ..; exit 1; }; cd ../..; rg foo .` を止めていた)
                    # return で終わる逃げ口は除く: 関数の中では呼んだ所に戻って後ろが走り、関数の外では return が落ちて後ろが走る
                    # ので、中の cd は後ろに届く(前は除かず、`cd sub || { cd /; return 1; }; rg foo .` を通していた)
                    out = self._escapes(j, k, ("exit",)) if self.lay and flow[0] else None
                    self._flow[j, k] = flow + (via, -1 if out is None else out)
                reach, surely, via, out = self._flow[j, k]
                if not reach:
                    continue
                escape = max(escape, out)
                if via:
                    passed += places   # cd が落ちると、continue・break で後ろの cd を飛ばして k に来る(_skips_pass)
                end = None if surely else self._then_end(j)
                if end is not None:
                    path = self.lay[j][0]
                    entered.add(path[:-1] + ((path[-1][0], path[-1][1] + 1, False),))
                elif not surely:
                    end, key = self._unit_end(j)
                    if key in entered:
                        surely, end = True, None   # 区画に入った側の場所だけが来る: 区画のじかの cd は必ず走る
                    elif key is not None:
                        entered.add(key)
                if end is not None:
                    stays = sorted(stays + [(end, p) for p in places], key=lambda e: e[0])
                alone = surely or end is not None   # 落ちた側の場所は stays で then・do を飛ばす
                move = (j, alone, tuple(places))
                if move in self._moves:
                    # 同じ cd を同じ場所の列から引くのは、後ろのコマンド(k)ごとに頭からたどり直すときに繰り返す。控えから引き、
                    # 列を写す分だけ数える(前は毎回場所ごとに引き直し、長いスクリプトで、読む字の上限より先にたどる数の上限に当たった)
                    self._spend(len(places))
                    places = list(self._moves[move])
                    continue
                self._spend(STEP_COST * len(places))
                new = []
                for place in places:
                    if (j, place) not in self._dests:
                        if len(self._dests) >= DESTS_MAX:
                            raise ValueError("繰り返しの中の cd が多く、探す場所を読み切れない")
                        dest = self.cd_dest(c.args[cr.command_start(c.args):], place)
                        self._dests[j, place] = cr.native_path(dest) if dest else None
                    dest = self._dests[j, place]
                    if not (dest and os.path.isabs(dest)):
                        new += [None] if alone else [None, place]
                    else:
                        new += [dest] if alone else [dest, place]
                places = _shallow(list(dict.fromkeys(new)))
                self._moves[move] = tuple(places)
            # then・do を飛ばした場所は、k が then・do の後ろなら k に来る(k が then・do の中なら、cd が移れたときにだけ走る)
            passed += [p for r, p in stays if r <= k]
            return _shallow(list(dict.fromkeys(places + passed))) if passed else places

        def _then_end(self, j):
            """j 番目の cd が if・elif・while の条件の最後のコマンドで、then・do が cd の移れたときにだけ走るなら、then・do の後ろの
            コマンドの番号(でなければ None)。cd の前が || でなく(`a || cd x` の条件は cd が走らずに通る)、裏返さない(`!`)とき。
            _walk は、cd が落ちた側の場所を then・do の中の cd に通さず、then・do の後ろに足す(前は落ちた側の場所にも then の
            `cd ..` を当て、`if cd sub; then make; cd ..; fi; rg bar .` を ~/src で打つとホームに届いたと読んで止めていた)。"""
            if j not in self._ends:
                self._ends[j] = None
                path, d, ops, _ = self.lay[j]
                if path and path[-1][2] and self.kinds.get(path[-1][0]) in ("if", "while") and not self.negs.get(j):
                    bid, sec, _ = path[-1]
                    at = len(path) - 1
                    inside = self._inside(bid)
                    cond = [m for m in inside if len(self.lay[m][0]) > at and self.lay[m][0][at] == (bid, sec, True)]
                    body = [m for m in inside if len(self.lay[m][0]) > at and self.lay[m][0][at] == (bid, sec + 1, False)]
                    if (cond[-1] == j and body and (j == cond[0] or all(op in (";", "\n", "&&") for op, _ in ops))
                            and all(op in (";", "\n") for op, _ in self.lay[j + 1][2]) and self.lay[j + 1][1] == d):
                        self._ends[j] = body[-1] + 1
            return self._ends[j]

        def _groups(self, j, own=False):
            """j 番目を囲む `{ }` のまとまりの (頭のコマンドの番号, 閉じの } の番号) の列(内から順)。j が頭のまとまりは、own の
            ときだけ入れる。"""
            return sorted(((start, end) for start, end in self.braces.items() if (start <= j if own else start < j) and j < end),
                          reverse=True)

        def _unit_end(self, j):
            """j 番目の cd が、まとめて走るか走らない組(if の then・elif・else の区画と、&& の繋がり)の中に在り、組が走れば必ず
            走るなら、(組の後ろのコマンドの番号, 区画の組なら区画の道) (でなければ (None, None))。区画の組は、cd が区画のじかのコマンドで、区画の頭から cd までが
            ; 改行だけで繋がり、cd の後ろが || でないとき。&& の組は、cd の前が && のときで、組は cd の後ろの && だけで繋がる所まで。
            _walk は _then_end と同じく、組に入らなかった側の場所を組の中の後ろの cd に通さず、組の後ろに足す(前は入らなかった側の
            場所にも組の後ろの `cd ..` を当て、`for d in a b; do if [ -d build ]; then cd build; make; cd ..; fi; done; rg x .` を、回ごとに
            1 つずつ上がって / に届いたと読んで止めていた)。区画の 2 つ目からの cd(と、条件の cd が移れたときに入る then の cd)には、
            区画に入った側の場所だけが来るので、_walk は必ず走ると見る。繰り返しの do の後の区画は組にしない(回ごとに重ねてたどる。_heads)。
            && の後ろの `{ }` のまとまりは 1 つのコマンドと見て、まとまりの頭から ; 改行だけで繋がる cd を同じ組に入れ、まとまりの
            印を区画の道の代わりに返す(2 つ目からの cd は、区画と同じく必ず走ると見る)。"""
            if j not in self._units:
                self._units[j] = (None, None)
                path, d, ops, _ = self.lay[j]
                after = self.lay[j + 1][2] if j + 1 < len(self.lay) else []
                if any(op == "||" and dep <= d for op, dep in after):
                    return self._units[j]   # cd が落ちても後ろが走る
                # cd がまとまり(`{ }`)の頭か、頭から ; 改行だけで繋がる所に在れば、まとまりを 1 つのコマンドと見て、頭の前の && と
                # 閉じの } の後ろの && の繋がりまでを組にする(前は cd の前の区切りだけを見て、`[ -d build ] && { cd build; make; cd ..; }`
                # の組を make の前で切り、入らなかった場所にも cd .. を当てていた)
                head, scan, key = j, j + 1, None
                for start, end in self._groups(j, True):
                    # cd がまとまりのじかのコマンドでなければ(if・case・サブシェルの中)、まとまりが走っても走るとは限らない。じかか
                    # は閉じの } と道・深さが同じかで見る(頭のコマンドは if の条件の中のこともある)。前は見ず、`true && { cd ..;
                    # if [ -d build ]; then cd build; fi; }; rg foo .` の if の中の cd もまとまりの組に入れて必ず走ると読み、~/src で通していた
                    if self.lay[end][0] != path or self.lay[end][1] != d:
                        break
                    if start < head and (any(op not in (";", "\n", "(", ")") for m in range(start + 1, head + 1)
                                             if self.lay[m][0] == path and self.lay[m][1] == d for op, _ in self.lay[m][2])
                                         or any(self.lay[m][3] in ("break", "continue", "return") for m in range(start, head))):
                        break
                    head, scan, key = start, end + 1, ("{", start)
                    if scan < len(self.lay) and any(op == "||" and dep <= d for op, dep in self.lay[scan][2]):
                        return self._units[j]   # まとまりが落ちても後ろが走る
                plain = [(op, dep) for op, dep in self.lay[head][2] if op not in "()"]
                if plain and all(op == "&&" and dep == d for op, dep in plain):
                    for m in range(scan, len(self.lay)):
                        if len(self.lay[m][0]) <= len(path) and any(
                                op not in ("&&", "(", ")") and dep <= d or op == ")" and dep < d
                                for op, dep in self.lay[m][2]):
                            self._units[j] = (m, key)
                            break
                    else:
                        self._units[j] = (len(self.lay), key)   # 組がコマンドの終わりまで続く(`a && { b; cd x; rg y .; }`)
                elif path and not path[-1][2] and self.kinds.get(path[-1][0]) == "if":
                    inside = [m for m in self._inside(path[-1][0]) if self.lay[m][0] == path]
                    # 区画の中で cd より前に break・continue・return が在れば(入れ子の中も)、区画に入った場所が cd の前で抜けて
                    # 後ろに来る(前は組と見て後ろの cd を必ず走ると読み、`for i in 1 2; do if true; then cd ..; if [ -f .zshrc ]; then
                    # break; fi; cd src; fi; done; rg foo .` を ~/src で通していた)。exit はシェルを抜けるので後ろに来ない
                    jumps = any(self.lay[m][3] in ("break", "continue", "return") for m in self._inside(path[-1][0])
                                if m < j and self.lay[m][0][:len(path)] == path)
                    if not jumps and all(op in (";", "\n", "(", ")") for m in inside if m <= j and self.lay[m][1] == d
                                         for op, _ in self.lay[m][2]):
                        self._units[j] = (inside[-1] + 1, path)
            return self._units[j]

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
PARALLEL_MAX = 64   # parallel の ::: の値の組を、組ごとに入れて見る数の上限(parallel_lines)
LOOPS = {"for", "select", "while", "until"}
# 1 つのコマンドで、繰り返しの回の中身をたどったコマンドの数(_heads)と、cd の行き先を場所ごとに引く数(_walk)の上限。超えたら読み切れないと
# して止める(入れ子の繰り返しの cd で場所が増え続けると掛け算で増え、時間切れは通す。5 重の `for …; do cd d; done` で 38 万・1.3 秒。
# 上限で止めるまで 1.5 秒ほど)
WALKS_MAX = 400000
DESTS_MAX = 200000
# 1 つのコマンドの検査で、$( )・bash -c・eval などの中身を読み直した字の数(1 回ごとに READ_COST を足す。reads)と、_walk が
# たどったコマンドの数(cd では場所 1 つごとに STEP_COST を足す。steps)の上限。超えたら読み切れないとして止める。中身は外の
# コマンドの走りうる cwd ごとに読み直すので、入れ子の $( ) ごとに掛け算で増える(7 段の `[ -d a ] && cd a; … echo $(…)` で 2 分。
# 時間切れは通す)。集めたコマンド(3 万 4 千本)で最も多いのは reads が 2 千 3 百・steps が 1 千 7 百ほど。上限で止めるまで
# reads は 1 秒・steps は 5 秒ほど(steps は、cd の無い 7 千ほどのコマンドを並べた 1 本で上限に当たる)
READS_MAX = 3000000
READ_COST = 200
STEPS_MAX = 25000000
STEP_COST = 20
# 読んだ数(reads・steps と、回の中身をたどった数 walks〔_heads で、上の WALKS_MAX まで〕)。中身を読み直すたびに Scope が新しく
# 作られるので、1 つのコマンドの検査の全体で数える(前は walks を Scope ごとに数え、入れ子の $( ) ごとに上限が新しくなっていた)。
# 外の検査(check_command の depth 0)の頭で 0 に戻す
SPENT = {"reads": 0, "walks": 0, "steps": 0}


def _shallow(places):
    """場所の列を PLACES_MAX 個までにする。走るとは限らない cd が続くと場所は倍々に増える(20 個で時間切れになり、時間切れは
    通す)。広い場所は浅いので、浅い物から残す。"""
    if len(places) <= PLACES_MAX:
        return places
    return sorted(places, key=lambda p: len(p or ""))[:PLACES_MAX]


if __name__ == "__main__":
    gate_shell.run(main, lambda why: "searchgate: 探す起点の検査自体に失敗した(%s)。" % why)
