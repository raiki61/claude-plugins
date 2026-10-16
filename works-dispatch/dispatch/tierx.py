"""要る道具の段の点検（tiers プラグインの bin/tiers）への口。

works-dispatch の要る段は 2（gh で自分の番の PR を集め、herdr に作業場を開き、アカウントの起こし方の命令で Claude Code を起こす）。
点検の中身は tiers が持ち、ここは呼んで JSON を読むだけ。tiers は plugin.json の dependencies で入り、Claude Code が
その bin/ を Bash の道具の PATH に入れる。リポジトリの checkout から走らせるとき（試験・開発）は、隣の tiers/bin/tiers を使う。
依存は claude plugin install のほか /reload-plugins・入れ直し・自動更新では入るが、claude plugin update では入らない
（公式の文書 code.claude.com/docs/en/plugins/dependencies の「Besides claude plugin install」の節。2026-10-16 に 2.1.301 で再現）。
なので、無いときは入れる命令をそのまま出す。
"""

import json
import os
import pathlib
import subprocess
import sys

NEEDED_TIER = 2
NAME = "tiers"


class TierError(Exception):
    pass


def install_command(here=None):
    """tiers を入れる命令。マーケットプレイスの名はこのプラグインの plugin.json の dependencies から読む（決め打ちしない）。"""
    root = pathlib.Path(here or __file__).resolve().parent.parent
    market = "<works-dispatch を入れたマーケットプレイス>"
    try:
        deps = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("dependencies") or []
    except (OSError, ValueError, AttributeError):
        deps = []
    for d in deps:
        if isinstance(d, dict) and d.get("name") == NAME and d.get("marketplace"):
            market = d["marketplace"]
    return f"claude plugin install {NAME}@{market}"


def locate(env, here=None):
    """tiers の入口のパス（無ければ None）。PATH の上の、拡張子の無い Python の台本を探す（Windows の which は拡張子で探すので使わない）。"""
    for d in (env.get("PATH") or "").split(os.pathsep):
        p = os.path.join(d, NAME) if d else ""
        if p and os.path.isfile(p):
            return p
    here = pathlib.Path(here or __file__).resolve().parent
    sibling = here.parent.parent / "tiers" / "bin" / NAME
    return str(sibling) if sibling.is_file() else None


def check(launchers, env=None, runner=subprocess.run, here=None):
    """段 NEEDED_TIER の点検の結果（tiers の --json の dict）。入口が無い・読めない出力は TierError。"""
    env = dict(os.environ if env is None else env)
    entry = locate(env, here)
    if entry is None:
        raise TierError("段の点検の部品（tiers プラグインの bin/tiers）が見つからない。works-dispatch の依存だが、"
                        f"claude plugin update では入らない。シェルで {install_command(here)} を打ち、"
                        "開いている会話では /reload-plugins を打つ")
    argv = [sys.executable, entry, "--tier", str(NEEDED_TIER), "--json"]
    for c in launchers:
        argv += ["--launcher", c]
    p = runner(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    try:
        got = json.loads(p.stdout)
    except (TypeError, ValueError):
        raise TierError(f"段の点検（{entry}）の出力が JSON でない（終了コード {p.returncode}）: {(p.stdout or p.stderr or '').strip()[:200]}")
    if not isinstance(got, dict) or got.get("schema") != 1 or not isinstance(got.get("checks"), list):
        raise TierError(f"段の点検（{entry}）の出力の形が違う（schema 1 を待つ）")
    return got


def problems(result):
    """足りない物ごとに 1 行（入れ方を添える）。"""
    out = []
    for x in result["checks"]:
        if not x.get("ok"):
            fix = " / ".join(x.get("fix") or [])
            out.append(f"段 {x.get('tier')} {x.get('name')}: {x.get('problem')}" + (f"（入れ方（手で）: {fix}）" if fix else ""))
    return out


def report(result):
    """--check に出す行。足りない物ごとに 1 行（problems）と、その下に tiers の案内（guide。tiers 0.2.0 から。無ければ出さない）を
    字下げで並べ、終わりに、同じ案内を人の読む形で出す命令を 1 行足す。"""
    out = []
    for line, x in zip(problems(result), (x for x in result["checks"] if not x.get("ok"))):
        out.append(f"- {line}")
        out.extend(f"  - {g}" for g in x.get("guide") or [] if isinstance(g, str) and g.strip())
    if out:
        out.append("詳しい案内は /tiers:check で見られる")
    return out
