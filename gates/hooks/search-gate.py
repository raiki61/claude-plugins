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
import json
import os
import posixpath
import re
import sys

# `sys.path[0]` に頼らない(coldread-gate.py が claude_auth を読むのと同じ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_shell  # noqa: E402

FIND = {"find", "bfs", "gfind"}
GREP = {"grep", "egrep", "fgrep", "ggrep"}
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
# grep は再帰の旗の在るときだけ読む(`| grep foo` のたびに解析部を読み込まない)
WORD_RE = re.compile(r"(?<![\w.-])(?:find|bfs|gfind|fd|fdfind|rg)(?![\w.-])"
                     r"|(?<![\w.-])(?:e?grep|fgrep|ggrep)(?![\w.-]).*?(?:\s-[A-Za-z]*[rRd]|--recursive|--dereference-recursive"
                     r"|--directories)", re.S)
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


def expand_home(value):
    """~・~/…・$HOME・${HOME} をホームに置き換える(Bash のシェルと同じ利用者・同じ HOME で起動されるので)。"""
    h = home().rstrip("/") or "/"
    if value == "~" or value.startswith("~/"):
        value = h + value[1:]
    return re.sub(r"\$(?:\{HOME\}|HOME(?![A-Za-z0-9_]))", lambda m: h, value)


def substitutions(text):
    """引用の単一の外にある $( … ) と ` … ` の中身。二重引用の中も読む(シェルが展開する)。"""
    out, i, quote, n = [], 0, None, len(text)
    while i < n:
        c = text[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == "\\":
            i += 1
        elif c == "'" and quote is None:
            quote = "'"
        elif c == '"':
            quote = None if quote == '"' else '"'
        elif text.startswith("$(", i) and not text.startswith("$((", i):
            depth, j = 1, i + 2
            while j < n and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
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


def find_starts(args):
    """find・bfs・gfind の起点。前の旗(-H -L -P -E -X -d -s -x -O3 -j8・値を取る -D -S・BSD の -f <起点>)の後、
    式(- か ( か ! で始まる語)の前までの語。起点が無ければ . (GNU と bfs の既定)。"""
    starts, i = [], 0
    while i < len(args) and args[i].startswith("-") and args[i] != "-":
        a = args[i]
        if a in ("-D", "-S", "-f"):
            if a == "-f" and i + 1 < len(args):
                starts.append(args[i + 1])
            i += 2
        elif re.fullmatch(r"-[HLPEXdsx]+|-O\d*|-j\d+", a):
            i += 1
        else:
            break
    while i < len(args) and not args[i].startswith(("-", "(", "!", ")")):
        starts.append(args[i])
        i += 1
    return starts or ["."]


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
             "--devices", "--include", "--exclude", "--exclude-dir", "--exclude-from", "--label", "--binary-files"}


def starts_of(name, args, piped):
    """ツール name の引数 args から起点を返す。探さない形(grep の再帰でない・stdin を読む)なら []。

    piped は前がパイプのとき(rg・grep は起点の無いとき stdin を読み、cwd を探さない)。"""
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
        recursive = any(o in ("-r", "-R", "--recursive", "--dereference-recursive") for o, _ in opts) or any(
            o in ("-d", "--directories") and v == "recurse" for o, v in opts)
        if not recursive:
            return []
        given = any(o in ("-e", "--regexp", "-f", "--file") for o, _ in opts)
        paths = pos if given else pos[1:]
        return paths or ([] if piped else ["."])
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


def check_command(cr, command, cwd, depth=0):
    """Bash のコマンド 1 本を見る。止める起点が在れば Hit を投げる。"""
    if depth > MAX_DEPTH or not command.strip():
        return
    text, _ = cr.prepare(command)
    tokens = cr.tokenize(text)
    if tokens is None:
        # 引用が閉じないなどで読めない: 素の find / だけは字面で拾う(シェルもたいてい走らせないが、落とすと黙って通る)
        m = re.search(r"(?:^|[\s;&|(`])(?:find|bfs|gfind)\s+(?:-[HLP]\s+)*(\S+)", text)
        if m:
            check_path(m.group(0).split()[0].lstrip(";&|(`"), m.group(1).strip("'\""), cwd)
        return
    cmds = cr.split_commands(tokens)
    files = Scope(cmds, cwd, [], text, tokens)
    for k, c in enumerate(cmds):
        at = cr.command_start(c.args)
        words = c.args[at:]
        while words and os.path.basename(words[0]) in HOPS:
            words = after_hop(words)   # 前置を越える(nice -n 19 find …・xargs -0 rg …)
        if not words or ("command" in c.args[:at] and {"-v", "-V"} & set(c.args[:at])):
            continue   # command -v rg は在るかを引くだけ
        name = os.path.basename(words[0])
        here = files.at(k, c.args[:at]).cwd_here()
        if name in SHELLS:
            script = shell_script(words[1:])
            if script is not None:
                check_command(cr, script, here, depth + 1)
            continue
        if name == "eval":
            check_command(cr, " ".join(words[1:]), here, depth + 1)
            continue
        piped = any(op == "|" for op, _ in c.ops)
        for start in starts_of(name, words[1:], piped):
            check_path(name, files.var(start) if "$" in start else start, here)
    for inner in substitutions(text):
        check_command(cr, inner, cwd, depth + 1)


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
        if not WORD_RE.search(command):
            return   # 探すツールの語が無い(bash -c・eval・$( ) の中も字としては同じ文字列に在る)
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


def load_coldread():
    cr = gate_shell.load_coldread()
    global Scope

    class Scope(cr.BodyFiles):
        """変数と cd の追い方は coldread と同じ 1 本。~ と $HOME だけ先にホームへ開く(coldread は本文のパスでしか開かない)。"""

        def assigned(self):
            if self._assigned is None:
                table = super().assigned()
                if "HOME" not in table:   # 代入の値の中の ~・$HOME も開く(D=$HOME; find $D)
                    self._assigned = {n: v and (expand_home(v[0]), v[1]) for n, v in table.items()}
            return self._assigned

        def var(self, value):
            if "HOME" not in self.assigned():
                value = expand_home(value)
            return super().var(value)

        # coldread の cwd_here と同じ読み方に、2 つを足す: ; と改行の後の cd も読む(coldread は本文のパスを取り違えない
        # ように && の後だけ)・引数の無い cd はホーム
        CD_BETWEEN = cr._SEQUENTIAL

        def cd_dest(self, args):
            return home() if args == ["cd"] else super().cd_dest(args)

    return cr


Scope = None


if __name__ == "__main__":
    gate_shell.run(main, lambda why: "searchgate: 探す起点の検査自体に失敗した(%s)。" % why)
