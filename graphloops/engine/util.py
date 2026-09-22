"""engine の小道具——時刻・hash・JSON の読み書き・git・path の辿り方。ループの中身を知らない。"""
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent
# 役の名前・段の名前・道具の名前・プラグイン名は engine に書かない——graph の runners / thickness.tiers / deliver.path_tools / plugin が正本


class Reject(Exception):
    """受け付けない（exit 1）。直して呼び直せる。"""


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def die(msg, code=2):
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


def git(*args, env=None):
    """成功なら stdout、失敗（git が無い・非 0・時間切れ）なら None。呼ぶ側は None を『分からない』として扱い、合格に倒さない。

    `env` は**足す**（置き換えない）。GIT_INDEX_FILE を渡して一時 index の上で組み立てる呼びが 1 つ在る
    ——intent-to-add の index では stash create も write-tree も非 0 で返るので、本物の index を避ける道が要る。
    置き換えにすると PATH も HOME も消えて git ごと動かなくなるので、os.environ の写しに足す形で固定する。
    """
    args = (*_repo_args(), *args)
    run_env = {**os.environ, **env} if env else None
    try:
        # errors=replace: 対象リポジトリに非 UTF-8 のテキストが 1 本でも在ると、復号の例外が『失敗なら None』の契約を
        # 迂回して総括例外で落ちた（実測 2026-09-13: next が exit 2 でどの周にも進めない）。置換文字で読み、落とさない
        r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=GIT_TIMEOUT, env=run_env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


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
