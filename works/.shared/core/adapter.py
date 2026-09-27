"""Claude の包み（同じ置き場の claude-adapter）の芯。argv の読み・設定のマージ・印・会話の id の置き場・柵・止め方。

Archon は Claude Code の実行ファイルを `assistants.claude.claudeBinaryPath`（設定）か `CLAUDE_BIN_PATH`（env）で
差し替えられる。そこに claude-adapter を置くと、Archon の SDK が組んだ argv がこちらに来る。包みは argv だけを見て
（標準入出力は中継せずに子へ継がせる）下の 1〜3 と 5 を足し、本物の claude を 4 の形で起こす。形は有料の試しで
本物の Archon v0.11.1・SDK 0.3.282・claude 2.1.283 と確かめた（scratchpad の claude-adapter-probe.md・
resume-probe-summary.md・probes-p14-p15-summary.md・trackB-probes-wave2.md の P6e）。

1. **Read のフック**: `--settings` の JSON に PostToolUse:Read のフック（同じ置き場の record-read.py）を足す。
   SDK は sandbox を持つ節にだけ `--settings {"sandbox":{…}}` を付けるので、在ればマージ（SDK の鍵は上書きしない）、
   無ければフックだけの `--settings` を足す。`--setting-sources`（SDK は `=` でつないで必ず渡す）と `--model` は触らない。
   CLAUDE.md を止めるのは YAML の `settingSources: []` の役目（Archon の検証と実際を食い違わせない）。
2. **会話の継ぎ**: 役の節の output_format（JSON Schema）の一番上の `description` に置いた印
   `works-node: <節の名>[ continue=<継ぐ節の名>][ <旗>…]` を、SDK がそのまま載せる argv の `--json-schema` から読む
   （指示文は claude が initialize に答えるまで stdin に来ないので、起動の前には読めない）。
   - 印あり・continue なし: SDK が付けた `--resume`／`--session-id` の id を、無ければ包みが作った uuid を
     `--session-id=<uuid>` で足して、`sessions/<cwd の hash>/<節の名>.id` に記録する。SDK が `--fork-session` で
     継ぐ時は新しい会話の id を SDK が知らせないので、包みが `--session-id=<uuid>` を足して決める
   - continue=X: SDK が付けた会話の旗（`--resume`・`-r`・`--session-id`・`--fork-session`・`--continue`・`-c`）を外し、
     `--resume <X の id>` を足す（fork しない。同じ会話に積む）。X の id が無い・読めない時は子を起こさず止まる
     （fail closed）。YAML の節は `context: fresh` にして Archon 自身には何も継がせない

3. **起動ごとの柵**（切符が在る起動だけ）: 線の `start` が書く切符（ticket.py。`<家>/tickets/<key>.json` の
   `protected`）に、起動の時に引き直す 2 つ——この起動の env の `CLAUDE_CONFIG_DIR` と、`git worktree list` の今の
   worktree（切符の後に切られた物。役の cwd の worktree 自身は除く）——を足し、どれも /var と /private/var・/tmp と
   /private/tmp の両方の綴りにして、`permissions.deny` に `Edit(//<場所>)`・`Edit(//<場所>/**)`・`Write(…)` を足す。
   SDK が sandbox の塊を渡した起動だけ `sandbox.filesystem.denyWrite` にも足す（sandbox の無い節に sandbox の鍵を作らない）。
   どちらも SDK の配列の後ろに足し、SDK の項目は消さない。

4. **木ごと止める**: 本物の claude は exec せずに子として新しいセッションで起こし（標準入出力は継ぐ）、走っている間
   POLL 秒ごとに子孫（ppid を辿る）の pid とプロセスグループを覚える。claude の Bash の道具はコマンドを claude と別の
   グループで走らせるので、claude のグループへ送るだけでは孫に届かない（試し P15: SIGTERM を無視する孫が Ctrl-C でも
   cancel でも残った）。SIGINT・SIGTERM・SIGHUP を受けた時（か直下の親が替わった時）と claude が終わった後に、覚えた
   仲間のうちまだ居る物のグループ全部へ TERM → KILL_GRACE（2 秒）→ KILL を送る。信号で止めた時は LINGER（1 秒）待って
   から 128+信号で抜ける（すぐ死ぬと Archon の run が running のまま固まる。試し P17）。上限は 0.2 + 2 + 1 秒余りで、
   Archon の cancel の猶予 5 秒より前。限界: 2 回の見回りの間に生まれて孤児になった物は拾えない
5. **印 no-post**（並行 PR の任せ先の役）: permissions.deny に gh の書き込みの語（NO_POST_DENY）を足す（切符に依らない）。

印の無い起動（Archon の題の生成＝`--tools ""` の起動など）は argv を 1 バイトも変えない。見分けられない形
（`--json-schema` や `--settings` が 2 つ・読めない JSON・値の無い旗）は足さずに素通しし、警告を 1 行出す。
ただし印が読めて `--settings` だけが見分けられない時も、会話の継ぎは行う（継がずに再審すると黙って別の目になる）。
印の跡（`works-node:`）が在るのに読めない起動（知らない旗・大文字・余分な空白・印を持つ --json-schema が 2 つ など）は
素通しせず、claude を起こさずに 1 行を出して止まる（黙って新しい会話で再審させず、no-post の柵を落とさない）。

置き場（包みの家）は env の `WORKS_ADAPTER_HOME`（無ければ `${XDG_STATE_HOME:-~/.local/state}/works/adapter`。切符と同じ）。Claude の子の env には
ARTIFACTS_DIR が来ないので、run の区別は cwd（Archon が run ごとに切る worktree）の realpath の sha256 の先頭 16 字で付ける:
`sessions/<key>/<節>.id`・`reads/<key>/reads.jsonl`（graphloops の engine の hook_evidence がそのまま読む形）・
`launches/<key>.jsonl`（起動ごとの 1 行。引数の本文は書かない）。家は役の sandbox の Bash から書けない場所に置く。

Python 3.9 でも動く形で書く（`#!/usr/bin/env python3` が macOS の /usr/bin/python3 に当たりうる）。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import re
import shlex
import signal
import subprocess
import time
import uuid
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

import tree_run

ENV_HOME = "WORKS_ADAPTER_HOME"
ENV_REAL = "WORKS_REAL_CLAUDE"
MARK_PREFIX = "works-node:"

# continue=X の節で外す SDK の会話の旗。値を持つ物と持たない物
SESSION_VALUE_FLAGS = ("--resume", "-r", "--session-id")
SESSION_BARE_FLAGS = ("--fork-session", "--continue", "-c")

_NAME_RE = re.compile(r"[a-z0-9-]+")   # node_marker._NAME と同じ
FLAGS = ("no-post",)                   # node_marker.FLAGS と同じ。no-post: gh の書き込みの語を柵に足す（仕様 3.8）
# no-post の起動の permissions.deny に足す gh の書き込みの語（計画 Task 5 の NO_POST_DENY）
NO_POST_DENY = ("Bash(gh pr comment:*)", "Bash(gh pr review:*)", "Bash(gh pr edit:*)", "Bash(gh pr create:*)",
                "Bash(gh pr close:*)", "Bash(gh pr merge:*)", "Bash(gh issue comment:*)", "Bash(gh issue create:*)",
                "Bash(gh api -X:*)", "Bash(gh api --method:*)")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


class Unrecognised(Exception):
    """argv の形が見分けられない（足さずに素通しする）"""


class BadMarker(Unrecognised):
    """印の跡が在るのに読めない（claude を起こさずに止める。fail closed）"""


class Marker(NamedTuple):
    name: str
    cont: Optional[str]
    flags: Tuple[str, ...]


class Plan(NamedTuple):
    argv: List[str]                 # 子に渡す argv（本物の claude の名は含まない）
    mode: str                       # "merged"（フックを足した）| "passthrough"（足さない）| "refused"（子を起こさない）
    why: Optional[str]              # passthrough・refused の理由
    warn: bool                      # stderr に警告を出すか（印の無い素通しは普段の形なので出さない）
    node: Optional[str]
    cont: Optional[str]
    hook: bool
    tools_empty: bool               # `--tools ""`（題の生成か、道具を持たない役）
    session: Optional[dict]         # {mode: new|sdk-resume|sdk-session|sdk-fork|continued|refused, id, of?, from?}
    record: List[Tuple[pathlib.Path, str]]   # 子を起こす前に書く (id のファイル, id)
    fence: Optional[dict] = None    # {deny_write, permissions_deny}（フックを足した起動だけ）


def marker_text(name: str, cont: Optional[str] = None, flags: Sequence[str] = ()) -> str:
    """output_format の description に置く印の 1 行（node_marker.mark の description と同じ）"""
    parts = [MARK_PREFIX, name] + ([f"continue={cont}"] if cont else []) + list(flags)
    return " ".join(parts)


def parse_marker(description) -> Optional[Marker]:
    """description が印なら Marker、印の頭（`works-node:`）を持たなければ None。
    頭を持つのに読めなければ BadMarker（包みは claude を起こさない）。文法は枝 wip/works-a2 の node_marker.parse と同じ:
    `works-node: <名>[ continue=<名>][ <flag>…]`、名は [a-z0-9-]+、区切りは空白 1 つ、flag は FLAGS に在る物を 1 度ずつ"""
    if not isinstance(description, str) or not description.startswith(MARK_PREFIX):
        return None
    bad = BadMarker(f"節の印が読めない: {description!r}")
    if not description.startswith(MARK_PREFIX + " "):
        raise bad
    words = description[len(MARK_PREFIX) + 1:].split(" ")
    if not _NAME_RE.fullmatch(words[0]):
        raise bad
    cont, flags = None, []
    for w in words[1:]:
        if w.startswith("continue="):
            if cont is not None or not _NAME_RE.fullmatch(w[len("continue="):]):
                raise bad
            cont = w[len("continue="):]
        elif w in FLAGS and w not in flags:
            flags.append(w)
        else:
            raise bad
    return Marker(words[0], cont, tuple(flags))


def find_opt(argv: Sequence[str], name: str) -> List[Tuple[int, int, str, bool]]:
    """argv の中の `name v` と `name=v` の全部を (位置, 語の数, 値, = でつないだか) で返す。値の無い旗は Unrecognised"""
    out = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == name:
            if i + 1 >= len(argv):
                raise Unrecognised(f"{name} に値が無い")
            out.append((i, 2, argv[i + 1], False))
            i += 2
            continue
        if a.startswith(name + "="):
            out.append((i, 1, a[len(name) + 1:], True))
        i += 1
    return out


def marker_from_argv(argv: Sequence[str]) -> Optional[Marker]:
    """argv の --json-schema から印を読む。無ければ None。見分けられない形は Unrecognised（素通し）、
    印の跡（`works-node:`）が在るのに読めなければ BadMarker（止める。黙って新しい会話で再審させない）"""
    try:
        found = find_opt(argv, "--json-schema")
    except Unrecognised:
        raise Unrecognised("--json-schema に値が無い") from None
    if not found:
        return None
    if len(found) > 1:
        if any(MARK_PREFIX in v for _, _, v, _ in found):
            raise BadMarker("--json-schema が 2 つ以上あり、印を持つ")
        raise Unrecognised("--json-schema が 2 つ以上")
    text = found[0][2]
    try:
        schema = json.loads(text)
    except ValueError:
        schema = None
    if not isinstance(schema, dict):
        if MARK_PREFIX in text:
            raise BadMarker("--json-schema が JSON の object として読めないのに印の跡を持つ")
        raise Unrecognised("--json-schema が JSON の object として読めない")
    return parse_marker(schema.get("description"))


def home(env=None) -> pathlib.Path:
    """包みの家: ${WORKS_ADAPTER_HOME:-${XDG_STATE_HOME:-$HOME/.local/state}/works/adapter}（ticket.home と同じ。空は無いと同じ）"""
    env = os.environ if env is None else env
    if env.get(ENV_HOME):
        return pathlib.Path(env[ENV_HOME])
    state = env.get("XDG_STATE_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "state")
    return pathlib.Path(state) / "works" / "adapter"


def cwd_key(cwd) -> str:
    return hashlib.sha256(os.path.realpath(str(cwd)).encode("utf-8")).hexdigest()[:16]


def _home_or(home_dir) -> pathlib.Path:
    return home() if home_dir is None else pathlib.Path(home_dir)


def session_path(cwd, node: str, home_dir=None) -> pathlib.Path:
    """節 node が cwd（run の worktree）で使った会話の id のファイル。home_dir を省くと env の家。
    再審の前の確かめ（rejudge の session_ready）も同じ関数で引く"""
    return _home_or(home_dir) / "sessions" / cwd_key(cwd) / f"{node}.id"


def reads_dir(cwd, home_dir=None) -> pathlib.Path:
    """Read のフックが reads.jsonl を書く置き場（engine の hook_evidence の board_dir にそのまま渡せる）"""
    return _home_or(home_dir) / "reads" / cwd_key(cwd)


def launches_path(cwd, home_dir=None) -> pathlib.Path:
    """cwd の起動の記録（1 起動 1 行。launch_row の形）"""
    return _home_or(home_dir) / "launches" / f"{cwd_key(cwd)}.jsonl"


def now() -> str:
    """launches の `at`。盤面の state.created（engine の util.now）と同じ、時差つきの ISO 8601（こちらは μ 秒まで）"""
    return datetime.datetime.now().astimezone().isoformat(timespec="microseconds")


def launch_row(p: "Plan", cwd, pid: int, at: str) -> dict:
    """launches の 1 行。引数の本文は書かない。
    `session` は {mode, id, of?, from?}: mode は new・sdk-resume・sdk-session・sdk-fork・continued・refused。
    `from` は既に在る会話を開いた起動（sdk-resume・sdk-fork・continued）の元の会話の id（sdk-fork だけ id と違う）"""
    return {"at": at, "pid": pid, "cwd": os.path.realpath(str(cwd)), "node": p.node, "continue": p.cont,
            "mode": p.mode, "why": p.why, "hook": p.hook, "tools_empty": p.tools_empty, "session": p.session,
            "fence": p.fence}


def read_launches(cwd, home_dir=None) -> List[dict]:
    """cwd の起動の記録を古い順に。無い・読めない行は飛ばす"""
    try:
        text = launches_path(cwd, home_dir).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for ln in text.splitlines():
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def last_launch(cwd, node: str, home_dir=None) -> Optional[dict]:
    """cwd で節 node を起こした最後の行（無ければ None）"""
    rows = [r for r in read_launches(cwd, home_dir) if r.get("node") == node]
    return rows[-1] if rows else None


def read_session_id(path: pathlib.Path) -> Optional[str]:
    """id のファイルの中身。無い・読めない・空・1 語でない時は None"""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text if _ID_RE.match(text) else None


def hook_settings(command: str) -> dict:
    """足す設定。期限は足さない（Claude の既定のまま）"""
    return {"hooks": {"PostToolUse": [{"matcher": "Read", "hooks": [{"type": "command", "command": command}]}]}}


def hook_command(python: str, recorder, sink) -> str:
    return " ".join(shlex.quote(str(x)) for x in (python, recorder, sink))


def merge_settings(sdk: dict, ours: dict) -> dict:
    """ours を sdk に足す。hooks の出来事ごとの配列は後ろに足し、辞書は潜り、それ以外は SDK の値を残す"""
    for k, v in ours.items():
        if k == "hooks" and isinstance(v, dict):
            h = sdk.setdefault("hooks", {})
            if not isinstance(h, dict):
                raise Unrecognised("--settings の hooks が object でない")
            for ev, matchers in v.items():
                cur = h.setdefault(ev, [])
                if not isinstance(cur, list):
                    raise Unrecognised(f"--settings の hooks.{ev} が配列でない")
                cur.extend(matchers)
        elif isinstance(v, dict) and isinstance(sdk.get(k), dict):
            merge_settings(sdk[k], v)
        else:
            sdk.setdefault(k, v)
    return sdk


def _load_settings(value: str) -> dict:
    if value.lstrip().startswith("{"):
        try:
            data = json.loads(value)
        except ValueError:
            raise Unrecognised("--settings の JSON が読めない") from None
    else:
        try:
            with open(value, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError, UnicodeDecodeError):
            raise Unrecognised("--settings が JSON でも読めるファイルでもない") from None
    if not isinstance(data, dict):
        raise Unrecognised("--settings が JSON の object でない")
    return data


def _with_hook(argv: List[str], command: str, protected: Sequence[str], no_post: bool = False) -> Tuple[List[str], dict]:
    found = find_opt(argv, "--settings")
    if len(found) > 1:
        raise Unrecognised("--settings が 2 つ以上")
    doc = merge_settings(_load_settings(found[0][2]), hook_settings(command)) if found else hook_settings(command)
    n_write, n_deny = add_fences(doc, protected) if protected else (0, 0)
    fence = {"deny_write": n_write, "permissions_deny": n_deny}
    if no_post:
        fence["no_post"] = add_deny(doc, NO_POST_DENY)
    text = json.dumps(doc, ensure_ascii=False)
    if not found:
        return argv + ["--settings", text], fence
    i, n, _, joined = found[0]
    return argv[:i] + (["--settings=" + text] if joined else ["--settings", text]) + argv[i + n:], fence


# --- 起動ごとの柵 ---------------------------------------------------------------------------------------------
GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")   # ticket.py と同じ（外から漏れると別のリポジトリを見る）
_ALIASES = (("/private/var", "/var"), ("/private/tmp", "/tmp"), ("/private/etc", "/etc"))


def ticket_path(cwd, home_dir=None) -> pathlib.Path:
    """切符の置き場（ticket.ticket_path と同じ式）"""
    return _home_or(home_dir) / "tickets" / f"{cwd_key(cwd)}.json"


def read_ticket(cwd, home_dir=None) -> Optional[dict]:
    """切符（ticket.read の代わりの薄い口。枝 wip/works-a4 の ticket.py と同じファイルを読む）。
    無い・読めない・object でない・protected が文字列の配列でなければ None"""
    try:
        doc = json.loads(ticket_path(cwd, home_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("protected"), list) \
            or not all(isinstance(p, str) and os.path.isabs(p) for p in doc["protected"]):
        return None
    return doc


def _alias(p: str) -> Optional[str]:
    for priv, pub in _ALIASES:
        for a, b in ((priv, pub), (pub, priv)):
            if p == a or p.startswith(a + "/"):
                return b + p[len(a):]
    return None


def spellings(path: str) -> List[str]:
    """同じ場所の綴りの全部: 渡された形・realpath・macOS の /var↔/private/var・/tmp↔/private/tmp・/etc↔/private/etc"""
    out: List[str] = []
    for p in (os.path.normpath(path), os.path.realpath(path)):
        for q in (p, _alias(p)):
            if q and q not in out:
                out.append(q)
    return out


def live_worktrees(cwd) -> List[str]:
    """cwd のリポジトリの今の worktree（元の作業ツリーを含む）のうち、cwd の worktree 自身でない物。git が引けなければ []"""
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROP}
    try:
        own = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             env=env, check=True).stdout.strip()
        listed = subprocess.run(["git", "-C", str(cwd), "worktree", "list", "--porcelain"], capture_output=True,
                                text=True, env=env, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    trees = [ln[len("worktree "):] for ln in listed.splitlines() if ln.startswith("worktree ")]
    return [t for t in trees if os.path.realpath(t) != os.path.realpath(own)]


def protected_now(ticket_doc: dict, cwd, env, worktrees: Sequence[str]) -> List[str]:
    """この起動で守る場所: 切符の protected ＋ 起動の env の CLAUDE_CONFIG_DIR ＋ 今の worktree。全部の綴りで。
    役の cwd の worktree 自身とその中は外す（役はそこに書く）"""
    places = list(ticket_doc.get("protected") or [])
    if env.get("CLAUDE_CONFIG_DIR"):
        places.append(os.path.abspath(env["CLAUDE_CONFIG_DIR"]))
    places += list(worktrees)
    mine = os.path.realpath(str(cwd))
    out, seen = [], set()
    for p in places:
        real = os.path.realpath(p)
        if real == mine or real.startswith(mine + os.sep):
            continue
        for s in spellings(p):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def deny_rules(paths: Sequence[str]) -> List[str]:
    """permissions.deny の規則。`//` で始まる形が絶対パス（Claude Code の規則の書き方）"""
    rules = []
    for p in paths:
        body = "/" + p                   # "/abs" → "//abs"
        for tool in ("Edit", "Write"):
            rules += [f"{tool}({body})", f"{tool}({body}/**)"]
    return rules


def add_deny(settings: dict, rules: Sequence[str]) -> int:
    """permissions.deny の後ろに rules を足す（在る物は足さない）。足した数"""
    perms = settings.setdefault("permissions", {})
    if not isinstance(perms, dict):
        raise Unrecognised("--settings の permissions が object でない")
    deny = perms.setdefault("deny", [])
    if not isinstance(deny, list):
        raise Unrecognised("--settings の permissions.deny が配列でない")
    n = 0
    for r in rules:
        if r not in deny:
            deny.append(r)
            n += 1
    return n


def add_fences(settings: dict, paths: Sequence[str]) -> Tuple[int, int]:
    """settings に柵を足す（SDK の項目は消さず、後ろに足す）。足した (denyWrite の数, permissions.deny の数)"""
    n_deny = add_deny(settings, deny_rules(paths))
    n_write = 0
    sandbox = settings.get("sandbox")
    if isinstance(sandbox, dict):
        fs = sandbox.setdefault("filesystem", {})
        if not isinstance(fs, dict):
            raise Unrecognised("--settings の sandbox.filesystem が object でない")
        dw = fs.setdefault("denyWrite", [])
        if not isinstance(dw, list):
            raise Unrecognised("--settings の sandbox.filesystem.denyWrite が配列でない")
        for p in paths:
            if p not in dw:
                dw.append(p)
                n_write += 1
    return n_write, n_deny


def _strip_session_flags(argv: List[str]) -> List[str]:
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in SESSION_VALUE_FLAGS:
            # 値の無い --resume（対話で選ぶ形）も外す。次の語が旗なら値ではない
            i += 2 if i + 1 < len(argv) and not argv[i + 1].startswith("-") else 1
            continue
        if a in SESSION_BARE_FLAGS or any(a.startswith(f + "=") for f in SESSION_VALUE_FLAGS if f.startswith("--")):
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def _tools_empty(argv: Sequence[str]) -> bool:
    try:
        return any(v == "" for _, _, v, _ in find_opt(argv, "--tools"))
    except Unrecognised:
        return False


def plan(argv: Sequence[str], cwd, home_dir, command: str,
         new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
         protected: Optional[Callable[[], Sequence[str]]] = None) -> Plan:
    """argv をどう直すかを決める（ファイルは id の読みと --settings のファイルの読みだけ。書かない）。
    protected は守る場所を返す関数（フックを足す起動でだけ呼ぶ。切符が無ければ空を返す）"""
    argv = list(argv)
    tools_empty = _tools_empty(argv)
    try:
        marker = marker_from_argv(argv)
    except BadMarker as e:
        return Plan(argv, "refused", f"works: {e}。claude を起こさない（印を直す）", True, None, None, False,
                    tools_empty, {"mode": "refused", "id": None}, [])
    except Unrecognised as e:
        return Plan(argv, "passthrough", str(e), True, None, None, False, tools_empty, None, [])
    if marker is None:
        return Plan(argv, "passthrough", "unmarked", False, None, None, False, tools_empty, None, [])

    home_dir = _home_or(home_dir)
    node, cont = marker.name, marker.cont
    # 1. 会話の継ぎ（--settings の形に依らずに行う）
    record: List[Tuple[pathlib.Path, str]] = []
    if cont:
        src = session_path(cwd, cont, home_dir)
        sid = read_session_id(src)
        if sid is None:
            why = f"works: 会話 {cont} の id が無い（節 {node} は {cont} の続きとして起こす）: {src}"
            return Plan(argv, "refused", why, True, node, cont, False, tools_empty,
                        {"mode": "refused", "id": None, "of": cont}, [])
        out = _strip_session_flags(argv) + ["--resume", sid]
        session = {"mode": "continued", "id": sid, "of": cont, "from": sid}
    else:
        out = argv
        try:
            resumed = find_opt(argv, "--resume")
            given = find_opt(argv, "--session-id")
        except Unrecognised as e:
            return Plan(argv, "passthrough", str(e), True, node, cont, False, tools_empty, None, [])
        src = resumed[-1][2] if resumed else None
        if given:
            sid, mode = given[-1][2], "sdk-fork" if src and "--fork-session" in argv else "sdk-session"
        elif src and "--fork-session" in argv:
            sid, mode = new_id(), "sdk-fork"
            out = argv + ["--session-id=" + sid]
        elif src:
            sid, mode = src, "sdk-resume"
        else:
            sid, mode = new_id(), "new"
            out = argv + ["--session-id=" + sid]
        session = {"mode": mode, "id": sid}
        if src:
            session["from"] = src
    record.append((session_path(cwd, node, home_dir), sid))

    # 2. Read のフック
    try:
        out, fence = _with_hook(out, command, protected() if protected else [], "no-post" in marker.flags)
    except Unrecognised as e:
        return Plan(out, "passthrough", str(e), True, node, cont, False, tools_empty, session, record)
    return Plan(out, "merged", None, False, node, cont, True, tools_empty, session, record, fence)


# --- 木ごと止める（試し P15 の直しの形。scratchpad/probes-p14-p15-summary.md） ------------------------------------
KILL_GRACE = tree_run.KILL_GRACE                  # 2 秒（台帳 R31）。新しい値を作らない
POLL = tree_run.POLL                              # 0.2 秒
STOP_SIGNALS = tree_run.STOP_SIGNALS
LINGER = getattr(tree_run, "LINGER", 1.0)         # 枝 wip/works-treerun の tree_run.LINGER（試し P17）と同じ値


def _ps() -> Optional[List[Tuple[int, int, int]]]:
    """全プロセスの (pid, ppid, pgid)。読めなければ None"""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,pgid="], stdin=subprocess.DEVNULL, capture_output=True,
                             text=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    rows = []
    for line in out.splitlines():
        f = line.split()
        if len(f) == 3 and all(x.isdigit() for x in f):
            rows.append((int(f[0]), int(f[1]), int(f[2])))
    return rows or None


def remember(root: int, seen: Dict[int, int]) -> None:
    """root の子孫（ppid を辿る。root を含む）の {pid: pgid} を seen に足す。自分（包み）は数えない"""
    rows = _ps()
    if rows is None:
        return
    fam, grew = {root}, True
    while grew:
        grew = False
        for pid, ppid, _ in rows:
            if ppid in fam and pid not in fam:
                fam.add(pid)
                grew = True
    for pid, _, pgid in rows:
        if pid in fam and pid != os.getpid():
            seen[pid] = pgid


def _groups_alive(root: int, seen: Dict[int, int]) -> List[int]:
    """覚えた仲間のうち、今も同じ pid・同じグループで居る物のグループ（番号の再利用で他人を撃たない）と root のグループ"""
    rows = _ps() or []
    now = {pid: pgid for pid, _, pgid in rows}
    groups = {pgid for pid, pgid in seen.items() if now.get(pid) == pgid}
    groups.add(root)
    return sorted(groups)


def _alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def stop_all(p: subprocess.Popen, seen: Dict[int, int], first: int = signal.SIGTERM) -> None:
    """覚えた仲間のグループ全部へ (first と SIGTERM) → KILL_GRACE → SIGKILL"""
    if p.poll() is None:
        remember(p.pid, seen)
    groups = _groups_alive(p.pid, seen)
    for sig in dict.fromkeys((first, signal.SIGTERM)):
        for g in groups:
            try:
                os.killpg(g, sig)
            except OSError:
                pass
    end = time.monotonic() + KILL_GRACE
    while time.monotonic() < end and any(_alive(g) for g in groups):
        p.poll()
        time.sleep(0.05)
    for g in groups:
        try:
            os.killpg(g, signal.SIGKILL)
        except OSError:
            pass
    p.poll()


def supervise(argv: Sequence[str]) -> int:
    """argv（本物の claude と引数）を新しいセッションで起こして待ち、終了コードを返す（信号で死んだら 128+信号）。
    止める信号を受けたか直下の親が替わったら木ごと止め、LINGER 待って 128+信号（親の替わりは SIGHUP）を返す"""
    got: List[int] = []
    old = {s: signal.signal(s, lambda signum, _f: got.append(signum)) for s in STOP_SIGNALS}
    ppid = os.getppid()
    seen: Dict[int, int] = {}
    p = subprocess.Popen(list(argv), start_new_session=True)
    try:
        while True:
            if got or os.getppid() != ppid:
                signum = got[0] if got else signal.SIGHUP
                stop_all(p, seen, signum)
                time.sleep(LINGER)
                return 128 + signum
            try:
                rc = p.wait(POLL)
                break
            except subprocess.TimeoutExpired:
                remember(p.pid, seen)
        stop_all(p, seen)       # claude が背景に残した孫（Bash の道具の別のグループ）
        if got:
            time.sleep(LINGER)
            return 128 + got[0]
        return rc if rc >= 0 else 128 - rc
    finally:
        if p.poll() is None:
            stop_all(p, seen)
        for s, h in old.items():
            signal.signal(s, h)
