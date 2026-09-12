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


GIT_TIMEOUT = 120  # 秒。近傍の scripts/comment-ratio.sh と同じ上限


def git(*args):
    """成功なら stdout、失敗（git が無い・非 0・時間切れ）なら None。呼ぶ側は None を『分からない』として扱い、合格に倒さない。"""
    try:
        # errors=replace: 対象リポジトリに非 UTF-8 のテキストが 1 本でも在ると、復号の例外が『失敗なら None』の契約を
        # 迂回して総括例外で落ちた（実測 2026-09-13: next が exit 2 でどの周にも進めない）。置換文字で読み、落とさない
        r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def git_bytes(*args):
    """成功なら stdout の**生バイト**、失敗なら None。突合（sha）に使う——git() の errors=replace は復号できない
    バイトを種類に依らず U+FFFD 1 文字に写すので、等長の非 UTF-8 書き換えが同じ文字列＝同じ sha になる
    （実測 2026-09-13: b"caf\xe9 \xff" と b"caf\xc3 \xfe" が一致）。貼る用は落としてよい／突合用は落としてはいけない。"""
    try:
        r = subprocess.run(["git", *args], capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def porcelain():
    """作業ツリーの写し。None = git が効かない（作業ツリーの保護はできない——呼ぶ側が止める）。"""
    out = git("status", "--porcelain")
    return None if out is None else sorted(out.splitlines())


def get_path(obj, path):
    """`a.b.c` で辿る。節名に点が入る（out.p0.question.x）ので、辞書の鍵は最長一致で食う。"""
    parts = path.split(".")
    cur = obj
    i = 0
    while i < len(parts):
        if isinstance(cur, dict):
            for j in range(len(parts), i, -1):
                key = ".".join(parts[i:j])
                if key in cur:
                    cur = cur[key]
                    i = j
                    break
            else:
                raise KeyError(path)
        elif isinstance(cur, list) and parts[i].isdigit() and int(parts[i]) < len(cur):
            cur = cur[int(parts[i])]
            i += 1
        else:
            raise KeyError(path)
    return cur


def set_path(obj, path, value):
    parts = path.split(".")
    cur = obj
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


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
