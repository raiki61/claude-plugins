#!/usr/bin/env python3
"""Stop のフック（裏で走る）: 会社の形が、前に表示を揃えた時から替わっていたら、その会社の部署と本社の属性と herdr の表示を
揃え直す（--sync と同じ中身を、その会社の分だけ。dispatch.sync_companies）。

会社の形（.claude/company.toml）の役の名前・fresh・会社の名前を替えても、herdr の表示（ペインの表示名・札・作業場の名前）は、
誰かが手で --sync を打つまで古いまま残った（my_notes で役の名前を 窓口 → 段取り に替えたとき。2026-10-17）。会社の形は origin の
既定のブランチから読む（tree.read_info）ので、替わるのはメインブランチに入った物が手元の origin のブランチに来た時（--land や本社の push の後、部署の
git fetch の後）。そのターンを終えた会話のこのフックが、どの道でメインブランチに入ったかに関わらず替わったことに気づく。

替わったかは、読んだ会社の形の中身の digest を、代表の clone の .git/company/shape-synced に控えた物と比べて決める。違えば揃え直し、
全部付け終えたら控えを書く（付けられなかった物があれば書かず、次のターンの終わりにもう一度揃える）。同じなら何もしない（会社の形を
読む git の 1 回だけ）。会社の形の無いリポジトリと git でない場所では何もしない。何度走っても同じ結果になる（--sync と同じ）。
裏で走るのでターンの終わりを待たせない。誤りは stderr に 1 行出し、会話は止めない。
"""

import hashlib
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    import config  # noqa: E402
    import gitx  # noqa: E402
    from nodes import tree  # noqa: E402
except (ImportError, SyntaxError) as _e:
    print(f"works-dispatch: 会社の形の替わりを herdr に揃えるフックを動かせない（Python 3.11 以上が要る: {_e}）", file=sys.stderr)
    sys.exit(0)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def mark_path(common):
    """前に表示を揃えた会社の形の digest の控え。"""
    return os.path.join(common, "company", "shape-synced")


def _sync(config_path, root):
    import dispatch   # 替わったときだけ読む（全部の部品を読むので重い）
    return dispatch.sync_companies(config_path, dispatch.Ports(), only=root)


def run(payload, env=os.environ, sync=_sync):
    """替わっていれば揃え直す。(揃え直したか, 出す行の並び)。"""
    cwd = payload.get("cwd") or os.getcwd()
    common = gitx.common_dir(cwd)
    if not common:
        return False, []
    root = gitx.root_of(common)
    config_path = gitx.worktree_attrs(cwd).get("config")
    info = tree.read_info(root, os.path.dirname(config.path_of(config_path, env)))
    if not info.get("text"):
        return False, []
    digest = hashlib.sha256(info["text"].encode("utf-8")).hexdigest()
    mark = mark_path(common)
    try:
        with open(mark, encoding="utf-8") as f:
            if f.read().strip() == digest:
                return False, []
    except OSError:
        pass
    lines, rc = sync(config_path, root)
    if rc != 0:
        return True, lines
    os.makedirs(os.path.dirname(mark), exist_ok=True)
    with open(mark, "w", encoding="utf-8") as f:
        f.write(digest)
    return True, []


def main(stdin=sys.stdin, env=os.environ):
    try:
        payload = json.loads(stdin.read() or "{}") or {}
    except ValueError:
        payload = {}
    try:
        _, lines = run(payload if isinstance(payload, dict) else {}, env)
    except Exception as e:  # フックの誤りで会話を止めない
        lines = [str(e)]
    if lines:
        print("works-dispatch: 会社の形の替わりを herdr に揃え切れなかった（次のターンの終わりにもう一度揃える。手でなら --sync）: "
              + " / ".join(lines), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
