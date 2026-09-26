"""engine の小道具——時刻・hash・JSON の読み書き・git・path の辿り方。ループの中身を知らない。"""
import datetime
import hashlib
import json
import os
import pathlib
import re
import stat
import subprocess
import sys

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent
# 役の名前・段の名前・道具の名前・プラグイン名は engine に書かない——graph の runners / thickness.tiers / deliver.path_tools / plugin が正本


class Reject(Exception):
    """受け付けない（exit 1）。直して呼び直せる。"""


class AnswerReject(Reject):
    """**返答の中身・形**が受け付けられない（読めない・型に合わない・記録の整合が取れない）。役に理由を返せば直せる
    ——engine が起こした役なら、同じ会話に続きを頼む（loop.py launch）。それ以外の Reject（節が待っていない・
    作業ツリーが変わった・前段が済んでいない）は役に返しても直らないので、続きを頼まずに回す側へ上げる。"""


class BoardConflict(SystemExit):
    """盤面を読んだ後に別のプロセスが盤面を進めていた（Board.save）。die と同じく exit 2 で終わる。別の型にしたのは、
    読み直して当て直してよい失敗（版の衝突）を、ほかの die（記録の書き込みの失敗など）と見分けるため（commands._board_update・
    launch の受け付け）。**文はここで出さない**——当て直して成功した回に失敗の文を残さないよう、最後に負けた回だけ
    入口（loop.py の main）が msg を出す"""

    def __init__(self, msg):
        super().__init__(2)
        self.msg = msg

    def __str__(self):   # 捕まえて理由の文に載せる口（run_role の受け付けの検査）でも本文が読めるように——code は 2 のまま
        return self.msg


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def waiting(inst):
    """待っている instance の経過と試行の回数——{elapsed_min, attempts}。**その場で計算し、盤面には書かない**"""
    t = datetime.datetime.fromisoformat(now())
    return {"elapsed_min": int((t - datetime.datetime.fromisoformat(inst["emitted_at"])).total_seconds() // 60),
            "attempts": inst.get("attempts", 1)}


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


LAST_DIE = None   # 最後に die した文面（loop.py の最上段が非 0 の終わりに記録器へ渡す。行に残すのは利用者が環境変数で選んだときだけ）


def die(msg, code=2):
    global LAST_DIE
    LAST_DIE = msg
    print(f"NG {msg}", file=sys.stderr)
    sys.exit(code)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        die(f"{path}: 読めない（{e}）")


def write_json(path, obj):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1)


# run が終わった状態。**2 語を engine の 2 か所に手で並べていた**——どちらかに値を足すと、
# もう一方だけが古いまま黙って通る（進行が止まらない／終わった run に次の節を出す）。
TERMINAL_STATUS = ("converged", "stopped")
# 人の答えとして engine が**実際に動ける語**。`continue` は次の周、`stop` は終端、`escalate` は最上段へ。
# 表が無かったとき、`ans == "stop"` 以外は全部 else（新しい周を開く）に落ちていた——rules が options に
# 綴り違いや engine の知らない語を入れると、**その語が「続ける」として通る**（諮った意味が消える）。
# 知らない語は落とす側に倒す: 諮りの口は「止める／続ける」の分岐なので、既定を「続ける」にしてはいけない。
ANSWER_ACTIONS = ("continue", "stop", "escalate")
# **周の途中の問い（ask の in_round が真）**で engine が動ける語。continue は問うた節を済ませて同じ周のまま先へ、
# stop は run をその場で止める（halted。後の節は 1 つも出さない）。escalate は周を進める語なので持たない——
# 周の途中の問いは、周の中の工程（仕様の承認・承認後のテストの変更）で人の答えを待つ口で、周の終わりの判定ではない
IN_ROUND_ACTIONS = ("continue", "stop")

GIT_TIMEOUT = 120  # 秒。近傍の scripts/comment-ratio.sh と同じ上限


GIT_CWD = None  # 対象リポジトリ。init が記録した inputs.cwd を engine が 1 度だけ入れる（下の _repo_args を見よ）


