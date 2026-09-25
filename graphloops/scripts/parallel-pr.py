"""並行 PR の交差を数える（review-loop の p0.parallel_pr を engine が走らせるときの語。engine に同梱）。

手順の正本は prompts/review-loop/p0.parallel_pr.md の 2〜5 段（1 段の owner/repo の解決は rules が済ませて --repo で渡す）:
自分の PR を headRefOid で除外し、--limit 100 の打ち切りを見て、残った PR の変更ファイルと --changed の集合の交差を取る。
6 段（交差した hunk を読んで担当の PR に申し送る）は判断なのでここではしない——交差があれば rules が任せ先の節に回す。
gh は必ず -R で呼ぶ（cwd の remote から解決させない）。読むだけで、書き込みはしない。

印字は 1 つの JSON: {repo, listed, truncated, conflicts: [{pr, files}]}。gh が失敗したら理由を標準エラーに書いて exit 1。
"""
import argparse
import json
import shutil
import subprocess
import sys

LIMIT = 100


GH = "gh"


def gh(*args):
    r = subprocess.run([GH, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        sys.stderr.write(f"gh {' '.join(args[:3])} が exit {r.returncode}: {r.stderr.strip()[-400:]}\n")
        sys.exit(1)
    return r.stdout


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--changed", required=True, help="交差を取る変更ファイルの一覧（1 行 1 ファイル）")
    a = p.parse_args()
    global GH
    # PATH から引いた実体で起こす（Windows では名前だけだと .exe しか探さない——which は PATHEXT を見る）。
    # 実体を引数で受けない: 引数は data だけにして、承認なしで走る同梱の語が別の実行形式を起こす口を作らない
    GH = shutil.which("gh") or "gh"
    with open(a.changed, encoding="utf-8") as f:
        mine = {ln.strip() for ln in f if ln.strip()}
    prs = json.loads(gh("pr", "list", "-R", a.repo, "--limit", str(LIMIT), "--json", "number,headRefName,headRefOid"))
    others = [pr for pr in prs if pr.get("headRefOid") != a.head]
    conflicts = []
    for pr in others:
        files = {ln.strip() for ln in gh("pr", "view", str(pr["number"]), "-R", a.repo, "--json", "files",
                                         "--jq", ".files[].path").splitlines() if ln.strip()}
        hit = sorted(files & mine)
        if hit:
            conflicts.append({"pr": str(pr["number"]), "files": hit})
    print(json.dumps({"repo": a.repo, "listed": len(prs), "truncated": len(prs) >= LIMIT, "conflicts": conflicts},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
