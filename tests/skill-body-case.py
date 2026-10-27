#!/usr/bin/env python3
"""全部のプラグインのスキルとコマンドの本文が、スキルの書き方の標準（docs/standards/skill-authoring.md）の決まり 1・4・5 を守るかを見る。

本文は呼ばれたときに丸ごと会話に載り、自動の圧縮の後は頭の 5,000 トークンだけが付け直される（https://code.claude.com/docs/en/skills）。
長すぎる本文は、圧縮の後に後ろの手順を失ったまま動く。指した別ファイルが無いと、読みに行った所で止まるか推測で埋める。

使い方: python3 tests/skill-body-case.py <場合>
- tree: marketplace に載る全部のプラグイン（.claude-plugin/marketplace.json の source）の skills/*/SKILL.md と commands/**/*.md を見る。
  プラグインのルートより深い所の物（works の .shared/borrow/ に写した第三者のスキルなど）は Claude Code のスキルとして読み込まれないので見ない
- arms: 下の検査の 1 つずつが、壊した例で落ち、壊していない例で通ることを見る（チェックが空振りしていないか）

見ること:
- 長さ（決まり 1）: 本文（頭の YAML の後ろ）が 500 行未満。字数は見ない
- 無い先（決まり 4）: 本文から相対パスの Markdown のリンクで指した先が在る。コードの中（``` の塊と ` の中）のリンクの形は見ない
- ルートの外（決まり 4）: 指した先がプラグインのルートの中に在る。marketplace から入れたプラグインはルートの中だけが手元に写され、
  ルートの外のファイルは利用者の手元に無い（https://code.claude.com/docs/en/plugins/loading#in-place-and-copied-plugins）
- 目次（決まり 5）: スキルのフォルダの中の .md の別ファイルで 100 行を超える物は、頭の 20 行以内の箇条書きに、そのファイルの
  見出し（##）を全部並べる。スクリプトは読まずに走らせる物なので見ない

今 標準を満たさない物は EXEMPT に載せて緑で始める。載せた物が標準を満たしたら赤で知らせるので、EXEMPT から消す
（残すと、後で崩れても見えない。配る形の標準の検査 MANIFEST_STANDARD_OK と同じ形）。
"""

import json
import os
import pathlib
import re
import sys
import tempfile
import urllib.parse

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
STANDARD = "docs/standards/skill-authoring.md"
BODY_LINES_LIMIT = 500  # 決まり 1。500 行「未満」
TOC_OVER = 100          # 決まり 5。100 行を「超える」別ファイル
TOC_HEAD = 20           # 決まり 5。目次を置く頭の行数
CUSTOM_PATHS = ("skills", "commands")

# 今 標準を満たさない物と、満たさない決まり（2026-10-18 の測り。各担当に分けの直しを標準が頼んである。docs/standards/README.md の台帳の 2 回目）
EXEMPT = {
}