def _repo_args():
    """git に渡す -C。**run は自分の対象リポジトリを値で持つ。**

    以前は git をプロセスの cwd で実行していたので、`--dir` を明示した run は対象リポジトリとの結び付きが
    外れた——resolve_dir は `--dir` が無いときだけ cwd の .git から run を探すので、`--dir` を渡すとその
    暗黙の錨だけが唯一の結び付きだった（実測 2026-09-13: 別のリポジトリの cwd から done を実行したら
    record.base が別リポジトリの HEAD になり、exit 0 で受理された）。inputs.cwd は init 時に記録されるのに
    突合にも実行にも使われていなかった。
    """
    return ["-C", GIT_CWD] if GIT_CWD else []


GIT_WHY_CAP = 300  # 失敗の理由として運ぶ git の標準エラーの末尾の字数


def git(*args, env=None, why=None):
    """成功なら stdout、失敗（git が無い・非 0・時間切れ）なら None。呼ぶ側は None を『分からない』として扱い、合格に倒さない。

    `env` は**足す**（置き換えない）。GIT_INDEX_FILE を渡して一時 index の上で組み立てる呼びが 1 つ在る
    ——intent-to-add の index では stash create も write-tree も非 0 で返るので、本物の index を避ける道が要る。
    置き換えにすると PATH も HOME も消えて git ごと動かなくなるので、os.environ の写しに足す形で固定する。

    `why` にリストを渡すと、失敗の回だけ git が言った理由（標準エラーの末尾）をそこに足す——止める側が利用者に
    原因を見せるため（subprocess.CalledProcessError が stderr を運ぶのと同じ役）。戻り値の契約は変えない。
    """
    args = (*_repo_args(), *args)
    run_env = {**os.environ, **env} if env else None
    try:
        # errors=replace: 対象リポジトリに非 UTF-8 のテキストが 1 本でも在ると、復号の例外が『失敗なら None』の契約を
        # 迂回して総括例外で落ちた（実測 2026-09-13: next が exit 2 でどの周にも進めない）。置換文字で読み、落とさない
        r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=GIT_TIMEOUT, env=run_env)
    except (OSError, subprocess.TimeoutExpired) as e:
        if why is not None:
            why.append(f"{type(e).__name__}: {e}"[-GIT_WHY_CAP:])
        return None
    if r.returncode == 0:
        return r.stdout
    if why is not None:
        why.append(r.stderr.strip()[-GIT_WHY_CAP:] or f"exit {r.returncode}（標準エラーは空）")
    return None


