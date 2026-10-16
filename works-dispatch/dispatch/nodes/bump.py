#!/usr/bin/env python3
"""bump ノード: Claude Code のプラグインの marketplace（`.claude-plugin/marketplace.json` に plugins[] を並べるリポジトリ）で、
中身を変えたのに版が据え置きのプラグインの版を上げる commit を作る。外に書く（その場所のファイルと commit）。

取り込みの命令（入口の --land）が、会社の形の land.bump = "marketplace" のときに、本流に入れる前の一時の場所で呼ぶ。
部署が版を上げずに出し、取り込むときに上げると、同じ版の番号を付けた部署どうしがぶつからない（会社の形の設計 8 章）。

決まりは、版の出し方の決まり（marketplace のリポジトリの docs/releasing.md の形）に合わせた。
- 据え置き: プラグインの置き場（plugins[].source）のファイルを、その plugin.json の version を今の値にした commit より後に
  変えた commit が有る（その marketplace の試験 VERSION_BUMP_OK と同じ数え方）。
- 上げ幅: そのプラグインの CHANGELOG.md の `## [Unreleased]` に Added・Changed・Deprecated・Removed の節が有れば
  minor（x.Y.0）、無ければ patch（x.y.Z）。marketplace の metadata.version は、minor を上げたプラグインが 1 つでも有れば minor、
  無ければ patch。
- 同じ commit で、plugin.json の version・marketplace.json の metadata.version・CHANGELOG.md の `## [Unreleased]` の中身を
  `## [<版>] - <日付>` の下へ移す（`## [Unreleased]` の見出しは空で残す）。
- 件名は `chore(<名前>, …): 版を上げる（<名前> <版> / … / marketplace <版>）`。
ファイルの書き換えは字の置き換えで、JSON の並びと字下げを崩さない。
"""

import json
import posixpath
import re

MARKETPLACE = ".claude-plugin/marketplace.json"
PLUGIN = ".claude-plugin/plugin.json"
MINOR = ("Added", "Changed", "Deprecated", "Removed")
_VERSION = re.compile(r'("version"\s*:\s*")(\d+)\.(\d+)\.(\d+)(")')
_META = re.compile(r'("metadata"\s*:\s*\{[^{}]*?"version"\s*:\s*")(\d+)\.(\d+)\.(\d+)(")', re.S)


class BumpError(Exception):
    pass


def _read(root, rel):
    with open(posixpath.join(root, rel), encoding="utf-8") as f:
        return f.read()


def _write(root, rel, text):
    with open(posixpath.join(root, rel), "w", encoding="utf-8", newline="") as f:
        f.write(text)


def raise_version(version, level):
    major, minor, patch = (int(x) for x in version.split("."))
    return f"{major}.{minor + 1}.0" if level == "minor" else f"{major}.{minor}.{patch + 1}"


def stale(root, plugins, g):
    """版が据え置きのプラグインの {名前: 置き場}。版を最後に変えた commit を、今の版を持つ commit が続く一番古い物とする。"""
    out = {}
    for p in plugins:
        src = posixpath.normpath(p["source"])
        pj = posixpath.join(src, PLUGIN)
        now = json.loads(_read(root, pj)).get("version")
        bump = None
        for c in g.commits_touching(root, pj):
            if json.loads(g.file_at(root, c, pj) or "{}").get("version") != now:
                break
            bump = c
        if bump is not None and g.commits_touching(root, src, since=bump):
            out[p["name"]] = src
    return out


def unreleased(text):
    """CHANGELOG の本文から (Unreleased の見出しの行の位置, 次の版の見出しの行の位置, 行の並び)。見出しが無ければ BumpError。"""
    lines = text.splitlines(keepends=True)
    head = next((i for i, line in enumerate(lines) if line.strip() == "## [Unreleased]"), None)
    if head is None:
        raise BumpError("CHANGELOG.md に `## [Unreleased]` の見出しが無い")
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## [")), len(lines))
    return head, end, lines


def level_of(text):
    head, end, lines = unreleased(text)
    return "minor" if any(line.strip() in (f"### {s}" for s in MINOR) for line in lines[head + 1:end]) else "patch"


def move_unreleased(text, version, date):
    head, end, lines = unreleased(text)
    body = "".join(lines[head + 1:end]).strip("\n")
    block = f"## [{version}] - {date}\n" + (f"\n{body}\n" if body else "")
    rest = "".join(lines[end:])
    return "".join(lines[:head]) + "## [Unreleased]\n\n" + block + ("\n" + rest if rest else "")


def plan(root, g):
    """上げる物の並び [{name, source, old, new, level}] と、marketplace の (old, new)。据え置きが無ければ ([], None)。"""
    mk = json.loads(_read(root, MARKETPLACE))
    plugins = [p for p in mk.get("plugins", []) if isinstance(p.get("source"), str) and p["source"].startswith("./")]
    rows = []
    for name, src in sorted(stale(root, plugins, g).items()):
        old = json.loads(_read(root, posixpath.join(src, PLUGIN)))["version"]
        level = level_of(_read(root, posixpath.join(src, "CHANGELOG.md")))
        rows.append({"name": name, "source": src, "old": old, "new": raise_version(old, level), "level": level})
    if not rows:
        return [], None
    m = _META.search(_read(root, MARKETPLACE))
    if not m:
        raise BumpError(f"{MARKETPLACE} に metadata.version が無い")
    old = ".".join(m.group(2, 3, 4))
    return rows, (old, raise_version(old, "minor" if any(r["level"] == "minor" for r in rows) else "patch"))


def apply(root, rows, market, date):
    """plan の結果をファイルに書き、commit の件名を返す。"""
    for r in rows:
        pj = posixpath.join(r["source"], PLUGIN)
        _write(root, pj, _VERSION.sub(lambda m: m.group(1) + r["new"] + m.group(5), _read(root, pj), count=1))
        cl = posixpath.join(r["source"], "CHANGELOG.md")
        _write(root, cl, move_unreleased(_read(root, cl), r["new"], date))
    _write(root, MARKETPLACE, _META.sub(lambda m: m.group(1) + market[1] + m.group(5), _read(root, MARKETPLACE), count=1))
    names = ", ".join(r["name"] for r in rows)
    versions = " / ".join(f"{r['name']} {r['new']}" for r in rows)
    return f"chore({names}): 版を上げる（{versions} / marketplace {market[1]}）"


def make(root, date, g):
    """据え置きのプラグインの版を上げて commit する。{sha, subject, rows, marketplace}。据え置きが無ければ sha は None。"""
    rows, market = plan(root, g)
    if not rows:
        return {"sha": None, "subject": None, "rows": [], "marketplace": None}
    subject = apply(root, rows, market, date)
    return {"sha": g.commit_all(root, subject), "subject": subject, "rows": rows, "marketplace": market[1]}