FRONT = re.compile(r"\A---[ \t]*\n(.*?\n)?---[ \t]*(?:\n|\Z)", re.S)
# 字下げは問わない（箇条書きの中の塊は 4 字以上字下げする）
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(`+)(?:.+?)\1")
LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+[\"'(][^)]*)?\)")
REF_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
HEADING2 = re.compile(r"^##[ \t]+(.+?)[ \t#]*$")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)")
LINK_TEXT = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def body_of(text):
    """頭の YAML を除いた本文。頭が無ければ全体。"""
    m = FRONT.match(text)
    return text[m.end():] if m else text


def prose_lines(text):
    """コードの塊（``` と ~~~）の外の行を、(行の番号, 行) で返す。塊の閉じは開きと同じ字で、同じ長さ以上の列。"""
    fence = None
    for i, line in enumerate(text.split("\n")):
        m = FENCE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                continue
            yield i, line
        elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)):]:
            fence = None


def link_targets(body):
    """本文の相対パスのリンクの先（# と ? の後ろを除き、%xx を戻した物）。URL・ページの中の # だけ・絶対パス・置き換えの変数は除く。"""
    found = []
    for _, line in prose_lines(body):
        line = INLINE_CODE.sub("", line)
        for raw in LINK.findall(line) + REF_DEF.findall(line):
            t = raw[1:-1] if raw.startswith("<") else raw
            if not t or SCHEME.match(t) or t.startswith(("#", "/")) or "${" in t:
                continue
            t = urllib.parse.unquote(re.split(r"[#?]", t, maxsplit=1)[0])
            if t:
                found.append(t)
    return found


def plain(s):
    """見出しと目次の項を比べる形（リンクは字だけ・` と ** を除き・空白を詰める）。"""
    return " ".join(LINK_TEXT.sub(r"\1", s).replace("`", "").replace("**", "").split())


def toc_gap(text):
    """100 行を超える別ファイルの目次の欠け（揃えば None）。目次の項は、見出しの字そのものか、見出しの字の後ろに区切り（空白・—・：・（）を置いて添え書きを続けた物。"""
    text = body_of(text)
    heads = [plain(m.group(1)) for _, line in prose_lines(text) if (m := HEADING2.match(line))]
    if not heads:
        return "見出し（##）が 1 つも無い（頭の目次に並べる見出しを立てる）"
    items = [plain(m.group(1)) for line in text.split("\n")[:TOC_HEAD] if (m := BULLET.match(line))]
    miss = [h for h in heads if not any(i == h or (i.startswith(h) and i[len(h)] in " —:：（(") for i in items)]
    if miss:
        return f"頭の {TOC_HEAD} 行の箇条書きに、見出し「{'」「'.join(miss[:3])}」{'など' if len(miss) > 3 else ''}が無い"
    return None


def check_file(path, plugin_root, kind):
    """1 つのファイルの食い違いを (決まりの名前, 文) の list で返す。kind は skill・command。"""
    text = path.read_text(encoding="utf-8").removeprefix("﻿")
    body = body_of(text)
    bad = []
    lines = len(body.splitlines())
    if lines >= BODY_LINES_LIMIT:
        bad.append(("長さ", f"本文が {lines} 行（{BODY_LINES_LIMIT} 行未満。決まり 1）"))
    # ルートの中かは、書いたパスの .. を畳んで見る（シンボリックリンクは辿らない。marketplace の中の繋ぎは写すときに扱われる）
    root = os.path.normpath(os.path.abspath(plugin_root))
    for t in link_targets(body):
        dest = pathlib.Path(os.path.normpath(os.path.join(os.path.abspath(path.parent), t)))
        if not dest.is_relative_to(root):
            bad.append(("ルートの外", f"リンク {t} がプラグインのルートの外を指す。入れた利用者の手元にはルートの中だけが写されるので、"
                                  "ルートの中に写すか、GitHub の URL で指す（決まり 4）"))
        elif not dest.exists():
            bad.append(("無い先", f"リンク {t} の先が無い（決まり 4）"))
    if kind == "skill":
        for side in sorted(path.parent.rglob("*.md")):
            if side == path:
                continue
            st = side.read_text(encoding="utf-8").removeprefix("﻿")
            n = len(st.splitlines())
            if n > TOC_OVER and (gap := toc_gap(st)):
                bad.append(("目次", f"{side.relative_to(path.parent).as_posix()} は {n} 行で、{gap}（決まり 5）"))
    return bad


def targets(root):
    """(ファイル, プラグインのルート, kind) の list と、走査そのものの食い違いの list を返す。"""
    market = json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    found, bad = [], []
    for plugin in market["plugins"]:
        src = root / plugin["source"]
        manifest = src / ".claude-plugin" / "plugin.json"
        declared = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
        custom = [k for k in CUSTOM_PATHS if k in declared]
        if custom:
            bad.append(f"{plugin['name']}: plugin.json が置き場（{', '.join(custom)}）を変えている。このチェックの走査も合わせて直す")
        mine = ([(f, src, "skill") for f in sorted(src.glob("skills/*/SKILL.md"))]
                + [(f, src, "command") for f in sorted(src.glob("commands/**/*.md"))])
        found += mine
    if not found:
        bad.append("スキルもコマンドも 1 つも見つからない（走査が空回りしている）")
    return found, bad


def scan(root, exempt):
    found, bad = targets(root)
    seen = set()
    for path, src, kind in found:
        rel = path.relative_to(root).as_posix()
        seen.add(rel)
        got = check_file(path, src, kind)
        allowed = exempt.get(rel, set())
        bad += [f"{rel}: {msg}（{STANDARD}）" for rule, msg in got if rule not in allowed]
        cleared = sorted(allowed - {rule for rule, _ in got})
        if cleared:
            bad.append(f"{rel}: 決まり「{'」「'.join(cleared)}」を満たしたので、tests/skill-body-case.py の EXEMPT から消す")
    bad += [f"{rel}: EXEMPT に載っているが、スキルにもコマンドにも無い（EXEMPT から消す）" for rel in sorted(set(exempt) - seen)]
    return found, bad


def tree():
    found, bad = scan(ROOT, EXEMPT)
    if bad:
        print("\n".join(bad))
        return 1
    print(f"SKILL_BODY_OK {len(found)} 件（外す一覧に {len(EXEMPT)} 件）")
    return 0


def arms():
    with tempfile.TemporaryDirectory() as tmp:
        return _arms(pathlib.Path(tmp))


def _arms(d):

    def probe(files, kind="skill"):
        """files は {プラグインのルートからの相対パス: 中身}。最初の物を見る。"""
        r = d / f"p{len(list(d.iterdir()))}"
        for rel, body in files.items():
            (r / rel).parent.mkdir(parents=True, exist_ok=True)
            (r / rel).write_text(body, encoding="utf-8")
        return [rule for rule, _ in check_file(r / next(iter(files)), r, kind)]

    def must(why, want, files, kind="skill"):
        got = probe(files, kind)
        assert got == want, f"{why}: {want} のはずが {got}"

    head = "---\ndescription: 何をするか\n---\n"
    sk = "skills/x/SKILL.md"
    must("素の本文", [], {sk: head + "本文\n"})
    must("頭の YAML は行数に数えない", [], {sk: "---\ndescription: |\n" + "  あ\n" * BODY_LINES_LIMIT + "---\n本文\n"})
    must("字数は見ない", [], {sk: head + "あ" * 6000})
    must("499 行", [], {sk: head + "a\n" * (BODY_LINES_LIMIT - 1)})
    must("500 行", ["長さ"], {sk: head + "a\n" * BODY_LINES_LIMIT})
    must("頭の YAML の無いコマンドも本文を測る", ["長さ"], {"commands/c.md": "a\n" * BODY_LINES_LIMIT}, kind="command")
    must("在る先", [], {sk: head + "[手順](references/a.md#セクション) と [別名][r]\n\n[r]: <references/b c.md>\n",
                       "skills/x/references/a.md": "a\n", "skills/x/references/b c.md": "b\n"})
    must("%20 の先", [], {sk: head + "[b](references/b%20c.md)\n", "skills/x/references/b c.md": "b\n"})
    must("無い先", ["無い先"], {sk: head + "[手順](references/none.md)\n"})
    must("参照の形の無い先", ["無い先"], {sk: head + "[r]: references/none.md\n"})
    must("画像の無い先", ["無い先"], {sk: head + "![図](fig.svg)\n"})
    must("プラグインの中の別の所", [], {sk: head + "[r](../../README.md)\n", "README.md": "r\n"})
    must("コマンドから隣のコマンド", [], {"commands/c.md": head + "[d](d.md)\n", "commands/d.md": "d\n"}, kind="command")
    must("ルートの外", ["ルートの外"], {sk: head + "[r](../../../outside.md)\n"})
    must("URL・ページの中・絶対パス・変数は見ない", [],
         {sk: head + "[a](https://x.example/a.md) [b](#セクション) [c](/abs.md) [d](mailto:a@b) [e](${CLAUDE_SKILL_DIR}/x.md)\n"})
    must("コードの中のリンクの形は見ない", [],
         {sk: head + "`[#番号](URL)` の形\n```\n[a](none.md)\n```\n~~~~\n[b](none.md)\n```\n~~~~\n"})
    must("閉じの無い塊の後ろは見ない", [], {sk: head + "```\n[a](none.md)\n"})
    must("閉じた塊の後ろは見る", ["無い先", "無い先"],
         {sk: head + "```sh\n[a](none.md)\n```\n[b](none.md)\n- 項\n    ~~~\n    [c](none.md)\n    ~~~\n[d](none.md)\n"})
    must("短い列と字の続く列では閉じない", [],
         {sk: head + "~~~~\n~~~\n[a](none.md)\n~~~~~\n````\n```\n[b](none.md)\n````\n```\n```x\n[c](none.md)\n```\n"})
    long_ok = "# 題\n\n- 一 — 添え書き\n- [`--二`](#--二)\n\n" + "## 一\n" + "a\n" * 60 + "## `--二`\n" + "b\n" * 60
    must("目次のある長い別ファイル", [], {sk: head + "[r](references/r.md)\n", "skills/x/references/r.md": long_ok})
    must("100 行ちょうどは目次が要らない", [], {sk: head, "skills/x/references/r.md": "a\n" * TOC_OVER})
    must("目次の無い長い別ファイル", ["目次"], {sk: head, "skills/x/references/r.md": "## 一\n" + "a\n" * 120})
    must("見出しの欠けた目次", ["目次"],
         {sk: head, "skills/x/references/r.md": "- 一\n\n## 一\n" + "a\n" * 60 + "## 二\n" + "b\n" * 60})
    must("目次が頭の 20 行目", [], {sk: head, "skills/x/references/r.md": "a\n" * (TOC_HEAD - 1) + "- 一\n## 一\n" + "a\n" * 100})
    must("目次が頭の 21 行目", ["目次"], {sk: head, "skills/x/references/r.md": "a\n" * TOC_HEAD + "- 一\n## 一\n" + "a\n" * 100})
    must("見出しを含むだけの項は目次でない", ["目次"],
         {sk: head, "skills/x/references/r.md": "- 手順一覧\n## 手順\n" + "a\n" * 120})
    must("頭の YAML の中の箇条書きは目次でない", ["目次"],
         {sk: head, "skills/x/references/r.md": "---\ntags:\n- 一\n---\n## 一\n" + "a\n" * 120})
    must("塊の後ろの見出しも目次に要る", ["目次"],
         {sk: head, "skills/x/references/r.md": "- 一\n## 一\n```\n## 例\n```\n## 二\n" + "a\n" * 120})
    must("見出しの無い長い別ファイル", ["目次"], {sk: head, "skills/x/references/r.md": "a\n" * 120})
    must("コードの中の ## は見出しでない", [],
         {sk: head, "skills/x/references/r.md": "- 一\n## 一\n```\n## 例\n```\n" + "a\n" * 120})
    must("スクリプトは目次を見ない", [], {sk: head, "skills/x/scripts/s.py": "a = 1\n" * 200})
    must("コマンドはフォルダを持たないので目次を見ない", [],
         {"commands/c.md": head, "commands/r.md": "a\n" * 200}, kind="command")

    # 走査と外す一覧: 外した決まりは通し、満たした物・無い物は消させる。外していない決まりは落とす
    r = d / "repo"
    for p, files in (("a", {"skills/x/SKILL.md": head + "a\n" * BODY_LINES_LIMIT,
                            "commands/c.md": head + "本文\n", "commands/sub/n.md": head + "[n](none.md)\n"}),
                     ("moved", {"skills/y/SKILL.md": head + "本文\n"}), ("moved2", {"commands/z.md": head + "本文\n"})):
        for rel, body in files.items():
            (r / p / rel).parent.mkdir(parents=True, exist_ok=True)
            (r / p / rel).write_text(body, encoding="utf-8")
        (r / p / ".claude-plugin").mkdir(parents=True)
        (r / p / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": p, **{"moved": {"commands": "./other"}, "moved2": {"skills": "./other"}}.get(p, {})}),
            encoding="utf-8")
    (r / ".claude-plugin").mkdir()
    (r / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"plugins": [{"name": p, "source": f"./{p}"} for p in ("a", "moved", "moved2")]}), encoding="utf-8")
    found, bad = scan(r, {"a/skills/x/SKILL.md": {"長さ"}, "a/commands/c.md": {"長さ"}, "a/gone.md": {"長さ"}})
    assert sorted(f.relative_to(r).as_posix() for f, _, _ in found) == \
        ["a/commands/c.md", "a/commands/sub/n.md", "a/skills/x/SKILL.md", "moved/skills/y/SKILL.md", "moved2/commands/z.md"], \
        f"走査の拾い方が違う: {found}"
    want = ["moved: plugin.json が置き場（commands）", "moved2: plugin.json が置き場（skills）", "a/commands/c.md: 決まり「長さ」を満たした", "a/commands/sub/n.md: リンク none.md",
            "a/gone.md: EXEMPT に載っているが"]
    assert len(bad) == len(want) and all(b.startswith(w) for b, w in zip(bad, want)), f"走査の食い違いの拾い方が違う: {bad}"
    assert not any(b.startswith("a/skills/x/SKILL.md") for b in bad), "外した決まりまで落としている"
    _, bad = scan(r, {})
    assert any(b.startswith("a/skills/x/SKILL.md: 本文が 500 行") for b in bad), "外していない長さを落とさない"
    empty = d / "empty"
    (empty / ".claude-plugin").mkdir(parents=True)
    (empty / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": []}), encoding="utf-8")
    assert scan(empty, {})[1] == ["スキルもコマンドも 1 つも見つからない（走査が空回りしている）"], "空回りを落とさない"
    print("SKILL_BODY_ARMS_OK")
    return 0


if __name__ == "__main__":
    sys.exit({"tree": tree, "arms": arms}[sys.argv[1]]())