def git_bytes(*args):
    """成功なら stdout の**生バイト**、失敗なら None。突合（sha）に使う——git() の errors=replace は復号できない
    バイトを種類に依らず U+FFFD 1 文字に写すので、等長の非 UTF-8 書き換えが同じ文字列＝同じ sha になる
    （実測 2026-09-13: b"caf\xe9 \xff" と b"caf\xc3 \xfe" が一致）。貼る用は落としてよい／突合用は落としてはいけない。"""
    args = (*_repo_args(), *args)
    try:
        r = subprocess.run(["git", *args], capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def porcelain():
    """作業ツリーの写し。None = git が効かない（作業ツリーの保護はできない——呼ぶ側が止める）。"""
    out = git("status", "--porcelain")
    return None if out is None else sorted(out.splitlines())


def _step(cur, parts, i, upto):
    """`cur` の中で `parts[i:upto]` の先頭に最長一致する鍵を探し、`(次の cur, 次の i)` を返す。無ければ None。

    **読む側（get_path）と書く側（set_path）はこの 1 本を共有する。** 以前は同じ走査が 2 本在り、
    書く側だけ最後の区切りを候補から外していた——`outputs.p1.local_review` のように**点を含む鍵が
    最後に来る綴り**が最長一致に当たらず、`cur.setdefault("p1", {})` へ落ちて新しい入れ子が生まれた。
    読む側は元の場所を読み続けるので、`patch` は ok を印字しながら手当てが当たらない（実測 2026-09-16:
    独立した 4 レンズが同じ所を指し、2 本は実走の盤面で ok が返ることまで測った）。
    """
    if isinstance(cur, dict):
        for j in range(upto, i, -1):
            key = ".".join(parts[i:j])
            if key in cur:
                return cur[key], j
    elif isinstance(cur, list) and parts[i].isdigit() and int(parts[i]) < len(cur):
        return cur[int(parts[i])], i + 1
    return None


def get_path(obj, path):
    """`a.b.c` で辿る。節名に点が入る（out.p0.question.x）ので、辞書の鍵は最長一致で食う。"""
    parts = path.split(".")
    cur = obj
    i = 0
    while i < len(parts):
        nxt = _step(cur, parts, i, len(parts))
        if nxt is None:
            raise KeyError(path)
        cur, i = nxt
    return cur


def set_path(obj, path, value):
    """`a.b.c` と `a.2.b` で辿って書く。**get_path と同じ綴りを受ける**——読める形に書けないと、
    手当ての口が黙って別の場所を作る（実測 2026-09-16: `questions[1]` を渡すと配列の要素ではなく
    その名前の鍵が新設され、patch は ok を返した。当たっていない手当てが 2 回成功と報告され、
    検証器が別の理由で落ちて初めて分かった）。

    辿り方は `_step`＝get_path と同じ 1 本。**作ってよいのは葉 1 つだけ**——親が辿れない綴りは
    落とす。以前は途中の辞書を何段でも作ったので、点を含む鍵を指す綴りが「既存の鍵の隣に
    新しい入れ子」を黙って生やす形だった（どちらの読みも成り立つ綴りで、機械が片方を勝手に選んでいた）。
    リストの添字は**既に在る要素だけ**を指せる——リストを伸ばす手当ては、順序の意味を回す側が決める。
    """
    # **角括弧は受けない。** `questions[1]` は get_path が読めない綴りで、黙って通すと
    # その名前の鍵が新設される（今回の事故そのもの）。書けない綴りはここで落とす。
    if "[" in path or "]" in path:
        raise KeyError(f"{path}: 添字は角括弧でなく点で書く（questions.1）——get_path が読める綴りだけを受ける")
    parts = path.split(".")
    cur = obj
    i = 0
    while i < len(parts) - 1:
        # 残り全部が 1 つの鍵（点を含む鍵）なら、ここが親。**この枝が無かったのが今回の欠陥**
        # ——`outputs.p1.local_review` は最後の区切りを候補から外す走査に当たらず、`p1` の入れ子を
        # 新設していた。get_path は元の場所を読み続けるので、当たらない手当てが ok を返した。
        rest = ".".join(parts[i:])
        if isinstance(cur, dict) and rest in cur:
            cur[rest] = value
            return
        nxt = _step(cur, parts, i, len(parts) - 1)
        if nxt is not None:
            cur, i = nxt
            continue
        if not isinstance(cur, dict):
            raise KeyError(path)
        if i != len(parts) - 2:
            # 作るのは葉 1 つまで。2 段以上の新設は「点を含む 1 つの鍵」との区別が付かない
            raise KeyError(f"{path}: '{'.'.join(parts[:i + 1])}' から先が辿れない——"
                           f"作ってよいのは葉 1 つだけ（親を先に作るか、既に在る綴りを指せ）。"
                           f"2 段以上を黙って作ると、点を含む 1 つの鍵と区別が付かない")
        cur = cur.setdefault(parts[i], {})
        i += 1
    last = parts[-1]
    if isinstance(cur, list):
        if not (last.isdigit() and int(last) < len(cur)):
            raise KeyError(path)
        cur[int(last)] = value
    elif isinstance(cur, dict):
        cur[last] = value
    else:
        raise KeyError(path)


def has_path(obj, path):
    if path in (None, "$"):
        return True
    try:
        get_path(obj, path)
        return True
    except KeyError:
        return False


def pick(value, fields):
    if isinstance(value, list):
        return [pick(v, fields) for v in value]
    if isinstance(value, dict):
        return {k: value[k] for k in fields if k in value}
    return value


def safe_name(instance_id):
    return re.sub(r"[^\w.\-]+", "__", instance_id)


# 役が指した文書を engine が読む上限（バイト）。読了の突合の sha・修正側の引用の数え・数える問いの子の出力が同じ値を
# 使う（別名で 2 つ持っていた頃は、片方だけ動かすと上限が黙ってずれた）。これを超える物は測らずに倒す。**値の根拠**:
# 追跡下で最大のテキスト（リポジトリ直下の tests/run.sh。`git ls-files -z | xargs -0 wc -c | sort -n | tail` で引ける）
# の 1 桁上に置き、普通の文書では効かず、誤って巨大な生成物を指した回だけ止める。
# **hooks/record-read.py に同じ値の写しが在る**（フックは engine を import しないため）
READ_CAP = 4_000_000


def read_capped(path, cap):
    """**通常のファイルだけを、上限の 1 バイト先まで読む** ——（bytes, ""）か（None, 理由）。

    役が指したパスを開く所はこの 1 本を通す。大きさを stat で見てから読み切る形は、大きさを申告しない物（FIFO）や
    読む間に伸びる物で上限が効かず、書き手の居ない FIFO は開くだけで止まる——判定は実際に読めた長さで下す
    （再現: simulate.py の test_hook_evidence の FIFO と上限ちょうどの腕）。以前は同じ手順を 3 か所に手で写し、
    1 か所だけ通常のファイルかの柵が抜けていた。
    """
    try:
        if not stat.S_ISREG(os.stat(path).st_mode):
            return None, "通常のファイルでない（開くと書き手を待って止まりうる）"
        with open(path, "rb") as f:
            data = f.read(cap + 1)
    except OSError as e:
        return None, f"読めない（{type(e).__name__}: {e}）"
    if len(data) > cap:
        return None, f"大きすぎて測らない（{cap} バイト超）"
    return data, ""


# 数える問い（how）の形。**役は検索語・パス・数え方を欄で書き、argv は engine が決まった形で組む**（OWASP OS Command
# Injection Defense Cheat Sheet の Defense Option 3——データとコマンドを構造で分け、引数を許可リストで検証し、オペランドの前に
# `--` を置く）。役の書いた 1 行を字句解析して段ごとの許可表で見張っていた頃は、3 周続けて別の入口から隙間が出た
# （`-c` を最後の段でしか見ない・版を 1 本目だけ確かめる・パスを別の世界で確かめる）。数える世界（リポジトリの中・.git を外す・
# .gitignore を尊重する）は git の pathspec 1 つに任せる。
COUNT_BY = {"lines": "-c", "files": "-l"}   # 一致した行の数（ファイルごとの -c の合計）か、一致したファイルの本数
COUNT_MAX = {"patterns": 20, "paths": 50}
# 数える問いの出力の上限。READ_CAP（役が指した文書を読む上限）と値は同じだが守る物が違うので分ける——同じ定数を
# 読んでいた頃、読了の台本が READ_CAP を一時的に 1 へ書き換える間に並列の台本の数える問いが『上限超え』で落ちた
COUNT_CAP = 4_000_000
_TEXT = {"type": "string", "minLength": 1, "pattern": "^[^\\n\\r\\x00]+$"}
# **数える問いの欄の正本**（graph の schema は "$ref": "engine#/count_how" でこれを引き、count_argv も同じ schema で型を当てる）。
# 節ごとに schema を手で写していた頃は、写しの 1 つだけが古い形のまま残り、揃いを見る検出器を足してもその検出器が拾う形の外で崩れた
# （2026-09-24 の review-graph 2 周目の一撃）
COUNT_HOW_SCHEMA = {
    "type": "object", "required": ["patterns", "paths", "count"], "additionalProperties": False,
    "properties": {
        "patterns": {"type": "array", "minItems": 1, "maxItems": COUNT_MAX["patterns"], "items": _TEXT,
                     "note": "検索語（1 つ以上。どれかに一致した行を数える）。git grep -e に 1 つずつ渡る"},
        "fixed": {"type": "boolean", "note": "true なら固定文字列（-F）、無いか false なら拡張正規表現（-E）"},
        "paths": {"type": "array", "minItems": 1, "maxItems": COUNT_MAX["paths"], "items": _TEXT,
                  "note": "数える場所（リポジトリのルート相対の git pathspec）"},
        "count": {"type": "string", "enum": list(COUNT_BY),
                  "note": "lines＝一致した行の数（ファイルごとの -c の合計）／files＝一致したファイルの本数（-l）"},
        "untracked": {"type": "boolean", "note": "true なら .gitignore に当たらない未追跡のファイルも数える（版を渡して数える回は落とす）"},
        "ignore_case": {"type": "boolean"},
        "word": {"type": "boolean", "note": "語の単位で一致（-w）"},
    },
    "note": "同じ形を全部引く問いを欄で書く。argv は engine が決まった形で組む（git grep -I --no-color -c|-l -F|-E [-i] [-w] [--untracked] "
            "-e <語>… [版] -- <パス>…）。数える版は書かない（版は呼び元が決める）。シェルもパイプも通らない",
}
# graph の schema が "$ref" で引ける engine の定義（engine/schema.py の expand_refs が展開する）
ENGINE_DEFS = {"count_how": COUNT_HOW_SCHEMA}


def count_argv(how, rev=None):
    """how（欄）から git grep の argv を組む ——（argv, ""）か（None, 拒否理由）。欄の型は COUNT_HOW_SCHEMA で当てる
    （graph の schema と同じ定義。役の返答は型検査を通った後に来るが、ここでも当てて入口に依らない）。**数える版（rev）は役に
    書かせず、呼び元が決める**——役が問いに版を書くと、作業ツリーを直した後の数え直しも同じ古い版を数え、直しが件数に
    一度も映らなかった（review-loop の実走の申し送り 2026-09-24）。版を渡した回は未追跡の旗を落とす"""
    from .schema import validate_schema
    if not isinstance(how, dict):
        return None, "how は欄（patterns・paths・count …）で書け——1 行のコマンドは受け取らない"
    errs = validate_schema(how, COUNT_HOW_SCHEMA, "how")
    if errs:
        return None, "how の欄が型に合わない: " + "; ".join(errs[:3])
    if rev is not None and not (isinstance(rev, str) and rev and not rev.startswith("-") and not any(c.isspace() or c == "\0" for c in rev)):
        return None, "数える版は版の名前 1 つ（- で始まらず、空白を含まない）"
    argv = ["git", "grep", "-I", "--no-color", COUNT_BY[how["count"]], "-F" if how.get("fixed") else "-E"]
    argv += [f for k, f in (("ignore_case", "-i"), ("word", "-w"), ("untracked", "--untracked")) if how.get(k) and not (rev and k == "untracked")]
    for pat in how["patterns"]:
        argv += ["-e", pat]
    return argv + ([rev] if rev else []) + ["--"] + list(how["paths"]), ""


def _run_capped(argv, cwd, timeout, cap):
    """1 本を走らせる ——（exit, 標準出力, 標準エラーの頭, 上限を超えたか, 時間切れか）。
    標準入力は DEVNULL（engine の標準入力を子に継がせない）、標準出力は上限の 1 バイト先までしか読まない"""
    import tempfile
    import threading
    flags = {"timeout": False}

    def kill():
        flags["timeout"] = True
        p.kill()
    with tempfile.TemporaryFile() as err:
        p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err)
        timer = threading.Timer(timeout, kill)
        timer.start()
        try:
            out = p.stdout.read(cap + 1)
            over = len(out) > cap
            if over:
                p.kill()
            p.stdout.close()
            rc = p.wait()
        finally:
            timer.cancel()
        err.seek(0)
        msg = err.read(2000).decode("utf-8", "replace").strip()
    return rc, out, msg, over, flags["timeout"]


