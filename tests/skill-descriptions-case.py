#!/usr/bin/env python3
"""全部のプラグインのスキル・コマンド・役の説明（ファイルの頭の YAML の description）が、黙って壊れていないかを見る。

説明は会話の始めに読み込まれ、Claude がそのスキルを呼ぶかを決める材料になる。壊れても読み込みは失敗しないので、誰も気づかない
（実例: works-dispatch の dispatch の説明が「issue #1300」の「 #」から後ろを YAML の注釈として読み捨てられ、いつ使うかが一覧から落ちていた）。

使い方: python3 tests/skill-descriptions-case.py <場合>
- tree: リポジトリの全部のプラグイン（.claude-plugin/marketplace.json の source）の skills/*/SKILL.md・commands/**/*.md・agents/*.md を見る
- arms: 下の検査の 1 つずつが、壊した例で落ち、壊していない例で通ることを見る（チェックが空振りしていないか）

見ること（どれも出典で決まる物だけ。短い目安の上限は持ち主が決めるまで足さない）:
- 頭の YAML が 1 行目の「---」から始まり、閉じの「---」が在り、mapping として読める。Claude Code は 1 行目でなければ全部を本文として読み、
  読めない YAML はフィールドを 1 つも持たないスキルとして読み込む（https://code.claude.com/docs/en/skills）
- 値の中に「---」が無い。Claude Code は値の途中の最初の「---」で頭を閉じる（下の CC_FRONT）
- description が空でない文字列。YAML として読んだ説明（と when_to_use）の後ろに、YAML が読み捨てた文（注釈）が無い——読んだ値の
  終わりから次のフィールドまでに、フィールドの名前より深い所から始まる文が無い（https://yaml.org/spec/1.2.2/#comments）。位置は YAML の読み手
  （PyYAML）が返す物を使い、自分で文法を真似ない
- SKILL.md の description は 1,024 字まで（Agent Skills の仕様。https://agentskills.io/specification）
- スキルとコマンドの description と when_to_use を足して 1,536 字まで（超えた分は一覧で切られる。https://code.claude.com/docs/en/skills）。
  コマンド（commands/*.md）もスキルと同じ一覧に並ぶ。役（agents/*.md）は字数の上限の出典が無いので、字数は見ない
"""

import json
import pathlib
import re
import sys
import tempfile

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import yaml  # noqa: E402  ——無い環境は tests/run.sh が先に見て、見送り（# SKIP pyyaml）にする

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL_MAX = 1024
LISTING_MAX = 1536
# 頭の YAML の形。閉じの「---」は行そのもの（後ろの空白は許す）
FRONT = re.compile(r"\A---[ \t]*\n(.*?\n)?---[ \t]*(?:\n|\Z)", re.S)
# Claude Code の切り出し方（2.1.302 の本体から引いた正規表現。実測 2026-10-17）。閉じの「---」を行頭に縛らないので、値の途中の
# 最初の「---」で頭が閉じる。上の行ごとの形と中身が違えば、説明がそこで黙って切れる
CC_FRONT = re.compile(r"^---\s*\n([\s\S]*?)---\s*\n?")
# plugin.json でこれらの置き場を変えられる。変えた物はここの走査が見ないので、黙ってチェックの外に出さずに落とす
CUSTOM_PATHS = ("skills", "commands", "agents")


def check_file(path, kind):
    """1 つのファイルの食い違いを文の list で返す。kind は skill・command・agent。"""
    # 改行は read_text が \n にそろえる。BOM は Claude Code も切り出す前に剥がす
    text = path.read_text(encoding="utf-8").removeprefix("\ufeff")
    m = FRONT.match(text)
    if not m:
        return ["頭の YAML が無い（1 行目が「---」でないか、閉じの「---」が無い）。Claude Code は説明の無いものとして読む"]
    front = m.group(1) or ""
    cc = CC_FRONT.match(text)
    if not cc or cc.group(1).lstrip() != front.lstrip():
        return ["値の中の「---」で、Claude Code が頭の YAML をそこで閉じる（説明がそこで切れる）。値の中に「---」を書かない"]
    try:
        node = yaml.compose(front)
        data = yaml.safe_load(front)
    except yaml.YAMLError as e:
        return [f"頭の YAML が読めない（Claude Code はフィールドを 1 つも持たないものとして読む）: {' '.join(str(e).split())}"]
    if not isinstance(data, dict) or not isinstance(node, yaml.MappingNode):
        return ["頭の YAML が「欄: 値」の並びになっていない"]
    bad = []
    desc = data.get("description")
    if not isinstance(desc, str) or not desc.strip():
        bad.append("description が無いか、空か、文字列でない")
    when = data.get("when_to_use")
    if when is not None and not isinstance(when, str):
        bad.append("when_to_use が文字列でない")
    pairs = node.value
    for i, (key, value) in enumerate(pairs):
        if key.value not in ("description", "when_to_use"):
            continue
        # 読んだ値の終わりから次のフィールドまでに残った文のうち、説明を切ったのは、フィールドの名前より深い所から始まる物だけ——値と同じ行に続く物
        # （YAML の注釈は前に空白が要るので、必ず 1 字以上深い）と、値の続きのつもりで字下げした行。フィールドと同じ深さの注釈の行は何も切っていない
        nxt = pairs[i + 1][0].start_mark.index if i + 1 < len(pairs) else len(front)
        for line in front[value.end_mark.index:nxt].split("\n"):
            if line.strip() and len(line) - len(line.lstrip(" \t")) > key.start_mark.column:
                bad.append(f"{key.value} の後ろの「{line.strip()[:40]}」を YAML が注釈として読み捨てる（説明がそこで切れる）。"
                           "値を引用符で囲むか、空白の後の「#」をやめる")
                break
    if not isinstance(desc, str):
        return bad
    if kind == "skill" and len(desc) > SKILL_MAX:
        bad.append(f"description が {len(desc)} 字（Agent Skills の上限は {SKILL_MAX} 字）")
    listed = len(desc) + (len(when) if isinstance(when, str) else 0)
    if kind in ("skill", "command") and listed > LISTING_MAX:
        bad.append(f"description と when_to_use で {listed} 字（Claude Code の一覧は {LISTING_MAX} 字で切る）")
    return bad


