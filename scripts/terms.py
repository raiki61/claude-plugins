#!/usr/bin/env python3
"""リポジトリの文に、IT の定着語でない言い方が増えていないかを確かめる。

語の一覧と見つけ方は works-dispatch/dispatch/terms.py（持ち主の CLAUDE.md の「日本語は IT 業界の定着語を使う」を守らせる辞書）。
まだ直していないファイルがあるので、ファイルごとの件数を基準（scripts/terms-baseline.json）に控え、基準より増えたら止める。
減ったときも、基準を書き直すまで止める（減った分をそのまま残すと、後で同じ数まで増やせてしまう。betterer の CI の回と同じ
考え: https://phenomnomnominal.github.io/betterer/docs/running-betterer-in-ci ）。

見ないもの: works/ と works-factory/（誰の受け持ちでもない）、変更の記録（CHANGELOG.md）・ADR（docs/adr/）・日付の付いた記録
（docs/specs・docs/trials などの 2026-… のファイル）と組織の改善の台帳（docs/reform/ledger.md）は当時の言葉の記録なので書き換えない、写しの部品（vendor/）、
辞書そのもの。

使い方:
    python3 scripts/terms.py            # 確かめる（会社の形 .claude/company.toml の [land] の check が呼ぶ）
    python3 scripts/terms.py --update   # 今の件数を基準に書く（直してファイルの件数が減ったとき）
    python3 scripts/terms.py --list <パス>...  # そのファイルの当たった行を出す（直すときは works-dispatch/dispatch/terms.py --fix）

終了コード: 0 = 基準どおり / 1 = 基準と違う
"""
import importlib.util
import json
import pathlib
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts" / "terms-baseline.json"
_spec = importlib.util.spec_from_file_location("terms", ROOT / "works-dispatch" / "dispatch" / "terms.py")
terms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(terms)

SUFFIXES = (".md", ".py", ".toml", ".sh", ".json", ".yaml", ".yml")
SKIPPED = re.compile(r"^(works|works-factory)/|(^|/)CHANGELOG\.md$|(^|/)docs/adr/|(^|/)vendor/|/20\d\d-\d\d-\d\d[^/]*$|^docs/reform/ledger\.md$"
                     r"|^works-dispatch/dispatch/terms\.py$|^works-dispatch/dispatch/tests/test_terms\.py$|^scripts/terms")


def counts():
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    out = {}
    for path in sorted(x for x in files.split("\0") if x.endswith(SUFFIXES) and not SKIPPED.search(x)):
        try:
            n = len(terms.text_problems((ROOT / path).read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
        if n:
            out[path] = n
    return out


def main(argv):
    if argv[:1] == ["--list"]:
        for p in argv[1:]:
            for n, found, expected in terms.text_problems((ROOT / p).read_text(encoding="utf-8")):
                print(f"{p}:{n}: 「{found}」→「{expected}」")
        return 0
    now = counts()
    if argv[:1] == ["--update"]:
        BASELINE.write_text(json.dumps(now, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"基準を書いた: {len(now)} ファイル・{sum(now.values())} 件")
        return 0
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    more = [(p, base.get(p, 0), n) for p, n in now.items() if n > base.get(p, 0)]
    less = [(p, n, now.get(p, 0)) for p, n in base.items() if now.get(p, 0) < n]
    for p, was, n in more:
        print(f"増えた: {p}（基準 {was} 件 → {n} 件）。python3 scripts/terms.py --list {p} で行を見て、"
              f"python3 works-dispatch/dispatch/terms.py --fix {p} で直す")
    for p, was, n in less:
        print(f"減った: {p}（基準 {was} 件 → {n} 件）。python3 scripts/terms.py --update で基準を書き直して commit する")
    if more or less:
        return 1
    print(f"TERMS_OK 基準どおり（{len(now)} ファイル・{sum(now.values())} 件が直し待ち）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