def sum_counts(text):
    """`…:数` の行（git grep -c の出力）の合計。数でない行が 1 行でも在れば None（黙って飛ばさない）"""
    lines = [l for l in text.splitlines() if l.strip()]
    if not all(l.rpartition(":")[2].strip().isdigit() for l in lines):
        return None
    return sum(int(l.rpartition(":")[2]) for l in lines)


def _grep_run(argv, cwd, timeout, cap):
    """git grep を 1 本 ——（exit, 標準出力のバイト, ""）か（None, None, 理由）。**読めなかった問いを 0 件にしない**:
    時間切れ・上限超え・標準エラーへの書き込み・1 でない非 0 は理由を返す（一致なしの exit 1 は正当な 0 件）"""
    try:
        rc, out, err, over, late = _run_capped(argv, cwd, timeout, cap)
    except OSError as e:
        return None, None, f"走らせられない（{type(e).__name__}）"
    if late:
        return None, None, f"git grep が {timeout} 秒で終わらない"
    if over:
        return None, None, f"git grep の出力が上限（{cap} バイト）を超えた——パスを絞れ"
    if err:
        return None, None, f"git grep が標準エラーに書いた（{err[:120]}）——読めなかった問いは 0 件の証拠にならない"
    if rc not in (0, 1):
        return None, None, f"git grep が exit {rc}——読めなかった問いは 0 件の証拠にならない"
    return rc, out, ""


