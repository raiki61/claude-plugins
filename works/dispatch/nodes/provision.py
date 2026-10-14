#!/usr/bin/env python3
"""provision ノード: PR ごとの作業場（clone と herdr の作業場）を、無ければ作り、有れば使い直す（設計書 3 節）。外に書く。

- clone のフォルダは `<clone_root>/<リポジトリの名前>-pr-<番号>`。herdr の作業場の名前も同じにそろえる。
- 無ければ: 元の clone（source）から clone し（中身はハードリンクで共有）、origin を元の clone の origin の URL へ向け直し、fetch し、
  copy_files（git が追わない手元だけのファイル）を写す。依存は入れない。枝を PR の枝へ移すのは /catchup に任せる。
- 有れば: origin が対象のリポジトリかを確かめて fetch だけする。違うリポジトリのフォルダなら触らずに provision_failed。
- herdr の作業場は、作業フォルダがその clone のペインを探して使い、無ければ開く。名前は人が見るためだけで、探すのに使わない
  （herdr の作業場の名前は重なっても止められず、作業場の ID は herdr の立ち上げ直しで変わるため）。
- 最後に、フォルダが対象のリポジトリの clone で、ペインが有ることを読み戻してから返す。

使い方: python3 nodes/provision.py --plan <plan の JSON> --number <PR 番号> [--config <パス>] [--repo OWNER/NAME] [--out <パス>]
"""

import argparse
import os
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import gitx  # noqa: E402
import herdr  # noqa: E402
import jsonio  # noqa: E402


def would(repo, number):
    """--dry-run の報告用: 作るか（create）使い直すか（reuse）。"""
    return "reuse" if os.path.exists(config.clone_path(repo, number)) else "create"


def _same(a, b):
    return os.path.realpath(a or "") == os.path.realpath(b or "")


def _pane_for(path, panes):
    return next((p for p in panes if _same(p.get("cwd"), path)), None)


def prepare(row, repo, h=herdr, g=gitx):
    path = row["clone_path"]
    out = {"number": row["number"], "path": path, "pane": None, "workspace": None,
           "created": False, "status": "provision_failed", "detail": None}
    notes = []
    try:
        if not os.path.exists(path):
            url = g.origin_url(repo.source)
            if not url:
                out["detail"] = f"元の clone {repo.source} に origin が無い"
                return out
            g.clone(repo.source, path)
            g.set_origin(path, url)
            g.fetch(path)
            out["created"] = True
            for rel in repo.copy_files:
                src = os.path.join(repo.source, rel)
                if not os.path.isfile(src):
                    notes.append(f"写すファイルが元の clone に無い: {rel}")
                    continue
                os.makedirs(os.path.dirname(os.path.join(path, rel)), exist_ok=True)
                shutil.copy2(src, os.path.join(path, rel))
        elif g.origin_repo(path) != repo.repo:
            out["detail"] = f"{path} は {repo.repo} の clone ではない（触らない）"
            return out
        else:
            g.fetch(path)

        pane = _pane_for(path, h.panes())
        if pane is None:
            made = h.create_workspace(path, os.path.basename(path))
            pane = {"pane_id": made.get("pane_id"), "workspace_id": made.get("workspace_id")}
        seen = _pane_for(path, h.panes())
    except (gitx.GitError, h.HerdrError, OSError) as e:
        out["detail"] = "／".join(notes + [str(e)])
        return out

    if g.origin_repo(path) != repo.repo or seen is None:
        out["detail"] = "／".join(notes + ["作った後の読み戻しで、clone かペインが見えない"])
        return out
    out.update(pane=seen.get("pane_id"), workspace=seen.get("workspace_id"), status="ready",
               detail="／".join(notes) or None)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--number", type=int, required=True)
    ap.add_argument("--config")
    ap.add_argument("--repo")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    repo = config.pick_repo(config.load(a.config, os.environ), a.repo)
    row = next(r for r in jsonio.load(a.plan)["plan"] if r["number"] == a.number and r["outcome"] == "assigned")
    jsonio.dump({"provision": prepare(row, repo)}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