def targets(root):
    """(相対パス, kind) の list と、走査そのものの食い違いの list を返す。"""
    market = json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    found, bad = [], []
    for plugin in market["plugins"]:
        src = root / plugin["source"]
        manifest = src / ".claude-plugin" / "plugin.json"
        declared = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
        custom = [k for k in CUSTOM_PATHS if k in declared]
        if custom:
            bad.append(f"{plugin['name']}: plugin.json が置き場（{', '.join(custom)}）を変えている。このチェックの走査も合わせて直す")
        mine = ([(f, "skill") for f in sorted(src.glob("skills/*/SKILL.md"))]
                + [(f, "command") for f in sorted(src.glob("commands/**/*.md"))]
                + [(f, "agent") for f in sorted(src.glob("agents/*.md"))])
        if not mine:
            bad.append(f"{plugin['name']}: スキル・コマンド・役が 1 つも見つからない（走査が空回りしている）")
        found += mine
    return found, bad


def scan(root):
    found, bad = targets(root)
    for path, kind in found:
        bad += [f"{path.relative_to(root).as_posix()}: {b}" for b in check_file(path, kind)]
    return found, bad


def tree():
    found, bad = scan(ROOT)
    if bad:
        print("\n".join(bad))
        return 1
    print(f"SKILL_DESCRIPTIONS_OK {len(found)} 件")
    return 0