def _grep_found(argv, cwd, timeout):
    """git grep -q を 1 本 ——（当たったか, ""）か（None, 理由）"""
    rc, _, why = _grep_run(argv, cwd, timeout, 1)
    return (None, why) if why else (rc == 0, "")


def _grep(argv, cwd, timeout):
    """git grep を 1 本 ——（標準出力の文字列, ""）か（None, 理由）"""
    _, out, why = _grep_run(argv, cwd, timeout, COUNT_CAP)
    return (None, why) if why else (out.decode("utf-8", "replace"), "")


def repo_root(git_fn=None):
    """対象リポジトリのルート（引けなければ None）。engine と rules が同じ 1 本を使う——rules は差し込まれた git（台本が
    対象リポジトリに固定して撃つ）を git_fn に渡す"""
    return ((git_fn or git)("rev-parse", "--show-toplevel") or "").strip() or None


# 任せ先に書かせない、利用者の手元の置き場（作業ツリーの外から本物の git と engine に入る道）。git の設定は core.hooksPath・
# core.fsmonitor・alias を持てるので、書き換えられると sandbox の外で回す側と engine が打つ git がそれを走らせる。シェルの起動ファイルも
# 同じく外で走る。engine 自身（プラグインの置き場）と Claude Code の設定は柵そのもの。sandbox の組み込みの保護は作業ディレクトリの
# 中のこれらしか守らない（公式の sandboxing 文書の Protected paths）ので、任せ先の作業ディレクトリを外に置く形では名指しが要る
HOME_PROTECTED = (".gitconfig", ".config/git", ".bashrc", ".bash_profile", ".profile", ".zshrc", ".zprofile", ".zshenv")


