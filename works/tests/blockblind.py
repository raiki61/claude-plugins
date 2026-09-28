"""ブロックの散文の中のほかのブロック・役・段の名指しを数える柵の中身（試験は test_block_blind）。

test_layers の決まり 3（name）はコードの文字列の定数だけを見る。ここはブロックの追跡されたテキスト全部を行で読み、
自分以外の blk-<名>（名の集合は blk-* のフォルダから取る）を「ファイル:相手の名 → 行の数」で数える。core に置かれた
ブロックの模块（test_layers の MOD で L4）も持ち主のブロックの部品として数える。行で読むのでコードの文字列の定数も数え、
決まり 3 と重なりうる（当座に許すなら両方の表に載せる）。
COPIED_FROM を持つフォルダはバイト単位の写しで直せないので外す（test_layers が L0 の写しに文字列の決まりを当てないのと同じ）。
役の指示書（commands・rules・写しでない prompts。下のフォルダの深さは問わない）は、ほかの役・段の語（ROLE_TERMS）を
「ファイル:語 → 行の数」で数える。自分の役は各ファイルの名乗りの文（最初の「お前は／あなたは」から「。」まで。
行ではない）から取って除く（手で表を持たない。名乗りの無いファイルは全部を数える）。
lib の Python が組んで指示書に入れる文（blk-fix/lib/fixrules.py など）は、依頼の目的の文が commands・rules に限るので見ない。
許可表の鍵に行番号を使わないのは、散文は行がずれやすいため（ESLint の bulk suppressions と同じ「ファイル×相手→件数」）。
"""
import re
import subprocess

from test_layers import MOD

NAME = re.compile(r"blk-[a-z0-9]+")
MARK = "COPIED_FROM"
# core に置かれたブロックの模块（層の正本 MOD で L4）もそのブロックの部品として数える: パス → 持ち主
CORE_OWNER = {f".shared/core/{m}.py": owner for m, (layer, owner) in MOD.items() if layer == 4}

# 2026-09-28 の依頼: この run はブロックの中身を変えない（他の run とぶつけない）。別の run で入力を形と約束で書き直す
LATER = "2026-09-28 の依頼で固定。別の run で入力を形と約束で書き直す"

# 今ある破れ（減らす方向にだけ変える）: "<works からのパス>:<相手の名>" → (行の数, 理由)
BLOCK_KNOWN = {
    ".shared/core/ci_role.py:blk-tests": (2, "docstring と拒否の文が開く条件を blk-tests の final で述べる。" + LATER),
    ".shared/core/purpose.py:blk-premises": (1, "docstring が入力を blk-premises の返答で述べる。" + LATER),
    "blk-ci/blk-ci.yaml:blk-tests": (1, "description が回す条件を blk-tests の final で述べる。" + LATER),
    "blk-delta/blk-delta.yaml:blk-refix": (1, "コメントが受け付けの欄を blk-refix と比べる。" + LATER),
    "blk-fix/blk-fix.yaml:blk-judge": (2, "inputs の description が入力を blk-judge の出口で述べる。" + LATER),
    "blk-judge/lib/judgebrief.py:blk-material": (1, "docstring が止めた節を blk-material で述べる。" + LATER),
    "blk-material/blk-material.yaml:blk-purpose": (1, "inputs の description が入力を blk-purpose の出口で述べる。" + LATER),
    "blk-material/lib/material.py:blk-ci": (2, "docstring とコメントが止め札を blk-ci と比べる。" + LATER),
    "blk-material/lib/material.py:blk-purpose": (2, "docstring が入力を blk-purpose の出口で述べる。" + LATER),
    "blk-purpose/blk-purpose.yaml:blk-premises": (1, "inputs の description が入力を blk-premises の返答で述べる。" + LATER),
    "blk-purpose/scripts/intake.py:blk-premises": (1, "docstring が入力を blk-premises の返答で述べる。" + LATER),
    "blk-refix/blk-refix.yaml:blk-delta": (1, "description が入力を blk-delta の穴で述べる。" + LATER),
    "blk-spec/lib/specblk.py:blk-rejudge": (1, "コメントが入口を blk-rejudge と比べる。" + LATER),
    "blk-tests/blk-tests.yaml:blk-ci": (1, "description が後を blk-ci が回すと述べる。" + LATER),
    "blk-tests/scripts/run_tests.py:blk-ci": (2, "docstring が後を blk-ci が回すと述べる。" + LATER),
}

FIX = ("ブロックはほかのブロック・役・段を知らない。入力・出口は形と約束で述べ、どのブロック・役が作ってどう繋ぐかは "
       "darkfactory/darkfactory.yaml（ライン）に書く。直したら BLOCK_KNOWN・ROLE_KNOWN の件数を減らす（増やさない）")


# 役の指示書（ブロックの commands・rules・写しでない prompts）がほかの役・段を前提にする語。閉じた一覧にするのは、
# 「〜役」を全部拾うと「代役」のような役割でない語まで拾うため（Vale の existence の tokens と同じ形）
ROLE_TERMS = ("判定役", "修正役", "審査役", "裁定役", "実測役", "比較役", "関所", "前段", "後段")
ROLE_DIRS = frozenset({"commands", "rules", "prompts"})
SELF_LINE = re.compile(r"(?:お前|あなた)は([^。]*)")

ROLE_LATER = "2026-09-28 の依頼で固定。別の run で、前後の役・段を所与にせず入力と出口の約束で書き直す"

