#!/usr/bin/env python3
"""判定表の各項目が実際に効いているかを、表を走査して確かめる。run.sh から呼ぶ。

代表 1 件だけを踏むテストだと、表からメンバーが 1 つ落ちても緑のままになる(実測)。
表が増えたら検査も自動で増えるように、表そのものを回す。
"""
import importlib.util
import os
import sys

gate_path = os.path.join(os.path.dirname(__file__), "..", "gates", "hooks", "coldread-gate.py")
spec = importlib.util.spec_from_file_location("coldread_gate", gate_path)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

BODY = "これは検査対象の本文です。" * 20
PAD = "x" * 420
failures = []


def bodies_of(command):
    candidates, blocked, parsed = gate.posting_bodies(command)
    return [c for c in candidates if len(c.strip()) >= 200], blocked, parsed


def want_body(command, why):
    bodies, blocked, parsed = bodies_of(command)
    if not bodies:
        failures.append("%s: 本文を拾えていない (blocked=%s parsed=%s) :: %s"
                        % (why, blocked, parsed, command[:90]))


def want_quiet(command, why):
    bodies, blocked, parsed = bodies_of(command)
    if bodies or blocked:
        failures.append("%s: 素通しのはずが反応した (bodies=%s blocked=%s) :: %s"
                        % (why, [len(b) for b in bodies], blocked, command[:90]))


# 長い旗: すべて綴りだけで本文と見なす(secret/variable set は NON_POSTING で別扱い)
for flag, kind in gate.LONG_TEXT_FLAGS.items():
    value = "- <<'EOF'\n%s\n%s\nEOF" % (BODY, PAD) if kind == "file" else "'%s %s'" % (BODY, PAD)
    want_body("gh issue comment 1 %s %s" % (flag, value), "長い旗 %s" % flag)

# 短縮形: 本文を意味するサブコマンドの全組で拾い、それ以外では反応しない
for flag, (kind, posting) in gate.SHORT_TEXT_FLAGS.items():
    for group, verb in sorted(posting):
        value = "- <<'EOF'\n%s\n%s\nEOF" % (BODY, PAD) if kind == "file" else "'%s %s'" % (BODY, PAD)
        want_body("gh %s %s 1 %s %s" % (group, verb, flag, value), "短縮形 %s (%s %s)" % (flag, group, verb))
    want_quiet("gh pr checkout 1 %s %s%s" % (flag, BODY, PAD), "短縮形 %s は投稿でない所で反応しない" % flag)

# 値を取る global 旗: 前に置かれてもサブコマンドを見失わない(空白・= ・密着の 3 形)
for flag in sorted(gate.GLOBAL_VALUE_FLAGS):
    val = "X-F:b" if flag in ("-H", "--header") else ("POST" if flag in ("-X", "--method") else "o/r")
    forms = ["%s %s" % (flag, val)]
    if flag.startswith("--"):
        forms.append("%s=%s" % (flag, val))
    else:
        forms.append("%s%s" % (flag, val))
    for form in forms:
        want_body("gh %s issue comment 1 -b '%s %s'" % (form, BODY, PAD), "global 旗 %s" % form)

# 前置ラッパー: 全メンバーで gh を見失わない
for wrapper in sorted(gate.WRAPPERS):
    want_body("%s gh issue comment 1 --body '%s %s'" % (wrapper, BODY, PAD), "前置 %s" % wrapper)

# リダイレクト演算子: 全メンバーで本文を見失わない(区切りと取り違えない)
for op in sorted(gate.REDIRECT_OPS):
    if op in ("<<", "<<<"):
        continue  # ヒアドキュメント系は盾置換の担当で、別のケースが見ている
    want_body("gh issue comment 1 --body '%s %s' %s /dev/null" % (BODY, PAD, op), "リダイレクト %s" % op)
    want_body("gh issue comment 1 --body %s2 '%s %s'" % (op, BODY, PAD), "リダイレクト %s 挟み" % op)

# 投稿でない同綴りのサブコマンド: 値を読み役へ送らない
for group, verb in sorted(gate.NON_POSTING):
    want_quiet("gh %s %s KEY --body '%s %s'" % (group, verb, BODY, PAD), "非投稿 %s %s" % (group, verb))

if failures:
    for f in failures:
        print("表の検査で漏れ: " + f)
    sys.exit(1)
print("TABLE_OK")