def protected_paths(extra=()):
    """任せ先（delegate）の sandbox が書き込みを拒む場所の一覧（並びは決まった順）。引けなければ None——柵を組めないので起こさない。
    extra は呼び元が足す場所（盤面の置き場。--dir で作業ツリーの外に置いた盤面は git からは引けない）。

    **正本は git** で、engine は値を持たない: 作業ツリーのルート（--show-toplevel）・この作業ツリーの gitdir の実体
    （--absolute-git-dir。linked worktree なら本体の .git/worktrees/<名前>）・共通の .git（--git-common-dir）・同じリポジトリの
    全部の作業ツリー（worktree list）。既定の盤面（gitdir の下）もこれで覆われる。綴りと実体（realpath）を両方入れる——macOS の
    /var と /private/var のように、同じ場所を 2 つの綴りで指せるので、片方だけだと別の綴りで書かれる"""
    top = git("rev-parse", "--show-toplevel")
    gd = git("rev-parse", "--absolute-git-dir")
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir")
    wl = git("worktree", "list", "--porcelain")
    if not all(x and x.strip() for x in (top, gd, common)) or wl is None:
        return None
    got = [top.strip(), gd.strip(), common.strip()]
    got += [line[len("worktree "):] for line in wl.splitlines() if line.startswith("worktree ")]
    home = pathlib.Path.home()
    got += [str(home / x) for x in HOME_PROTECTED]
    got += [str(PLUGIN_ROOT), os.environ.get("CLAUDE_CONFIG_DIR") or str(home / ".claude"), *map(str, extra)]
    return sorted({q for p in got for q in (os.path.abspath(p), os.path.realpath(p))})