def arms():
    d = pathlib.Path(tempfile.mkdtemp())

    def probe(body, kind="skill", name="SKILL.md"):
        f = d / name
        f.write_text(body, encoding="utf-8", newline="")
        return check_file(f, kind)

    def must_fail(why, body, kind="skill", word=""):
        got = probe(body, kind)
        assert got and all(word in g for g in got[:1]), f"{why}: 落ちるはずが {got}"

    def must_pass(why, body, kind="skill"):
        got = probe(body, kind)
        assert not got, f"{why}: 通るはずが {got}"

    must_pass("素の 1 行", "---\nname: a\ndescription: 何をするか。いつ使うか。\n---\n本文\n")
    must_pass("CRLF の行末", "---\r\nname: a\r\ndescription: 何をするか\r\n---\r\n本文\r\n")
    must_pass("引用符の中の #", '---\ndescription: "「issue #1300 を始めて」と言われたときに使う"\nname: a\n---\n')
    must_pass("空白の無い #", "---\ndescription: 「issue#1300 を始めて」と言われたときに使う\n---\n")
    must_pass("畳む書き方の中の #", "---\ndescription: >\n  「issue #1300 を始めて」と\n  言われたときに使う\nname: a\n---\n")
    must_pass("複数行の素の値", "---\ndescription: 何をするか。\n  いつ使うか。\nname: a\n---\n")
    must_pass("BOM と開きの後ろの空白", "\ufeff--- \ndescription: 何をするか\n---\n")
    must_pass("フィールドと同じ深さの注釈の行", "---\ndescription: 何をするか\n# 注\nname: a\n# 注\n---\n")
    must_pass("塊の後ろの浅い注釈の行", "---\ndescription: |+\n  何をするか\n\n# 注\nname: a\n---\n")
    must_fail("値の中の ---", "---\ndescription: 前の版 --- 後の版を比べる\n---\n", word="値の中の「---」")
    must_fail("畳む書き方の中の ---", "---\ndescription: >\n  前の版\n  ---\n  後の版\n---\n", word="値の中の「---」")
    must_fail("空白の後の # で切れる（dispatch の実例の形）",
              "---\nname: a\ndescription: 「issue #1300 を始めて」と言われたときに使う\n---\n", word="読み捨てる")
    must_fail("最後のフィールドで切れる", "---\ndescription: 何をするか #いつ使うか\n---\n", word="読み捨てる")
    must_fail("引用符の後ろの注釈", '---\ndescription: "何をするか" # いつ使うか\n---\n', word="読み捨てる")
    must_fail("続きの行が注釈になる", "---\ndescription: 何をするか。\n  # いつ使うか\nname: a\n---\n")
    must_fail("when_to_use で切れる", "---\ndescription: 何をするか\nwhen_to_use: 「#1 を見て」 #と言われたとき\n---\n",
              word="when_to_use の後ろ")
    must_fail("読めない YAML", "---\ndescription: 使い方: こう\n  打つ: こう\n---\n", word="読めない")
    must_fail("1 行目が「---」でない", "\n---\ndescription: 何をするか\n---\n", word="頭の YAML が無い")
    must_fail("閉じの「---」が無い", "---\ndescription: 何をするか\n", word="頭の YAML が無い")
    must_fail("description が無い", "---\nname: a\n---\n", word="description が無い")
    must_fail("description が空", "---\ndescription: \"\"\n---\n", word="description が無い")
    must_fail("description が文字列でない", "---\ndescription: [a, b]\n---\n", word="description が無い")
    must_fail("並びでない", "---\n- a\n---\n", word="並び")
    must_pass("SKILL.md の 1,024 字", f"---\ndescription: {'あ' * SKILL_MAX}\n---\n")
    must_fail("SKILL.md の 1,025 字", f"---\ndescription: {'あ' * (SKILL_MAX + 1)}\n---\n", word="1025 字")
    must_pass("コマンドは 1,024 字を超えてよい", f"---\ndescription: {'あ' * 1500}\n---\n", kind="command")
    must_pass("コマンドの合わせて 1,536 字", f"---\ndescription: {'あ' * 1000}\nwhen_to_use: {'い' * 536}\n---\n", kind="command")
    must_fail("コマンドの合わせて 1,537 字", f"---\ndescription: {'あ' * 1000}\nwhen_to_use: {'い' * 537}\n---\n",
              kind="command", word="1537 字")
    must_fail("スキルの合わせて 1,537 字", f"---\ndescription: {'あ' * 1000}\nwhen_to_use: {'い' * 537}\n---\n", word="1537 字")
    must_pass("役は字数を見ない", f"---\ndescription: {'あ' * 2000}\n---\n", kind="agent")
    must_fail("役も切れは見る", "---\ndescription: 何をするか #いつ\n---\n", kind="agent", word="読み捨てる")

    # 走査: 置き場を変えたプラグインと、何も見つからないプラグインを落とす。見つかる物は skills・commands（入れ子も）・agents
    r = d / "repo"
    for p, files in (("full", ("skills/x/SKILL.md", "commands/y.md", "commands/sub/z.md", "agents/w.md")),
                     ("moved", ("skills/x/SKILL.md",)), ("empty", ("README.md",))):
        for rel in files:
            (r / p / rel).parent.mkdir(parents=True, exist_ok=True)
            (r / p / rel).write_text("---\ndescription: 何をするか\n---\n", encoding="utf-8")
        (r / p / ".claude-plugin").mkdir(parents=True)
        (r / p / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": p, **({"skills": "./other"} if p == "moved" else {})}), encoding="utf-8")
    (r / ".claude-plugin").mkdir()
    (r / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"plugins": [{"name": p, "source": f"./{p}"} for p in ("full", "moved", "empty")]}), encoding="utf-8")
    found, bad = scan(r)
    kinds = sorted((f.relative_to(r).as_posix(), k) for f, k in found)
    assert kinds == [("full/agents/w.md", "agent"), ("full/commands/sub/z.md", "command"), ("full/commands/y.md", "command"),
                     ("full/skills/x/SKILL.md", "skill"), ("moved/skills/x/SKILL.md", "skill")], f"走査の拾い方が違う: {kinds}"
    assert len(bad) == 2 and "moved: plugin.json が置き場（skills）" in bad[0] and "empty: スキル・コマンド・役が 1 つも" in bad[1], \
        f"走査の食い違いの拾い方が違う: {bad}"
    (r / "full" / "commands" / "y.md").write_text("---\ndescription: 何を #いつ\n---\n", encoding="utf-8")
    assert any(b.startswith("full/commands/y.md: description の後ろ") for b in scan(r)[1]), "走査がファイルの食い違いを返さない"
    print("SKILL_DESCRIPTION_ARMS_OK")
    return 0


if __name__ == "__main__":
    sys.exit({"tree": tree, "arms": arms}[sys.argv[1]]())