# 今ある破れ（減らす方向にだけ変える）: "<works からのパス>:<語>" → (行の数, 理由)
ROLE_KNOWN = {
    "blk-delta/commands/delta-review.md:修正役": (2, "審査の相手を修正役として述べる。" + ROLE_LATER),
    "blk-delta/commands/delta-review.md:関所": (1, "後に人の関所が在る前提で述べる。" + ROLE_LATER),
    "blk-fix/rules/common.md:判定役": (3, "名乗りの無い共通の決まりが判定役の判定を所与にする。" + ROLE_LATER),
    "blk-fix/rules/common.md:裁定役": (2, "食い違いの申し出の先を裁定役として述べる。" + ROLE_LATER),
    "blk-fix/rules/common.md:関所": (1, "最後の人の関所が在る前提で述べる。" + ROLE_LATER),
    "blk-fix/rules/direct.md:判定役": (3, "判定役が切った単位を所与にする。" + ROLE_LATER),
    "blk-fix/rules/direct.md:後段": (1, "後段が在る前提で述べる。" + ROLE_LATER),
    "blk-fix/rules/direct.md:関所": (1, "人の関所が在る前提で述べる。" + ROLE_LATER),
    "blk-fix/rules/principles.md:関所": (1, "最後の人の関所が在る前提で述べる。" + ROLE_LATER),
    "blk-fix/rules/ruler.md:修正役": (1, "裁く相手を修正役として述べる。" + ROLE_LATER),
    "blk-fix/rules/tdd.md:判定役": (1, "判定役が切った単位を所与にする。" + ROLE_LATER),
    "blk-fix/rules/tdd.md:関所": (1, "人の関所が在る前提で述べる。" + ROLE_LATER),
    "blk-judge/commands/diagnose.md:修正役": (2, "判定の読み手を修正役として述べる。" + ROLE_LATER),
    "blk-premises/commands/premises.md:判定役": (2, "実測の読み手を判定役として述べる。" + ROLE_LATER),
    "blk-purpose/commands/purpose.md:判定役": (1, "目的の文の読み手を判定役として述べる。" + ROLE_LATER),
    "blk-refix/commands/refix.md:修正役": (1, "手直しの前を修正役として述べる。" + ROLE_LATER),
    "blk-refix/commands/refix2.md:判定役": (1, "次の run の判定役を所与にする。" + ROLE_LATER),
    "blk-refix/commands/review2.md:判定役": (1, "次の run の判定役を所与にする。" + ROLE_LATER),
    "blk-refix/commands/review2.md:関所": (1, "最後の人の関所が在る前提で述べる。" + ROLE_LATER),
    "blk-rejudge/commands/rejudge-third.md:修正役": (1, "往復の相手を修正役として述べる。" + ROLE_LATER),
    "blk-rejudge/commands/rejudge.md:修正役": (1, "異議の出し手を修正役として述べる。" + ROLE_LATER),
}


def blocks(root):
    """ブロックの名の集合（works の blk-* のフォルダ。名前の順）"""
    return sorted(p.name for p in root.glob("blk-*") if p.is_dir())


def tracked(root):
    """ブロックの追跡されたファイルと、core に在るブロックの模块（L4）（works からのパス）"""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", "blk-*", *CORE_OWNER],
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.split("\0") if f]


def block_refs(root, files):
    """"<パス>:<相手の名>" → 自分以外のブロックの名を含む行の数。写しのフォルダ・ブロックの外・テキストでない物は見ない"""
    names = set(blocks(root))
    found = {}
    for f, text in _texts(root, files):
        own = CORE_OWNER.get(f, f.split("/", 1)[0])
        if own not in names:
            continue
        for line in text.splitlines():
            for other in set(NAME.findall(line)) & names - {own}:
                key = f"{f}:{other}"
                found[key] = found.get(key, 0) + 1
    return found


def self_roles(text):
    """指示書の名乗り（最初の「お前は／あなたは …」の文）に在る役・段の語。名乗りが無ければ空"""
    m = SELF_LINE.search(text)
    return {t for t in ROLE_TERMS if m and t in m.group(1)}


def role_refs(root, files):
    """"<パス>:<語>" → 役の指示書でほかの役・段の語を含む行の数（自分の名乗りの語は除く）"""
    found = {}
    for f, text in _texts(root, files):
        parts = f.split("/")
        if len(parts) < 3 or not parts[0].startswith("blk-") or parts[1] not in ROLE_DIRS:
            continue
        own = self_roles(text)
        others = [t for t in ROLE_TERMS if t not in own]
        for line in text.splitlines():
            for t in others:
                if t in line:
                    key = f"{f}:{t}"
                    found[key] = found.get(key, 0) + 1
    return found


def _texts(root, files):
    """(パス, 中身) の組。写しのフォルダ（COPIED_FROM を持つ）とテキストでない物は除く"""
    copied = {f.rsplit("/", 1)[0] + "/" for f in files if f.rsplit("/", 1)[-1] == MARK}
    for f in files:
        if any(f.startswith(d) for d in copied):
            continue
        try:
            yield f, (root / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def verdict(found, known):
    """許可表とのずれの文の一覧（空なら揃っている）: 表に無い組・増えた組・減った組（直ったのに表が残る）"""
    out = []
    for key in sorted(set(found) | set(known)):
        n, k = found.get(key, 0), known.get(key, (0, ""))[0]
        if n > k:
            out.append(f"増えた {key}: {n} 行（表は {k}）")
        elif n < k:
            out.append(f"減った {key}: {n} 行（表は {k}。表を減らす）")
    return out


def report(found, known):
    lines = verdict(found, known)
    return "\n".join([FIX] + lines) if lines else ""