def copy_worktree(dst):
    """対象リポジトリの作業ツリーの今の姿を dst に写す（任せ先の作業ディレクトリ）。写せなければ Reject。

    写しは本物の .git を共有しない独立の clone（--shared は本物の object を読むだけで、新しい object は写しの側に書く）で、
    HEAD は本物と同じ commit、作業ツリーは本物の今の姿——未コミットの変更と未追跡の新規ファイルを載せ、作業ツリーで消した
    ファイルは消す。index は HEAD のままなので、写しの git diff / git status は本物と同じ変更を映す。.gitignore の対象
    （依存の置き場・ビルドの出力）は写さない——CI の checkout と同じ姿で、要るなら任せ先が写しの上で入れ直す"""
    top = repo_root()
    if not top:
        raise Reject("作業ツリーのルートを引けない——任せ先の写しを作れない")
    dst = pathlib.Path(dst)
    try:
        subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", top, str(dst)], check=True,
                       capture_output=True, timeout=GIT_TIMEOUT)
        head = git("rev-parse", "--verify", "-q", "HEAD")
        if head and head.strip():
            subprocess.run(["git", "-C", str(dst), "checkout", "-q", "--detach", head.strip()], check=True,
                           capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        raise Reject(f"任せ先の写しを作れない（git clone / checkout: {e}）") from e
    changed = git("diff", "--name-only", "-z", "HEAD") if head and head.strip() else git("ls-files", "-z")
    untracked = git("ls-files", "-z", "-o", "--exclude-standard")
    if changed is None or untracked is None:
        raise Reject("作業ツリーの変更を引けない（git diff / ls-files）——任せ先の写しを作れない")
    import shutil  # 写す節でだけ要る
    for rel in {x for x in (changed + untracked).split("\0") if x}:
        src, to = pathlib.Path(top) / rel, dst / rel
        if src.is_symlink() or src.is_file():
            to.parent.mkdir(parents=True, exist_ok=True)
            if to.is_symlink() or to.exists():
                to.unlink()
            shutil.copy2(src, to, follow_symlinks=False)
        elif not src.exists() and (to.is_symlink() or to.is_file()):
            to.unlink()
    return str(dst)


def run_count(how, cwd, timeout=60, rev=None, probe=True):
    """『同じ形を全部引く問い』（how）を engine が組んだ argv で走らせ、件数を返す ——（件数, ""）か（None, 理由）。

    パスは 1 本ずつ、**数える本体と同じ旗・同じ版で**テキストのファイルに 1 本以上当たるかを先に見る——指し先の無い問いは
    0 件の証拠にならない。probe=False はこの下調べを飛ばす: 直した後の数え直しでは、直しがファイルを消した（削除で解く）
    ために当たらなくなったパスは正当な 0 件である"""
    argv, why = count_argv(how, rev)
    if why:
        return None, why
    if rev:
        try:
            r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], cwd=cwd,
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            return None, f"数える版を確かめられない（{type(e).__name__}）"
        if r.returncode != 0:
            return None, f"数える版 {rev!r} が版として解決できない"
    # 下調べの argv も count_argv が組む（数える世界を決める旗——未追跡・版——は本体と同じ、一致の旗だけ外す）。
    # 旗の一覧を手で写していた頃は、count_argv に旗を足すと下調べに漏れた
    world, _ = count_argv({"patterns": ["^"], "paths": ["."], "count": "files",
                           **({"untracked": True} if how.get("untracked") else {})}, rev)
    world = world[:world.index("--")]
    # -l でなく -q——一致したファイル名を全部読まない（パス . で 5 万ファイルなら 1 本 9〜13 秒・1.8MB だった）
    world = ["-q" if x == "-l" else x for x in world]
    for p in how["paths"] if probe else []:
        found, why = _grep_found(world + ["--", p], cwd, timeout)
        if why:
            return None, f"パス {p!r} を確かめられない（{why}）"
        if not found:
            where = f"版 {rev}" if rev else ("追跡中と未追跡" if how.get("untracked") else "追跡中") + "のファイル"
            return None, f"パス {p!r} が数える世界（{where}）のテキストのファイルに 1 本も当たらない——指し先の無い問いは 0 件の証拠にならない"
    out, why = _grep(argv, cwd, timeout)
    if why:
        return None, why
    if how["count"] == "files":
        return len([l for l in out.splitlines() if l.strip()]), ""
    got = sum_counts(out)
    if got is None:
        return None, f"-c の出力が `…:数` の形でない（{out.splitlines()[0][:60]!r}）"
    return got, ""


# フックが部分読みに倒した理由（hooks/record-read.py の partial_why）と、説明に書く語
PARTIAL_WHY = {"range": "offset / limit 付き", "size": "ハーネスが切りうる大きさ"}


