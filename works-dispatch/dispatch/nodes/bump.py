#!/usr/bin/env python3
"""bump ノード: Claude Code のプラグインの marketplace（`.claude-plugin/marketplace.json` に plugins[] を並べるリポジトリ）で、
中身を変えたのに版が据え置きのプラグインの版を上げる commit を作る。外に書く（その場所のファイルと commit）。

取り込みの命令（入口の --land）が、会社の形の land.bump = "marketplace" のときに、本流に入れる前の一時の場所で呼ぶ。
部署が版を上げずに出し、取り込むときに上げると、同じ版の番号を付けた部署どうしがぶつからない（会社の形の設計 8 章）。

決まりは、版の出し方の決まり（marketplace のリポジトリの docs/releasing.md の形）に合わせた。
- 据え置き: プラグインの置き場（plugins[].source）のファイルを、その plugin.json の version を今の値にした commit より後に
  変えた commit が有る（その marketplace の試験 VERSION_BUMP_OK と同じ数え方）。
- 上げ幅: そのプラグインの CHANGELOG.md の `## [Unreleased]` に Added・Changed・Deprecated・Removed の節が有れば
  minor（x.Y.0）、無ければ patch（x.y.Z）。ただし版を最後に上げた後に変えたファイルが試験と文書だけ（QUIET。利用者が動かす物を
  変えていない）なら、節によらず patch（Semantic Versioning の minor は「後方互換のある機能の追加」で、試験と文書だけの直しは
  当たらない）。marketplace の metadata.version は、minor を上げたプラグインが 1 つでも有れば minor、無ければ patch。
- 同じ commit で、plugin.json の version・marketplace.json の metadata.version・CHANGELOG.md の `## [Unreleased]` の中身を
  `## [<版>] - <日付>` の下へ移す（`## [Unreleased]` の見出しは空で残す）。
- 件名は `chore(<名前>, …): 版を上げる（<名前> <版> / … / marketplace <版>）`。
- 中身の無い版は作らない: 据え置きのプラグイン（版を最後に上げた後に、フォルダの中のファイルを変えた物）の
  `## [Unreleased]` に見出し（`### Fixed` のような `#` で始まる行）でない行が 1 つも無ければ、版を上げずに BumpError で止める（利用者に効く違いを書き足してから打ち直す）。版を上げずに通す道は用意しない——
  marketplace は版が変わった時だけ中身を取り直すので、上げなければ変えた中身が利用者に届かず、版の据え置きを
  main・release/* の CI で赤にするリポジトリの試験（tests/run.sh の VERSION_BUMP_OK）も赤にする。見出しだけの版は、何が変わったかを記録が答えないまま利用者に取り直させる。
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
    """版が据え置きのプラグインの {名前: (置き場, 版を最後に変えた commit)}。版を最後に変えた commit を、今の版を持つ commit が
    続く一番古い物とする。"""
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
            out[p["name"]] = (src, bump)
    return out


def unreleased(text):
    """CHANGELOG の本文から (Unreleased の見出しの行の位置, 次の版の見出しの行の位置, 行の並び)。見出しが無ければ BumpError。"""
    lines = text.splitlines(keepends=True)
    head = next((i for i, line in enumerate(lines) if line.strip() == "## [Unreleased]"), None)
    if head is None:
        raise BumpError("CHANGELOG.md に `## [Unreleased]` の見出しが無い")
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## [")), len(lines))
    return head, end, lines


def has_entries(text):
    """`## [Unreleased]` の下に、見出しでない中身の行が有るか。"""
    head, end, lines = unreleased(text)
    return any(line.strip() and not line.lstrip().startswith("#") for line in lines[head + 1:end])


def quiet(path, src):
    """プラグインの置き場 src の下のファイル path（リポジトリの根からの相対）が、試験か文書か（利用者が動かす物でないか）。
    試験は tests・test のフォルダの下と test_*.py・*_test.py・conftest.py、文書は docs のフォルダの下と、置き場の直下の
    README.md・CHANGELOG.md・CONTRIBUTING.md・LICENSE。SKILL.md やエージェントの .md は、Claude Code が読んで動く物なので文書に数えない。"""
    rel = posixpath.relpath(path, src)
    parts = rel.split("/")
    name = parts[-1]
    if any(d in ("tests", "test", "docs") for d in parts[:-1]):
        return True
    if name.startswith("test_") and name.endswith(".py") or name.endswith("_test.py") or name == "conftest.py":
        return True
    return len(parts) == 1 and name in ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", "LICENSE")


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
    """上げる物の並び [{name, source, old, new, level, why（上げ幅を記録の節と違えた訳か None）}] と、marketplace の (old, new)。据え置きが無ければ ([], None)。
    据え置きのどれかの `## [Unreleased]` に中身が無ければ BumpError（ファイルは書かない）。"""
    mk = json.loads(_read(root, MARKETPLACE))
    plugins = [p for p in mk.get("plugins", []) if isinstance(p.get("source"), str) and p["source"].startswith("./")]
    rows, empty = [], []
    for name, (src, since) in sorted(stale(root, plugins, g).items()):
        old = json.loads(_read(root, posixpath.join(src, PLUGIN)))["version"]
        log = _read(root, posixpath.join(src, "CHANGELOG.md"))
        if not has_entries(log):
            empty.append(f"{name}（{src}/CHANGELOG.md）")
            continue
        level, why = level_of(log), None
        if level == "minor" and all(quiet(f, src) for f in g.changed_paths(root, since, src)):
            level, why = "patch", "変えたのは試験と文書だけなので、記録の節によらず patch"
        rows.append({"name": name, "source": src, "old": old, "new": raise_version(old, level), "level": level, "why": why})
    if empty:
        raise BumpError(f"版を最後に上げた後に中身を変えたのに、`## [Unreleased]` に利用者に効く違いが書いてない: {'、'.join(empty)}。"
                        "中身の無い版は作らないので、違いを書き足して commit してから打ち直す")
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