def hook_evidence(board_dir, doc, cache=None, data=None):
    """フックが盤面の隣に残した読了の記録から、この文書の全文読みを探す ——（結果, 説明）。

    結果は 5 つ: `"read"`（全文を読んだ記録が在る）／`"none"`（記録そのものが無い＝フックが
    入っていない、または入れる前に始めた session／記録か文書を読めない／文書が上限を超える・通常のファイルでない）／
    `"stale"`（読んだ後に文書が変わった）／`"absent"`（記録は在るがこの文書の読みが 1 件も無い）／`"partial"`
    （在るのは部分読みだけ。説明に理由——offset / limit 付きか、ハーネスが切りうる大きさか——を書く）。

    **`doc` はこのプロセスの cwd に解決する。** 呼ぶ側がリポジトリ相対のパスを渡すなら、
    渡す前にリポジトリのルート基準へ直せ（`--dir` を付けた run では cwd がリポジトリの外になる）。

    **これは「在れば強い」証拠であって、唯一の証拠ではない。** 射程は Read だけで、cat / sed で
    読んだ回は記録に残らない（bash のコマンド行からパスを取り出すのは綴りの数だけ穴が開く）。
    だから `read` 以外は**判定を下さず**、呼ぶ側が転写の走査へ落とす。ここで拒むと、
    フックを入れていない環境と別の読み方が、柵を切る以外の出口を持たなくなる。

    **受け取るのは盤面そのものでなく置き場のパス**（`board_dir`）——util.py は「ループの中身を知らない」と
    名乗る層なので、盤面の型を知らない形にしてある。読む先は置き場の隣 1 か所（書く側の理由は hooks/record-read.py）。

    突き合わせるのは**読んだ時のファイルの sha と、今の sha**。中身そのものは記録に残さない
    （文書の本文をこちらのディスクへ写さないため）ので、一致しなければ読み直しを求める側に倒れる。

    `cache` に辞書を渡すと、記録はその中に 1 度だけ読んでパスごとの索引にして持ち回す——1 回の検査で文書を
    何件も問う呼び元が、件数の分だけ記録を読み直し・解析し直さないため（記録の行数に上限は無い）。
    `data` は呼び元が read_capped で読み終えた文書のバイト列（同じファイルを 2 度開かない）。
    """
    log = pathlib.Path(board_dir) / "reads.jsonl"
    if not log.is_file():
        return "none", f"{log} が無い（フックが入っていないか、入れる前に始めた session）"
    # 上限を持たないと、役が大きなファイルを指した回に丸ごとメモリへ載る（この関数は拒否の材料であって柵ではない
    # ので、測れない回は none へ倒す）。値の根拠は READ_CAP の注記。render.py の FILE_CAP（40KB）とは守る物が
    # 違う——あちらはプロンプトに貼る穴の大きさで、揃えると 40KB を超える文書の読了証拠が黙って消える
    if data is None:
        data, why = read_capped(doc, READ_CAP)
        if data is None:
            return "none", f"{doc} は{why}"
    elif len(data) > READ_CAP:
        return "none", f"{doc} は大きすぎて測らない（{READ_CAP} バイト超）"
    want = hashlib.sha256(data).hexdigest()
    real = os.path.realpath(doc)
    if cache is not None and "index" in cache:
        index, n = cache["index"], cache["n"]
    else:
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            return "none", f"{log} を読めない（{e}）"
        index, n = {}, len(lines)
        for ln in lines:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if isinstance(r, dict) and isinstance(r.get("path"), str):
                index.setdefault(r["path"], []).append(r)
        if cache is not None:
            cache["index"], cache["n"] = index, n
    rows = index.get(real, [])
    saw_stale, partial_why = False, set()
    for r in rows:
        if r.get("partial") or r.get("file_sha") is None:   # 部分読みは全文の証拠にしない。sha の無い行は上限超え＝大きさ
            partial_why.add(r.get("partial_why") or ("size" if r.get("file_sha") is None else "range"))
            continue
        if r.get("file_sha") == want:
            return "read", (f"フックの記録に全文読みが在る（{log.name} / sha {want[:12]}"
                            + (f" / agent {r['agent_id']}" if r.get("agent_id") else "") + "）")
        saw_stale = True
    if not rows:
        return "absent", f"フックの記録（{log.name}・{n} 行）に {doc} の読みが 1 件も無い"
    # **stale を partial より先に名乗る。** 部分読みと、古い版の全文読みが両方在るとき、
    # 回す側に要るのは「読み直せ」であって「全部読め」ではない——後者は既にやっている
    if saw_stale:
        return "stale", f"フックの記録の全文読みは今の {doc}（sha {want[:12]}）と一致しない——読んだ後に文書が変わった"
    if partial_why == {"size"}:
        return "partial", (f"{doc} は{PARTIAL_WHY['size']}なので、フックの記録は全文の証拠に"
                           "ならない——読み直しても変わらない")
    return "partial", ("フックの記録に在るのは部分読み（" + "・".join(PARTIAL_WHY.get(w, w) for w in sorted(partial_why))
                       + "）だけ——全文の証拠にならない")
