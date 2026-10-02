"""Claude の包み（同じ置き場の claude-adapter）の芯。argv の読み・設定のマージ・印・会話の id の置き場・柵・止め方。

Archon は Claude Code の実行ファイルを `assistants.claude.claudeBinaryPath`（設定）か `CLAUDE_BIN_PATH`（env）で
差し替えられる。そこに claude-adapter を置くと、Archon の SDK が組んだ argv がこちらに来る。包みは argv だけを見て
（標準入出力は 9・16 のほかは中継せずに子へ継がせる）下の 1〜3 と 5 を足し、本物の claude を 4 の形で起こす。形は有料の試しで
本物の Archon v0.11.1・SDK 0.3.282・claude 2.1.283 と確かめた（scratchpad の claude-adapter-probe.md・
resume-probe-summary.md・probes-p14-p15-summary.md・trackB-probes-wave2.md の P6e）。

1. **Read と書き込みのフック**: `--settings` の JSON に PostToolUse:Read のフック（同じ置き場の record-read.py）と、
   PostToolUse:Edit|Write|NotebookEdit のフック（record-write.py。書いた後の中身の sha を writes_path に残し、書く役の受け付けが
   版からの変更と突き合わせる。.shared/core/writes.py）を足す。
   SDK は sandbox を持つ節にだけ `--settings {"sandbox":{…}}` を付けるので、在ればマージ（SDK の鍵は上書きしない）、
   無ければフックだけの `--settings` を足す。`--setting-sources`（SDK は `=` でつないで必ず渡す）と `--model`・`--effort` は
   触らない（`--model`・`--effort` は読んで起動の記録に残すだけ。launch_row）。
   CLAUDE.md を止めるのは YAML の `settingSources: [user]` と、開発の殻が組む隔離した設定の柵（dev/toolset.py）の役目
   （Archon の検証と実際を食い違わせない）。
2. **会話の継ぎ**: 役の節の output_format（JSON Schema）の一番上の `description` に置いた印
   `works-node: <節の名>[ continue=<継ぐ節の名>][ <旗>…]` を、SDK がそのまま載せる argv の `--json-schema` から読む
   （指示文は claude が initialize に答えるまで stdin に来ないので、起動の前には読めない）。
   - 印あり・continue なし: SDK が付けた `--resume`／`--session-id` の id を、無ければ包みが作った uuid を
     `--session-id=<uuid>` で足して、`sessions/<cwd の hash>/<節の名>.id` に記録する。SDK が `--fork-session` で
     継ぐ時は新しい会話の id を SDK が知らせないので、包みが `--session-id=<uuid>` を足して決める
   - continue=X: SDK が付けた会話の旗（`--resume`・`-r`・`--session-id`・`--fork-session`・`--continue`・`-c`）を外し、
     `--resume <X の id>` を足す（fork しない。同じ会話に積む）。X の id が無い・読めない時は子を起こさず止まる
     （fail closed）。YAML の節は `context: fresh` にして Archon 自身には何も継がせない

3. **起動ごとの柵**（切符が在る起動だけ）: 線の `start` が書く切符（ticket.py。`<家>/tickets/<key>.json` の
   `protected`）に、起動の時に引き直す 2 つ——この起動の env の `CLAUDE_CONFIG_DIR` と、`git worktree list` の今の
   worktree（切符の後に切られた物。役の cwd の worktree 自身は除く）——を足し、どれも /var と /private/var・/tmp と
   /private/tmp の両方の綴りにして、`permissions.deny` に `Edit(//<場所>)`・`Edit(//<場所>/**)`・`Write(…)` を足す。
   SDK が sandbox の塊を渡した起動だけ `sandbox.filesystem.denyWrite` にも足す（sandbox の無い節に sandbox の鍵を作らない）。
   どちらも SDK の配列の後ろに足し、SDK の項目は消さない。

4. **木ごと止める**: 本物の claude は exec せずに子として新しいセッションで起こし（標準入出力は 9・16 のほかは継ぐ）、走っている間
   POLL 秒ごとに木の仲間（tree_run._tree_members: グループ・セッションの番号・親子の鎖・前に数えた物。開始時刻で番号の
   再利用を見分ける）を数えて溜める。claude の Bash の道具はコマンドを claude と別のグループで走らせるので、claude の
   グループへ送るだけでは孫に届かない（試し P15: SIGTERM を無視する孫が Ctrl-C でも cancel でも残った）。
   SIGINT・SIGTERM・SIGHUP を受けた時（か直下の親が替わった時）と claude が終わった後に、溜めた仲間ごと
   tree_run.stop_group（数え上げ→送る→数え直し。TERM → KILL_GRACE → KILL）で止める。信号で止めた時は LINGER 待ってから
   128+信号で抜ける（すぐ死ぬと Archon の run が running のまま固まる。試し P17）。上限は tree_run と同じ勘定。
5. **印 no-post**（並行 PR の任せ先の役。切符に依らない）: gh は丸ごと拒み（permissions.deny の `Bash(gh:*)`・本物の gh の
   絶対パスの全部の綴り・`Bash(git push:*)`）、読む 4 つの形（pr list・pr view・pr diff を -R 付きで、repo view <OWNER/REPO>）
   だけを通す口 no-post-bin/works-gh を env の WORKS_GH で渡し、PATH の頭に同じ口を gh の名で置く（NO_POST_DENY の注記）。
6. **旗 no-tree-write**（CI の任せ先の役。裁定 R56）: 役の sandbox は graphloops の任せ先と同じ allowWrite ['/']（依存の
   置き場・網を今までどおり使う）なので、本物の作業ツリーは包みが守る。役の cwd の worktree の根（`git rev-parse
   --show-toplevel`。全部の綴り）を 3 の柵（denyWrite・permissions.deny）に足す。SDK が sandbox の塊（enabled: true・
   allowUnsandboxedCommands: false・failIfUnavailable: true）を渡していない起動・切符の無い起動・根が git から引けない
   起動は起こさない（役が書く道は Bash だけで守りは denyWrite だけ。
   盤面・pack・git の設定の守りは切符にしか無い）。切符の「役の cwd の worktree 自身は除く」はそのまま（書く役の fix のため）
6b. **旗 isolated**（独立の目の道具ゼロの役 blind-judge）: 子を Git の外の置き場 `<一時の置き場>/works-isolated-<cwd の hash>`
   で起こす（graphloops の commands._isolated_cwd と同じ。claude は cwd が Git のリポジトリの外なら git status の写しを system
   prompt に入れない——公式 'Absent outside a Git repository'。CLAUDE.md は YAML の settingSources: [user] が外す）。置き場は run
   ごとに同じ（claude の会話の置き場は cwd ごとなので、出し直しの --resume が同じ会話を引ける）。会話の id・起動の記録の鍵は
   Archon の cwd（run の worktree）のまま。道具を持つ起動（`--tools ""` でない）・置き場が Git の中の起動は起こさない
7. **印のある起動は柵なしで起こさない**: --settings を読めない・混ぜられない、切符のファイルが在るのに読めない、
   会話の id を記録できない時は、claude を起こさずに 1 行を出して止まる（fail closed）。
8. **網を閉じる**（印の有無に依らない。option A）: Archon は役を bypassPermissions で起こし、網の型（sandboxSettingsSchema.network）
   から strictAllowlist を捨てる。bypassPermissions の下の Claude Code 2.1.283 は、allowedDomains に無い宛先への sandbox の
   通信の問い合わせを自動で通す（拒むのは strictAllowlist: true の時だけ。この鍵は --settings から効く）。そこで
   `--settings` の sandbox.network.allowedDomains が配列で `*` を含まない起動に sandbox.network.strictAllowlist: true を足す
   （Claude Code では狭める側の鍵）。`*` の網（任せ先）・網の一覧を持たない sandbox・sandbox の無い起動は触らない。
   --settings が読めない・2 つ・sandbox や network や一覧の形が違う起動は、網を閉じられるかが決まらないので、印が無くても
   claude を起こさずに 1 行を出して止まる（fail closed）。WebFetch・WebSearch はこの鍵の外（Claude Code の説明文どおり）。

9. **指示書の全文版と差分版**（トークンの節約。持ち主の承認。印のある起動だけ）: 輪（loop_group の fresh_context: false）の
   役は 1 つの会話を周をまたいで継ぐので、共有の規則を毎周送り直すと会話に同じ規則が積み重なる。支度のスクリプトは指示書
   （prompt_file。既定は全文版の写し）の隣に `<stem>.full.md`・`<stem>.delta.md`・`<stem>.variants.json`（{full, delta,
   rules_sha, iteration, sections}）を書く。包みは印のある起動の stdin を子へ中継し（バイトは変えない）、最初の user の 1 行
   （SDK が initialize の後に書く指示文）から指示書のパスを読んで、その行を子へ渡す前に指示書へ全文版か差分版を書く。
   差分版は、この起動が継ぐ会話（--resume の元。fork の鎖を包みの起動の記録で辿る）が同じ rules_sha の全文版をこの包みから
   受け取り、Read のフックの記録で部分読みでなく読み切り、会話の記録（Claude Code の transcript）に要約・古い道具の結果の消去
   （compact_boundary・microcompact_boundary）の跡が無い時だけ。ほかは全部全文版（疑いは全文版）。variants.json が無ければ
   何もしない。読めない・指示書が 2 つ・指示書の中身が全文版とも包みの差分版とも違う時は指示書に触らない。選んだ版は
   起動の記録の `prompt`（{file, variant, rules_sha, iteration, full_sha, reason}）に残す（variants.json の無い起動は欄を持たない）

10. **借りる MCP を渡す**（印のある起動だけ）: Archon の役の節は周りの MCP（利用者・プラグインの MCP）を読まない
   （SDK が `--strict-mcp-config` を付ける。Archon v0.11.1 の providers/claude/provider.ts の strictMcpConfig）。開発の殻が
   隔離した設定の置き場に書く `works-mcp.json`（dev/toolset.py が許す一覧 borrow.json の使用許諾を確かめて書く。Context7）を、
   env の WORKS_CONTEXT7_MCP が on の時だけ（既定は渡さない。役が書く問いに対象のコードの字が載り、外のサービスへ出うるため。
   controller の裁定 2026-09-28。持ち主が決めるまで安全側）、web を持つ起動（`--tools` に WebFetch が在る）にだけ
   `--mcp-config=<ファイル>` で渡す（web を読む道具と同じ扱い。
   道具ゼロ・web を持たない役には渡さない）。SDK が自分の `--mcp-config` を渡した起動は触らない。ファイルが読めない時は
   渡さずに起動の記録の fence.mcp に理由を書く（足す物なので、渡せなくても役は起こす）

13. **検索語の規律を重ね書きする**（印のある道具を持つ起動だけ）: works の役は本流の役の定義（agents/*.md）を読まないので、
   本流が定義に置く『検索語に対象の名前を載せるな』の規律が役に届かない。包みと同じ置き場の写し agents/judge.md から、頭の行
   QUERY_RULE_HEAD と続く 2 字下げの下位の箇条を字のまま切り出し（字を写さない）、`--append-system-prompt` で足す（本流が役の
   定義を system prompt に足すのと同じ位置）。SDK が `--append-system-prompt` を渡していれば、その値の後ろに空行 1 つで繋ぐ。
   道具ゼロの役（外へ問い合わせられない）には足さない。SDK が `--append-system-prompt-file` を渡した起動と、塊を引けない起動は
   claude を起こさない（fail closed）。塊の sha256 の先頭 16 字を起動の記録の fence.query_rule に残す。包み無しの run には
   載らない（ほかの柵と同じ制約）。経路は argv: SDK 0.3.282 は system prompt を stdin の initialize で渡すが、Claude Code
   2.1.283 は initialize が appendSystemPrompt を持つ時だけ argv の値を置き換え、systemPrompt の置き換え（SDK の既定は []）
   とは別に append を末尾に足す（本体の initialize の受けと system prompt の組み立てで確かめた）。works の YAML は
   systemPrompt を持たないので、initialize に appendSystemPrompt は来ない。役が Agent で起こす子は自分の system prompt で
   起きて塊が届かないので、QUERY_RULE_LEAD が子への指示に塊を含めさせる

14. **対象の持ち主の禁止を写す**（印のある起動だけ）: 役は settingSources: [user] と隔離した設定で起きるので、対象リポジトリの
   project の段を読まず、持ち主が `.claude/settings.json`・`settings.local.json` に置いた permissions.deny が役に効かない。
   project の段を読ませると CLAUDE.md・フックも入るので、役の cwd の worktree の根の 2 つのファイルの permissions.deny だけを
   `--settings` の permissions.deny の後ろに足す（本流 graphloops/engine/role_run.repo_deny と同じ読み方。Claude Code の
   permissions の配列は段をまたいで足し合わされるので、同じ意味になる）。足した数を fence.repo_deny に残す。根を引けない・
   読めない・形が違えば、ファイルを名指して claude を起こさない（fail closed）。Bash の規則は置き場に依らず同じ意味だが、
   `/` 始まりの Read・Edit の規則は設定の出所の置き場から引かれ、`!` の打ち消しは同じ出所の規則にしか効かないので、
   --settings に写した後は対象の意図と指す所・効き方が変わりうる（本流も同じ写し方）

15. **engine の子の目印**（印のある起動だけ）: 子の env に ENGINE_CHILD_ENV=1 を立てる（役の claude の Bash の子へ継がれる）。
   本流 role_run が役・任せ先・書く子に立てるのと同じ名で、対象の重い一式（tests/run.sh・変異の撃ち）はこれを見て AI の役
   からの起動を拒める。線の節（board.py の宣言の一式など）は包みを通らないので立たない。包み無しの run にも立たない。
   同じ子に NO_BG_ENV=1 も立て、役の会話が背景の作業（Bash の run_in_background など）を起こせないようにする。背景を残した
   会話を引き継ぐと、Claude Code がその終わりの知らせを先に処理して依頼の文に届かずに空の result で終わり（origin が
   task-notification・num_turns 0）、16 の no_turn の起こし直しが同じ結果を繰り返して節が落ちた（2026-10-01 の run 155b・155c の tdd）

16. **子の終わりを種分けする**（印の有無に依らない。`--output-format stream-json` の起動だけ）: 子の stdout を継がせずに
   行ごとに同じバイトで写し（relay_out）、1 手も進まずに終わった子（assistant の行が無く result の num_turns が 0。no_turn）の
   result の行だけは Archon へ写さず、木を止めて NO_TURN_EXIT（75）で返す。result を写すと SDK は散文の答えと同じ
   output_contract に落とし、Archon は起こし直さない（run 43・54）。0 でない終了は transient として Archon が上限まで
   起こし直す。result の行は届いた時に決め、手が進んだ起動の result はすぐ写す。写さなかった result は全文を包みの終わりの
   記録 `exits/<key>.jsonl`（claude-adapter の write_exit）に残す
17. **run ごとの書ける置き場**（印のある起動で、`--tools` に Bash・sandbox が enabled・allowWrite に `/` が無い・網を閉じていない・
   切符が在る時だけ）: 役の sandbox が書けるのは cwd と利用者ごとの TMPDIR だけ（Claude Code の既定）で、dev の殻が置く
   uv のキャッシュ（XDG_CACHE_HOME の下）と試験の置き場（linekit.work_home）はその外なので、Bash の役は Operation not
   permitted になる。切符の board の隣 `<board の親>/run-place`（RUN_PLACE_NAME。run ごと。包みが作る）の全部の綴りを
   `sandbox.filesystem.allowWrite` の SDK の項目の後ろに足し（denyWrite が勝つので柵は残る）、子の env に RUN_PLACE_ENV
   （UV_CACHE_DIR・WORKS_RUN_PLACE）を立てる。置き場が役の worktree か守る場所に掛かる（同じ・祖先・子孫）なら足さずに
   fence.run_place.skipped に理由を残し、作れなければ起こさない。TMPDIR は Claude Code が sandbox の中で書ける一時フォルダへ
   向けるので向けず、WORKS_DEV_HOME・XDG_CACHE_HOME は run をまたぐ共有の置き場なので向けない。allowWrite に `/` が在る
   起動（任せ先）・道具ゼロ・Bash の無い役・網を閉じた役・切符の無い起動は sandbox も env も変えない
18. **形ごとの道具の柵**（印のある起動で、切符が在る時だけ。計画 220）: 切符の board の修正の形（fixshape.shape_at。形はいつも
   この口から引く）と印の名から fixshape.denied_tools が返す道具——g3 以外の座の節（SKILL_NODES）の `Skill`、g1 以外の修正役
   （AGENT_NODES）の `Agent`——を `permissions.deny` の後ろに足し、足した数を fence.shape_deny に残す（拒む物が無ければ鍵を
   持たない）。形の控えが壊れている（読めない・語の外）なら、壊れた切符と同じく claude を起こさない（理由に fix_shape）。
   deny は道具の呼びを拒むだけで、YAML の `skills:` が載せたスキルの一覧は system prompt に残る（拒まれた呼びが Archon の
   events に tool_called として出うる。一覧を外すのは YAML の側）

印の無い起動（Archon の題の生成＝`--tools ""` の起動など）は、8 で網を閉じる時の --settings の値のほかは argv を 1 バイトも
変えない（stdin も中継しない。stdout は 16 のとおり同じバイトで写す）。見分けられない形
（印の跡の無い `--json-schema` が 2 つ・読めない JSON・値の無い旗）は足さずに素通しし、警告を 1 行出す。
印の跡（`works-node:`）が --json-schema のどこかに在るのに一番上の description の印として読めない起動（知らない旗・
大文字・余分な空白・入れ子の description・印を持つ --json-schema が 2 つ・壊れた JSON）は、JSON として読めても
読めなくても同じ規則で素通しせず、claude を起こさずに 1 行を出して止まる（黙って新しい会話で再審させず、柵を落とさない）。

置き場（包みの家）は env の `WORKS_ADAPTER_HOME`（無ければ `${XDG_STATE_HOME:-~/.local/state}/works/adapter`。切符と同じ）。Claude の子の env には
ARTIFACTS_DIR が来ないので、run の区別は cwd（Archon が run ごとに切る worktree）の realpath の sha256 の先頭 16 字で付ける:
`sessions/<key>/<節>.id`・`reads/<key>/reads.jsonl`（graphloops の engine の hook_evidence がそのまま読む形）・
`launches/<key>.jsonl`（起動ごとの 1 行。引数の本文は書かない。印のある起動は 9 の版を決めた時か子が終わった時に書く）・
`exits/<key>.jsonl`（16 の即時の死の起動ごとの 1 行）。
家は役の sandbox の Bash から書けない場所に置く。

Python 3.9 でも動く形で書く（`#!/usr/bin/env python3` が macOS の /usr/bin/python3 に当たりうる）。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

import fixshape
import tree_run

ENV_HOME = "WORKS_ADAPTER_HOME"
WRITE_MATCHER = "Edit|Write|NotebookEdit"   # 書き込みの記録のフック（record-write.py）が掛かる道具
WRITES_LOG = "writes.jsonl"
ENV_REAL = "WORKS_REAL_CLAUDE"
MARK_PREFIX = "works-node:"

# continue=X の節で外す SDK の会話の旗。値を持つ物と持たない物
SESSION_VALUE_FLAGS = ("--resume", "-r", "--session-id")
SESSION_BARE_FLAGS = ("--fork-session", "--continue", "-c")

_NAME_RE = re.compile(r"[a-z0-9-]+")   # node_marker._NAME と同じ
# node_marker.FLAGS と同じ。no-post: gh の書き込みの語を柵に足す（仕様 3.8）。no-tree-write: 役の cwd の worktree を柵に足す（裁定 R56）
FLAGS = ("no-post", "no-tree-write", "isolated")
NO_TREE_WRITE = "no-tree-write"
ISOLATED = "isolated"
ISOLATED_PREFIX = "works-isolated-"
MCP_FILE = "works-mcp.json"        # dev/toolset.py の MCP_FILE と同じ（隔離した設定の置き場の下）
WEB_TOOL = "WebFetch"              # これを持つ起動にだけ借りる MCP を渡す
ENV_MCP = "WORKS_CONTEXT7_MCP"     # on の時だけ借りる MCP を渡す（既定は渡さない）
QUERY_RULE_SOURCE = pathlib.Path(__file__).resolve().parent / "agents" / "judge.md"   # 検索語の規律の正本（写し）
QUERY_RULE_HEAD = "- **検索語に対象の名前を載せるな。**"
QUERY_RULE_LEAD = ("外のサービスへ問い合わせる時の決まり（works の包みより。役への直の指示。Agent で子を起こすなら、子への指示に"
                   "下の塊をそのまま含めよ——子にはこの決まりが届かない）:")
REPO_SETTINGS = (pathlib.Path(".claude") / "settings.json", pathlib.Path(".claude") / "settings.local.json")   # role_run と同じ
# 本流 graphloops/engine/role_run.ENGINE_CHILD_ENV と同じ名（対象の入口が既にこの名を読むので、読む側を 2 つにしない）
ENGINE_CHILD_ENV = "GRAPHLOOPS_ENGINE_CHILD"
NO_BG_ENV = "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"   # Claude Code の背景の作業を切る（15 の後半）
RUN_PLACE_NAME = "run-place"   # 切符の board の隣（run ごとの置き場。17）
RUN_PLACE_ENV = {"UV_CACHE_DIR": "uv-cache", "WORKS_RUN_PLACE": ""}   # 子の env 名 → 置き場の下の相対（"" は置き場そのもの）。向け直す物はここだけ
# 印 no-post（読むだけの役）の gh の柵は許す物の一覧で組む。Claude Code の permissions は deny が allow に勝つので
# 「gh を拒んで一部だけ許す」は規則では書けない。そこで gh は丸ごと拒み（Bash(gh:*) と本物の gh の絶対パス）、
# 読む 4 つの形だけを通す口 works-gh（no-post-bin/。env の WORKS_GH が絶対パス）を役に渡す。PATH の頭にも同じ口を
# gh の名で置き、前方一致をすり抜ける呼び方（command gh・xargs gh・sh -c "gh …"）も同じ一覧に通す。git push も拒む
NO_POST_DENY = ("Bash(gh:*)", "Bash(git push:*)")
NO_POST_BIN = pathlib.Path(__file__).resolve().parent / "no-post-bin"
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


class Unrecognised(Exception):
    """argv の形が見分けられない（足さずに素通しする）"""


class BadMarker(Unrecognised):
    """印の跡が在るのに読めない（claude を起こさずに止める。fail closed）"""


class Marker(NamedTuple):
    name: str
    cont: Optional[str]
    flags: Tuple[str, ...]


class Plan(NamedTuple):
    argv: List[str]                 # 子に渡す argv（本物の claude の名は含まない）
    mode: str                       # "merged"（フックを足した）| "passthrough"（足さない）| "refused"（子を起こさない）
    why: Optional[str]              # passthrough・refused の理由
    warn: bool                      # stderr に警告を出すか（印の無い素通しは普段の形なので出さない）
    node: Optional[str]
    cont: Optional[str]
    hook: bool
    tools_empty: bool               # `--tools ""`（題の生成か、道具を持たない役）
    session: Optional[dict]         # {mode: new|sdk-resume|sdk-session|sdk-fork|continued|refused, id, of?, from?}
    record: List[Tuple[pathlib.Path, str]]   # 子を起こす前に書く (id のファイル, id)
    fence: Optional[dict] = None    # {deny_write, permissions_deny, no_post?, isolated?, mcp?, query_rule?, repo_deny?, shape_deny?}（フックを足した起動だけ）
    env: Optional[dict] = None      # 子の env に上書きする物（印のある起動。ENGINE_CHILD_ENV と、no-post の口）
    strict_net: Optional[bool] = None   # 網: True は strictAllowlist で閉じた起動、False は `*` の網、None は網の一覧が無い
    cwd: Optional[str] = None       # 子の cwd（旗 isolated の起動だけ。None なら包みの cwd のまま）


def marker_text(name: str, cont: Optional[str] = None, flags: Sequence[str] = ()) -> str:
    """output_format の description に置く印の 1 行（node_marker.mark の description と同じ）"""
    parts = [MARK_PREFIX, name] + ([f"continue={cont}"] if cont else []) + list(flags)
    return " ".join(parts)


def parse_marker(description) -> Optional[Marker]:
    """description が印なら Marker、印の頭（`works-node:`）を持たなければ None。
    頭を持つのに読めなければ BadMarker（包みは claude を起こさない）。文法は枝 wip/works-a2 の node_marker.parse と同じ:
    `works-node: <名>[ continue=<名>][ <flag>…]`、名は [a-z0-9-]+、区切りは空白 1 つ、flag は FLAGS に在る物を 1 度ずつ"""
    if not isinstance(description, str) or not description.startswith(MARK_PREFIX):
        return None
    bad = BadMarker(f"節の印が読めない: {description!r}")
    if not description.startswith(MARK_PREFIX + " "):
        raise bad
    words = description[len(MARK_PREFIX) + 1:].split(" ")
    if not _NAME_RE.fullmatch(words[0]):
        raise bad
    cont, flags = None, []
    for w in words[1:]:
        if w.startswith("continue="):
            if cont is not None or not _NAME_RE.fullmatch(w[len("continue="):]):
                raise bad
            cont = w[len("continue="):]
        elif w in FLAGS and w not in flags:
            flags.append(w)
        else:
            raise bad
    return Marker(words[0], cont, tuple(flags))


def find_opt(argv: Sequence[str], name: str) -> List[Tuple[int, int, str, bool]]:
    """argv の中の `name v` と `name=v` の全部を (位置, 語の数, 値, = でつないだか) で返す。値の無い旗は Unrecognised"""
    out = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == name:
            if i + 1 >= len(argv):
                raise Unrecognised(f"{name} に値が無い")
            out.append((i, 2, argv[i + 1], False))
            i += 2
            continue
        if a.startswith(name + "="):
            out.append((i, 1, a[len(name) + 1:], True))
        i += 1
    return out


def marker_from_argv(argv: Sequence[str]) -> Optional[Marker]:
    """argv の --json-schema から印を読む。規則は JSON として読めても読めなくても 1 つ:
    一番上の description が印として読めればその印。読めず、--json-schema の本文のどこかに印の跡（`works-node:`）が
    在れば BadMarker（止める）。跡が無ければ、--json-schema が無い・object なら None、形が見分けられなければ Unrecognised"""
    try:
        found = find_opt(argv, "--json-schema")
    except Unrecognised:
        raise Unrecognised("--json-schema に値が無い") from None
    if not found:
        return None
    traced = any(MARK_PREFIX in v for _, _, v, _ in found)
    if len(found) > 1:
        if traced:
            raise BadMarker("--json-schema が 2 つ以上あり、印の跡を持つ")
        raise Unrecognised("--json-schema が 2 つ以上")
    try:
        schema = json.loads(found[0][2])
    except ValueError:
        schema = None
    marker = parse_marker(schema.get("description")) if isinstance(schema, dict) else None   # 崩れた印は BadMarker
    if marker is not None:
        return marker
    if traced:
        raise BadMarker("--json-schema に印の跡が在るのに、一番上の description の印として読めない")
    if not isinstance(schema, dict):
        raise Unrecognised("--json-schema が JSON の object として読めない")
    return None


def home(env=None) -> pathlib.Path:
    """包みの家: ${WORKS_ADAPTER_HOME:-${XDG_STATE_HOME:-$HOME/.local/state}/works/adapter}（ticket.home と同じ。空は無いと同じ）"""
    env = os.environ if env is None else env
    if env.get(ENV_HOME):
        return pathlib.Path(env[ENV_HOME])
    state = env.get("XDG_STATE_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "state")
    return pathlib.Path(state) / "works" / "adapter"


def cwd_key(cwd) -> str:
    return hashlib.sha256(os.path.realpath(str(cwd)).encode("utf-8")).hexdigest()[:16]


def _home_or(home_dir) -> pathlib.Path:
    return home() if home_dir is None else pathlib.Path(home_dir)


def session_path(cwd, node: str, home_dir=None) -> pathlib.Path:
    """節 node が cwd（run の worktree）で使った会話の id のファイル。home_dir を省くと env の家。
    再審の前の確かめ（rejudge の session_ready）も同じ関数で引く"""
    return _home_or(home_dir) / "sessions" / cwd_key(cwd) / f"{node}.id"


def reads_dir(cwd, home_dir=None) -> pathlib.Path:
    """Read のフックが reads.jsonl を書く置き場（engine の hook_evidence の board_dir にそのまま渡せる）"""
    return _home_or(home_dir) / "reads" / cwd_key(cwd)


def writes_path(cwd, home_dir=None) -> pathlib.Path:
    """書き込みのフックの記録（reads_dir と同じ置き場）。包みが印のある起動の前に作る——在ることが「記録を取っている run」の印"""
    return reads_dir(cwd, home_dir) / WRITES_LOG


def launches_path(cwd, home_dir=None) -> pathlib.Path:
    """cwd の起動の記録（1 起動 1 行。launch_row の形）"""
    return _home_or(home_dir) / "launches" / f"{cwd_key(cwd)}.jsonl"


def exits_path(cwd, home_dir=None) -> pathlib.Path:
    """cwd の子の終わりの記録（即時の死の起動だけ 1 行。write の形は claude-adapter の write_exit）"""
    return _home_or(home_dir) / "exits" / f"{cwd_key(cwd)}.jsonl"


def read_exits(cwd, home_dir=None) -> List[dict]:
    """exits_path の行（読めない行は飛ばす。無ければ []）"""
    try:
        text = exits_path(cwd, home_dir).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for ln in text.splitlines():
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def now() -> str:
    """launches の `at`。盤面の state.created（engine の util.now）と同じ、時差つきの ISO 8601（こちらは μ 秒まで）"""
    return datetime.datetime.now().astimezone().isoformat(timespec="microseconds")


def launch_row(p: "Plan", cwd, pid: int, at: str) -> dict:
    """launches の 1 行。引数の本文は書かない。
    `session` は {mode, id, of?, from?}: mode は new・sdk-resume・sdk-session・sdk-fork・continued・refused。
    `from` は既に在る会話を開いた起動（sdk-resume・sdk-fork・continued）の元の会話の id（sdk-fork だけ id と違う）。
    `model` は Archon がこの起動に渡した `--model`（要求した模型。応答が名乗る模型ではない。無ければ None＝CLI の既定）。
    `effort` は同じく Archon がこの起動に渡した `--effort`（無ければ None＝CLI の既定か設定。SDK が旗でない経路で渡しても None）"""
    return {"at": at, "pid": pid, "cwd": os.path.realpath(str(cwd)), "node": p.node, "continue": p.cont,
            "mode": p.mode, "why": p.why, "hook": p.hook, "tools_empty": p.tools_empty, "session": p.session,
            "fence": p.fence, "strict_net": p.strict_net, "model": requested_flag(p.argv, "--model"),
            "effort": requested_flag(p.argv, "--effort")}


def requested_flag(argv: Sequence[str], flag: str) -> Optional[str]:
    """argv の最後の flag の値（CLI は後の指定が勝つ）。無い・値の無い旗は None"""
    try:
        found = find_opt(argv, flag)
    except Unrecognised:
        return None
    return found[-1][2] if found else None


def read_launches(cwd, home_dir=None) -> List[dict]:
    """cwd の起動の記録を古い順に。無い・読めない行は飛ばす"""
    try:
        text = launches_path(cwd, home_dir).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for ln in text.splitlines():
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def last_launch(cwd, node: str, home_dir=None) -> Optional[dict]:
    """cwd で節 node を起こした最後の行（無ければ None）"""
    rows = [r for r in read_launches(cwd, home_dir) if r.get("node") == node]
    return rows[-1] if rows else None


def read_session_id(path: pathlib.Path) -> Optional[str]:
    """id のファイルの中身。無い・読めない・空・1 語でない時は None"""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text if _ID_RE.match(text) else None


def hook_settings(command: str, write_command: Optional[str] = None) -> dict:
    """足す設定。期限は足さない（Claude の既定のまま）。write_command が在れば書き込みの記録のフックも足す"""
    post = [{"matcher": "Read", "hooks": [{"type": "command", "command": command}]}]
    if write_command:
        post.append({"matcher": WRITE_MATCHER, "hooks": [{"type": "command", "command": write_command}]})
    return {"hooks": {"PostToolUse": post}}


def hook_command(python: str, recorder, sink) -> str:
    return " ".join(shlex.quote(str(x)) for x in (python, recorder, sink))


def merge_settings(sdk: dict, ours: dict) -> dict:
    """ours を sdk に足す。hooks の出来事ごとの配列は後ろに足し、辞書は潜り、それ以外は SDK の値を残す"""
    for k, v in ours.items():
        if k == "hooks" and isinstance(v, dict):
            h = sdk.setdefault("hooks", {})
            if not isinstance(h, dict):
                raise Unrecognised("--settings の hooks が object でない")
            for ev, matchers in v.items():
                cur = h.setdefault(ev, [])
                if not isinstance(cur, list):
                    raise Unrecognised(f"--settings の hooks.{ev} が配列でない")
                cur.extend(matchers)
        elif isinstance(v, dict) and isinstance(sdk.get(k), dict):
            merge_settings(sdk[k], v)
        else:
            sdk.setdefault(k, v)
    return sdk


def _load_settings(value: str) -> dict:
    if value.lstrip().startswith("{"):
        try:
            data = json.loads(value)
        except ValueError:
            raise Unrecognised("--settings の JSON が読めない") from None
    else:
        try:
            with open(value, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError, UnicodeDecodeError):
            raise Unrecognised("--settings が JSON でも読めるファイルでもない") from None
    if not isinstance(data, dict):
        raise Unrecognised("--settings が JSON の object でない")
    return data


def find_gh(path_env: str) -> List[str]:
    """PATH の上の本物の gh の絶対パス（no-post-bin の口は除く。前から順に、重なりは 1 つ）"""
    out = []
    skip = os.path.realpath(str(NO_POST_BIN))
    for d in path_env.split(os.pathsep):
        if not d or not os.path.isabs(d) or os.path.realpath(d) == skip:
            continue
        c = os.path.join(d, "gh")
        if os.path.isfile(c) and os.access(c, os.X_OK) and c not in out:
            out.append(c)
    return out


def no_post_rules(gh_paths: Sequence[str]) -> List[str]:
    """no-post の起動の permissions.deny: NO_POST_DENY と、本物の gh の絶対パス（綴り・realpath・/private の別名の全部）"""
    rules = list(NO_POST_DENY)
    for g in gh_paths:
        for p in spellings(g):
            r = f"Bash({p}:*)"
            if r not in rules:
                rules.append(r)
    return rules


def no_post_env(env, gh_paths: Sequence[str]) -> dict:
    """no-post の起動の子の env の差し替え: PATH の頭に口の置き場、WORKS_GH（口）、WORKS_REAL_GH（口が起こす本物の gh）"""
    return {"PATH": str(NO_POST_BIN) + os.pathsep + env.get("PATH", ""),
            "WORKS_GH": str(NO_POST_BIN / "works-gh"),
            "WORKS_REAL_GH": gh_paths[0] if gh_paths else "",
            "WORKS_GH_ACTIVE": ""}   # 外から漏れた口の輪止めの印で、役の口が全部拒まれないように空にする


def _put_settings(argv: List[str], found, doc: dict) -> List[str]:
    """argv の --settings（find_opt の 1 つ。無ければ None）の値を doc の JSON に差し替える（綴りは元のまま。無ければ後ろに足す）"""
    text = json.dumps(doc, ensure_ascii=False)
    if found is None:
        return argv + ["--settings", text]
    i, n, _, joined = found
    return argv[:i] + (["--settings=" + text] if joined else ["--settings", text]) + argv[i + n:]


def strict_network(argv: List[str]) -> Tuple[List[str], Optional[bool]]:
    """8. 網を閉じる。--settings の sandbox.network.allowedDomains が配列で `*` を含まなければ strictAllowlist: true を足した
    argv と True を返す（もう true なら argv はそのまま）。`*` を含めば (argv, False)、網の一覧が無ければ (argv, None)。
    --settings が読めない・2 つ・値が無い・sandbox／network／一覧の形が違えば Unrecognised（呼び手は起動を拒む）"""
    found = find_opt(argv, "--settings")   # 値の無い旗は Unrecognised
    if not found:
        return argv, None
    if len(found) > 1:
        raise Unrecognised("--settings が 2 つ以上")
    doc = _load_settings(found[0][2])
    if "sandbox" not in doc:
        return argv, None
    sandbox = doc["sandbox"]
    if not isinstance(sandbox, dict):
        raise Unrecognised("--settings の sandbox が object でない")
    if "network" not in sandbox:
        return argv, None
    net = sandbox["network"]
    if not isinstance(net, dict):
        raise Unrecognised("--settings の sandbox.network が object でない")
    if "allowedDomains" not in net:
        return argv, None
    allowed = net["allowedDomains"]
    if not isinstance(allowed, list) or not all(isinstance(d, str) for d in allowed):
        raise Unrecognised("--settings の sandbox.network.allowedDomains が文字列の配列でない")
    if "*" in allowed:
        return argv, False
    if net.get("strictAllowlist") is True:
        return argv, True
    net["strictAllowlist"] = True
    return _put_settings(argv, found[0], doc), True


def _overlaps(a: str, b: str) -> bool:
    """a と b が同じ・祖先・子孫か（全部の綴りで比べる）"""
    for x in spellings(a):
        for y in spellings(b):
            if x == y or x.startswith(y.rstrip("/") + "/") or y.startswith(x.rstrip("/") + "/"):
                return True
    return False


def board_of(ticket_doc: Optional[dict]) -> Optional[str]:
    """切符の board（正規化した絶対パス）。切符が無ければ None。絶対パスの文字列でなければ BadTicket（「切符が無い」に化かさない）"""
    if ticket_doc is None:
        return None
    board = ticket_doc.get("board")
    if not isinstance(board, str) or not os.path.isabs(board):
        raise BadTicket(f"切符の board が絶対パスの文字列でない（{board!r}）")
    return os.path.normpath(board)


def shape_deny(board_dir: Optional[str], node: str) -> Tuple[str, ...]:
    """18. 盤面 board_dir の修正の形で印 node の役に拒む道具。切符が無ければ ()。形の控えが壊れていれば Unrecognised
    （理由に fix_shape。呼び手は起動を拒む）"""
    if board_dir is None:
        return ()
    try:
        return fixshape.denied_tools(fixshape.shape_at(board_dir), node)
    except ValueError as e:
        raise Unrecognised(f"盤面の修正の形（{fixshape.KEY}）が読めない（{e}）") from None


def run_place_of(ticket_doc: Optional[dict]) -> Optional[str]:
    """17. 切符の board の隣の run ごとの置き場（<board の親>/run-place）。切符が無ければ None。切符の board が絶対パスの文字列でなければ
    BadTicket（壊れた切符の理由を「切符が無い」に化かさず、起動を拒ませる）"""
    board = board_of(ticket_doc)
    return None if board is None else os.path.join(os.path.dirname(board), RUN_PLACE_NAME)


def with_run_place(doc: dict, tools: set, board_place: Optional[str], strict: Optional[bool], keep_out: Sequence[str]) \
        -> Tuple[Optional[str], Optional[str]]:
    """17. 対象の起動（Bash を持つ・sandbox が enabled・allowWrite に `/` が無い・網を閉じていない）なら、置き場の全部の綴りを
    doc の sandbox.filesystem.allowWrite の後ろに足し、置き場とその下の道具の置き場を作る。(足した置き場, 足さなかった理由)
    を返す（対象外は (None, None)。足せない対象は理由つき）。keep_out は置き場が掛かってはいけない所（役の worktree・守る場所）。
    作れなければ Unrecognised（呼び手は起動を拒む）"""
    sandbox = doc.get("sandbox")
    if "Bash" not in tools or not isinstance(sandbox, dict) or sandbox.get("enabled") is not True or strict is True:
        return None, None
    fs = sandbox.get("filesystem")
    if fs is not None and not isinstance(fs, dict):
        raise Unrecognised("--settings の sandbox.filesystem が object でない")
    aw = (fs or {}).get("allowWrite", [])
    if not isinstance(aw, list):
        raise Unrecognised("--settings の sandbox.filesystem.allowWrite が配列でない")
    if "/" in aw:
        return None, None
    if board_place is None:   # 切符が無い起動は sandbox も env も変えず、記録にも残さない（17）
        return None, None
    for k in keep_out:
        if _overlaps(board_place, k):
            return None, f"置き場が守る場所か役の worktree に掛かる（{k}）"
    try:
        for rel in RUN_PLACE_ENV.values():
            os.makedirs(os.path.join(board_place, rel), mode=0o700, exist_ok=True)
    except OSError as e:
        raise Unrecognised(f"run ごとの置き場を作れない（{board_place}: {e}）") from None
    fs = sandbox.setdefault("filesystem", {})
    allow = fs.setdefault("allowWrite", [])
    for p in spellings(board_place):
        if p not in allow:
            allow.append(p)
    return board_place, None


def _with_hook(argv: List[str], command: str, protected: Sequence[str],
               no_post: Optional[Sequence[str]] = None, write_command: Optional[str] = None,
               repo: Sequence[str] = (), place: Optional[Tuple[Optional[str], Optional[bool], Sequence[str]]] = None,
               tools_deny: Sequence[str] = ()) -> Tuple[List[str], dict]:
    """place は 17 の (board の隣の置き場, strict_network の値, 置き場が掛かってはいけない所)。省けば足さない。
    tools_deny は 18 の形ごとに拒む道具（空なら足さず、fence.shape_deny の鍵も持たない）"""
    found = find_opt(argv, "--settings")
    if len(found) > 1:
        raise Unrecognised("--settings が 2 つ以上")
    ours = hook_settings(command, write_command)
    doc = merge_settings(_load_settings(found[0][2]), ours) if found else ours
    n_write, n_deny = add_fences(doc, protected) if protected else (0, 0)
    fence = {"deny_write": n_write, "permissions_deny": n_deny}
    if place is not None:
        added, skipped = with_run_place(doc, _tools(argv), *place)
        if added:
            fence["run_place"] = added
        elif skipped:
            fence["run_place"] = {"skipped": skipped}
    if repo:
        fence["repo_deny"] = add_deny(doc, repo)
    if tools_deny:
        fence["shape_deny"] = add_deny(doc, tools_deny)
    if no_post is not None:
        fence["no_post"] = add_deny(doc, no_post_rules(no_post))
    return _put_settings(argv, found[0] if found else None, doc), fence


# --- 起動ごとの柵 ---------------------------------------------------------------------------------------------
GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")   # ticket.py と同じ（外から漏れると別のリポジトリを見る）
_ALIASES = (("/private/var", "/var"), ("/private/tmp", "/tmp"), ("/private/etc", "/etc"))


def ticket_path(cwd, home_dir=None) -> pathlib.Path:
    """切符の置き場（ticket.ticket_path と同じ式）"""
    return _home_or(home_dir) / "tickets" / f"{cwd_key(cwd)}.json"


class BadTicket(Exception):
    """切符のファイルが在るのに読めない（印のある起動は柵なしで起こさない）"""


def read_ticket(cwd, home_dir=None) -> Optional[dict]:
    """切符（ticket.read の代わりの薄い口。枝 wip/works-a4 の ticket.py と同じファイルを読む）。
    ファイルが無ければ None。在るのに読めない・object でない・protected が絶対パスの文字列の配列でなければ BadTicket"""
    path = ticket_path(cwd, home_dir)
    if not os.path.lexists(str(path)):
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise BadTicket(f"切符が読めない: {path}（{e}）") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("protected"), list) \
            or not all(isinstance(p, str) and os.path.isabs(p) for p in doc["protected"]):
        raise BadTicket(f"切符の形が違う（protected は絶対パスの配列）: {path}")
    return doc


def _alias(p: str) -> Optional[str]:
    for priv, pub in _ALIASES:
        for a, b in ((priv, pub), (pub, priv)):
            if p == a or p.startswith(a + "/"):
                return b + p[len(a):]
    return None


def spellings(path: str) -> List[str]:
    """同じ場所の綴りの全部: 渡された形・realpath・macOS の /var↔/private/var・/tmp↔/private/tmp・/etc↔/private/etc"""
    out: List[str] = []
    for p in (os.path.normpath(path), os.path.realpath(path)):
        for q in (p, _alias(p)):
            if q and q not in out:
                out.append(q)
    return out


def live_worktrees(cwd) -> List[str]:
    """cwd のリポジトリの今の worktree（元の作業ツリーを含む）のうち、cwd の worktree 自身でない物。git が引けなければ []"""
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROP}
    try:
        own = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True, encoding="utf-8",
                             env=env, check=True).stdout.strip()
        listed = subprocess.run(["git", "-C", str(cwd), "worktree", "list", "--porcelain"], capture_output=True,
                                text=True, encoding="utf-8", env=env, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    trees = [ln[len("worktree "):] for ln in listed.splitlines() if ln.startswith("worktree ")]
    return [t for t in trees if os.path.realpath(t) != os.path.realpath(own)]


def own_worktree(cwd) -> Optional[str]:
    """役の cwd の worktree の根（git rev-parse --show-toplevel）。git が引けなければ None"""
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROP}
    try:
        top = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True, encoding="utf-8",
                             env=env, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return top or None


def repo_deny(cwd) -> List[str]:
    """14. 役の cwd の worktree の根の REPO_SETTINGS が宣言した permissions.deny（置き場の順・重なりを除く）。本流
    graphloops/engine/role_run.repo_deny と同じ読み方で、allow・ask・ほかの鍵は読まない。置き場が無い・Git の作業ツリーで
    ない cwd は空。根を引けない・どれかの置き場が読めない・形が違えば、そのファイルを名指して Unrecognised（黙って落とさない）"""
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROP}
    try:
        r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                           encoding="utf-8", env=env)
    except OSError as e:
        raise Unrecognised(f"対象リポジトリの根を引けない（{e}）——{REPO_SETTINGS[0]} の permissions.deny を写せない") from None
    if r.returncode != 0 or not r.stdout.strip():
        if "not a git repository" in r.stderr:
            return []
        raise Unrecognised(f"対象リポジトリの根を引けない（{r.stderr.strip()[:200]}）——"
                           f"{REPO_SETTINGS[0]} の permissions.deny を写せない")
    out: List[str] = []
    for rel in REPO_SETTINGS:
        p = pathlib.Path(r.stdout.strip()) / rel
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise Unrecognised(f"{p} が読めない（{e}）——このファイルを直せ（permissions.deny を役に写せない）") from None
        perms = data.get("permissions", {}) if isinstance(data, dict) else None
        deny = perms.get("deny", []) if isinstance(perms, dict) else None
        if not (isinstance(deny, list) and all(isinstance(x, str) and x for x in deny)):
            raise Unrecognised(f"{p} の permissions.deny が空でない文字列の一覧でない——このファイルを直せ")
        out += [x for x in dict.fromkeys(deny) if x not in out]
    return out


def _no_tree_write_places(argv: Sequence[str], cwd, ticketed: bool) -> List[str]:
    """旗 no-tree-write の起動で足す守る場所（役の cwd の worktree の根の全部の綴り）。起こせない時は Unrecognised"""
    found = find_opt(argv, "--settings")
    sandbox = _load_settings(found[0][2]).get("sandbox") if len(found) == 1 else None
    if not (isinstance(sandbox, dict) and sandbox.get("enabled") is True):
        raise Unrecognised("旗 no-tree-write の役に SDK が sandbox の塊（enabled: true）を渡していない——作業ツリーを守る"
                           "denyWrite を足す先が無い")
    if not (sandbox.get("allowUnsandboxedCommands") is False and sandbox.get("failIfUnavailable") is True):
        raise Unrecognised("旗 no-tree-write の役の sandbox が allowUnsandboxedCommands: false・failIfUnavailable: true でない——"
                           "sandbox の外で走る Bash・sandbox が立たない場の素通しには denyWrite が効かない")
    if not ticketed:
        raise Unrecognised("旗 no-tree-write の役に切符が無い——allowWrite ['/'] の下で盤面・pack・git の設定を守れない")
    top = own_worktree(cwd)
    if top is None:
        raise Unrecognised(f"旗 no-tree-write の役の cwd の worktree の根が git から引けない（{cwd}）")
    return spellings(top)


def protected_now(ticket_doc: dict, cwd, env, worktrees: Sequence[str]) -> List[str]:
    """この起動で守る場所: 切符の protected ＋ 起動の env の CLAUDE_CONFIG_DIR ＋ 今の worktree。全部の綴りで。
    切符の項はそのまま写す（役の worktree の `<cwd>/.git` のように cwd の中の物も守る。何を守るかは ticket.py が決める）。
    worktrees は live_worktrees の値で、役の cwd の worktree 自身は既に外してある"""
    places = list(ticket_doc.get("protected") or [])
    if env.get("CLAUDE_CONFIG_DIR"):
        places.append(os.path.abspath(env["CLAUDE_CONFIG_DIR"]))
    places += list(worktrees)
    out, seen = [], set()
    for p in places:
        for s in spellings(p):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def deny_rules(paths: Sequence[str]) -> List[str]:
    """permissions.deny の規則。`//` で始まる形が絶対パス（Claude Code の規則の書き方）"""
    rules = []
    for p in paths:
        body = "/" + p                   # "/abs" → "//abs"
        for tool in ("Edit", "Write"):
            rules += [f"{tool}({body})", f"{tool}({body}/**)"]
    return rules


def add_deny(settings: dict, rules: Sequence[str]) -> int:
    """permissions.deny の後ろに rules を足す（在る物は足さない）。足した数"""
    perms = settings.setdefault("permissions", {})
    if not isinstance(perms, dict):
        raise Unrecognised("--settings の permissions が object でない")
    deny = perms.setdefault("deny", [])
    if not isinstance(deny, list):
        raise Unrecognised("--settings の permissions.deny が配列でない")
    n = 0
    for r in rules:
        if r not in deny:
            deny.append(r)
            n += 1
    return n


def add_fences(settings: dict, paths: Sequence[str]) -> Tuple[int, int]:
    """settings に柵を足す（SDK の項目は消さず、後ろに足す）。足した (denyWrite の数, permissions.deny の数)"""
    n_deny = add_deny(settings, deny_rules(paths))
    n_write = 0
    sandbox = settings.get("sandbox")
    if isinstance(sandbox, dict):
        fs = sandbox.setdefault("filesystem", {})
        if not isinstance(fs, dict):
            raise Unrecognised("--settings の sandbox.filesystem が object でない")
        dw = fs.setdefault("denyWrite", [])
        if not isinstance(dw, list):
            raise Unrecognised("--settings の sandbox.filesystem.denyWrite が配列でない")
        for p in paths:
            if p not in dw:
                dw.append(p)
                n_write += 1
    return n_write, n_deny


# --- 起動に柵が掛かったか（包みを宣言した run の CI の任せ先の役の受け付けが使う。裁定 R58。Task 22 の h-judge も使える） ----
def _at(s) -> Optional[datetime.datetime]:
    try:
        t = datetime.datetime.fromisoformat(str(s))
    except ValueError:
        return None
    return t if t.tzinfo else None


def fenced_launch(cwd, node: str, since: str, home_dir=None) -> Optional[str]:
    """since（時差つきの ISO 8601）より後の節 node の起動が、包みを通り（mode merged）、柵 no_tree_write が cwd の worktree の根
    だったか。全部よければ None、でなければ理由の 1 文。起こさなかった起動（refused）は害が無いので数えないが、merged が
    1 つも無ければ理由を返す。印の無い起動（題の生成など）は node が無いので見ない"""
    top = own_worktree(cwd)
    if top is None:
        return f"{cwd} の worktree の根が git から引けない"
    start = _at(since)
    if start is None:
        return f"試行の時刻が読めない（{since!r}）"
    rows = [r for r in read_launches(cwd, home_dir)
            if r.get("node") == node and (_at(r.get("at")) or start) > start]
    where = launches_path(cwd, home_dir)
    if not rows:
        return f"包みの起動の記録（{where}）にこの試行の節 {node} の起動が無い（包みを通らずに起こされた）"
    root = os.path.realpath(top)
    for r in rows:
        mode = r.get("mode")
        if mode == "refused":
            continue
        mark = (r.get("fence") or {}).get("no_tree_write") if isinstance(r.get("fence"), dict) else None
        if mode != "merged" or not isinstance(mark, str) or os.path.realpath(mark) != root:
            return (f"節 {node} の起動（{r.get('at')}・{mode}）に柵 no_tree_write（{root}）が掛かっていない"
                    f"（fence: {r.get('fence')!r}。記録 {where}）")
    if not any(r.get("mode") == "merged" for r in rows):
        return f"節 {node} は包みに拒まれ、起こされていない（記録 {where}）"
    return None


def _strip_session_flags(argv: List[str]) -> List[str]:
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in SESSION_VALUE_FLAGS:
            # 値の無い --resume（対話で選ぶ形）も外す。次の語が旗なら値ではない
            i += 2 if i + 1 < len(argv) and not argv[i + 1].startswith("-") else 1
            continue
        if a in SESSION_BARE_FLAGS or any(a.startswith(f + "=") for f in SESSION_VALUE_FLAGS if f.startswith("--")):
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def _tools_empty(argv: Sequence[str]) -> bool:
    try:
        return any(v == "" for _, _, v, _ in find_opt(argv, "--tools"))
    except Unrecognised:
        return False


def isolated_place(cwd, env=None) -> pathlib.Path:
    """旗 isolated の子の cwd: <一時の置き場（env の TMPDIR か tempfile の既定）>/works-isolated-<cwd の hash>"""
    import tempfile
    env = os.environ if env is None else env
    root = env.get("TMPDIR") or tempfile.gettempdir()
    return pathlib.Path(os.path.realpath(root)) / (ISOLATED_PREFIX + cwd_key(cwd))


def _inside_git(path: pathlib.Path) -> bool:
    """path が Git の作業ツリーの中か（git が引けない・外なら偽。GIT_DIR などの env は落とす——live_worktrees と同じ）"""
    env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROP}
    try:
        r = subprocess.run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, encoding="utf-8",
                           env=env)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def plan(argv: Sequence[str], cwd, home_dir, command: str,
         new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
         protected: Optional[Callable[[], Sequence[str]]] = None, env=None, write_command: Optional[str] = None,
         run_place: Optional[Callable[[], Optional[str]]] = None,
         board: Optional[Callable[[], Optional[str]]] = None) -> Plan:
    """argv をどう直すかを決める（ファイルは id の読みと --settings のファイルの読みだけ。書くのは旗 isolated と 17 の置き場の mkdir）。
    protected は守る場所を返す関数（印のある起動でだけ呼ぶ。切符が無ければ None、在るのに読めなければ BadTicket）。
    run_place は 17 の置き場（run_place_of の値。切符が無ければ None）を返す関数。protected と同じ切符の 1 回の読みを使う。
    board は 18 の切符の board（board_of の値。切符が無ければ None）を返す関数。同じ切符の 1 回の読みを使う。
    write_command は書き込みの記録のフックのコマンド（包みが渡す。無ければ Read のフックだけ）。
    env は起動の env（no-post の起動で本物の gh を PATH から引き、子の PATH を組むのに使う。省けば os.environ）。
    子の env の上書き（Plan.env）は印のある起動の全部に付く（15 の目印。no-post なら 5 の口も）"""
    argv = list(argv)
    tools_empty = _tools_empty(argv)
    unknown = None
    try:
        marker = marker_from_argv(argv)
    except BadMarker as e:
        return Plan(argv, "refused", f"works: {e}。claude を起こさない（印を直す）", True, None, None, False,
                    tools_empty, {"mode": "refused", "id": None}, [])
    except Unrecognised as e:
        marker, unknown = None, e
    # 8. 網を閉じる（印の有無に依らない）。閉じられるかが決まらない起動は起こさない
    try:
        argv, strict = strict_network(argv)
    except Unrecognised as e:
        return _refuse(argv, marker.name if marker else None, marker.cont if marker else None, tools_empty,
                       f"sandbox の網を閉じられない（{e}）")
    if unknown is not None:
        return Plan(argv, "passthrough", str(unknown), True, None, None, False, tools_empty, None, [], strict_net=strict)
    if marker is None:
        return Plan(argv, "passthrough", "unmarked", False, None, None, False, tools_empty, None, [], strict_net=strict)

    home_dir = _home_or(home_dir)
    node, cont = marker.name, marker.cont
    # 1. 会話の継ぎ（--settings の形に依らずに行う）
    record: List[Tuple[pathlib.Path, str]] = []
    if cont:
        src = session_path(cwd, cont, home_dir)
        sid = read_session_id(src)
        if sid is None:
            why = f"works: 会話 {cont} の id が無い（節 {node} は {cont} の続きとして起こす）: {src}"
            return Plan(argv, "refused", why, True, node, cont, False, tools_empty,
                        {"mode": "refused", "id": None, "of": cont}, [])
        out = _strip_session_flags(argv) + ["--resume", sid]
        session = {"mode": "continued", "id": sid, "of": cont, "from": sid}
    else:
        out = argv
        try:
            resumed = find_opt(argv, "--resume")
            given = find_opt(argv, "--session-id")
        except Unrecognised as e:
            return _refuse(argv, node, cont, tools_empty, f"会話の旗が見分けられない（{e}）")
        src = resumed[-1][2] if resumed else None
        if given:
            sid, mode = given[-1][2], "sdk-fork" if src and "--fork-session" in argv else "sdk-session"
        elif src and "--fork-session" in argv:
            sid, mode = new_id(), "sdk-fork"
            out = argv + ["--session-id=" + sid]
        elif src:
            sid, mode = src, "sdk-resume"
        else:
            sid, mode = new_id(), "new"
            out = argv + ["--session-id=" + sid]
        session = {"mode": mode, "id": sid}
        if src:
            session["from"] = src
    record.append((session_path(cwd, node, home_dir), sid))

    # 2. Read のフックと柵。印のある起動は、柵を足せなければ起こさない（fail closed）
    env = os.environ if env is None else env
    gh = find_gh(env.get("PATH", "")) if "no-post" in marker.flags else None
    try:
        places = protected() if protected else None
        own = _no_tree_write_places(argv, cwd, places is not None) if NO_TREE_WRITE in marker.flags else []
        board_place = run_place() if run_place else None
        tools_deny = shape_deny(board() if board else None, node)
        out, fence = _with_hook(out, command, list(places or []) + [p for p in own if p not in (places or [])], gh,
                                write_command, repo_deny(cwd),
                                (board_place, strict, list(places or []) + [os.path.abspath(str(cwd))]) if run_place else None,
                                tools_deny)
    except (Unrecognised, BadTicket) as e:
        return _refuse(argv, node, cont, tools_empty, f"柵を足せない（{e}）")
    if own:
        fence["no_tree_write"] = own[0]
    child_cwd = None
    if ISOLATED in marker.flags:
        if not tools_empty:
            return _refuse(argv, node, cont, tools_empty, "旗 isolated は道具ゼロの役（--tools \"\"）だけに付く")
        place = isolated_place(cwd, env)
        try:
            place.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as e:
            return _refuse(argv, node, cont, tools_empty, f"Git の外の置き場を作れない（{place}: {e}）")
        if _inside_git(place):
            return _refuse(argv, node, cont, tools_empty, f"Git の外の置き場が Git の作業ツリーの中にある（{place}）")
        child_cwd = str(place)
        fence["isolated"] = child_cwd
    mcp = mcp_config(out, env, tools_empty or ISOLATED in marker.flags)
    if mcp is not None:
        out, fence["mcp"] = mcp
    if not tools_empty:   # 道具ゼロの役は外へ問い合わせられない
        try:
            out, fence["query_rule"] = with_query_rule(out)
        except Unrecognised as e:
            return _refuse(argv, node, cont, tools_empty, f"検索語の規律を足せない（{e}）")
    child_env = {**(no_post_env(env, gh) if gh is not None else {}), ENGINE_CHILD_ENV: "1", NO_BG_ENV: "1"}
    if isinstance(fence.get("run_place"), str):   # 17。外から立っていた値は置き場の物に替わる（替えた名を記録に残す）
        child_env.update({k: os.path.join(fence["run_place"], rel).rstrip("/") for k, rel in RUN_PLACE_ENV.items()})
        replaced = sorted(k for k in RUN_PLACE_ENV if env.get(k) and env[k] != child_env[k])
        if replaced:
            fence["run_place_replaced_env"] = replaced
    return Plan(out, "merged", None, False, node, cont, True, tools_empty, session, record, fence, child_env,
                strict_net=strict, cwd=child_cwd)


def _tools(argv: Sequence[str]) -> set:
    """--tools の値の道具の名（, と空白で切る）"""
    try:
        return {t for _, _, v, _ in find_opt(argv, "--tools") for t in re.split(r"[,\s]+", v) if t}
    except Unrecognised:
        return set()


def mcp_config(argv: List[str], env, no_tools: bool) -> Optional[Tuple[List[str], dict]]:
    """10. 借りる MCP のファイルを --mcp-config で足した argv と、起動の記録に書く fence.mcp。ファイルが無ければ None"""
    cfg = env.get("CLAUDE_CONFIG_DIR")
    path = pathlib.Path(cfg) / MCP_FILE if cfg else None
    if path is None or not path.is_file():
        return None
    if str(env.get(ENV_MCP, "")).strip().lower() != "on":
        return argv, {"skipped": f"既定では渡さない（{ENV_MCP}=on の時だけ渡す）"}
    if no_tools or WEB_TOOL not in _tools(argv):
        return argv, {"skipped": "web を持たない役（--tools に WebFetch が無い）には渡さない"}
    try:
        if find_opt(argv, "--mcp-config"):
            return argv, {"skipped": "SDK が --mcp-config を渡した（混ぜない）"}
    except Unrecognised:
        return argv, {"skipped": "SDK の --mcp-config に値が無い"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        servers = sorted(doc["mcpServers"])
    except (OSError, ValueError, TypeError, KeyError) as e:
        return argv, {"skipped": f"{path} が読めない（{type(e).__name__}）"}
    return list(argv) + ["--mcp-config=" + str(path)], {"file": str(path), "servers": servers}


def query_rule(path: pathlib.Path = QUERY_RULE_SOURCE) -> str:
    """13. 写しの agents/judge.md から検索語の規律の塊（頭の行 QUERY_RULE_HEAD と、続く 2 字下げの下位の箇条）を字のまま切り出す。
    ファイルが読めない・頭の行が無ければ Unrecognised（呼び手は起動を拒む）"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        raise Unrecognised(f"検索語の規律の正本 {path} が読めない（{type(e).__name__}）") from None
    start = next((i for i, ln in enumerate(lines) if ln.startswith(QUERY_RULE_HEAD)), None)
    if start is None:
        raise Unrecognised(f"検索語の規律の正本 {path} に頭の行が無い")
    end = start + 1
    while end < len(lines) and lines[end].startswith("  - "):
        end += 1
    return "\n".join(lines[start:end])


def with_query_rule(argv: List[str]) -> Tuple[List[str], str]:
    """13. --append-system-prompt に検索語の規律を足した argv と、塊の sha256 の先頭 16 字。SDK の値が在れば後ろに空行 1 つで
    繋ぐ（旗を 2 つにしない）。SDK が --append-system-prompt-file を渡した・--append-system-prompt が 2 つ・塊を引けなければ
    Unrecognised"""
    if find_opt(argv, "--append-system-prompt-file"):
        raise Unrecognised("SDK が --append-system-prompt-file を渡した（検索語の規律を繋げない）")
    found = find_opt(argv, "--append-system-prompt")
    if len(found) > 1:
        raise Unrecognised("--append-system-prompt が 2 つ以上")
    block = query_rule()
    text = QUERY_RULE_LEAD + "\n" + block
    digest = hashlib.sha256(block.encode("utf-8")).hexdigest()[:16]
    if not found:
        return argv + ["--append-system-prompt", text], digest
    i, n, value, joined = found[0]
    value = value + "\n\n" + text
    return argv[:i] + (["--append-system-prompt=" + value] if joined else ["--append-system-prompt", value]) + argv[i + n:], digest


def _refuse(argv, node, cont, tools_empty, why) -> Plan:
    session = {"mode": "refused", "id": None}
    if cont:
        session["of"] = cont
    who = f"節 {node} " if node else "印の無い起動"
    return Plan(list(argv), "refused", f"works: {who}を起こさない: {why}", True, node, cont, False, tools_empty,
                session, [])


# --- 指示書の全文版と差分版（9） ------------------------------------------------------------------------------
VARIANTS_SUFFIX = ".variants.json"
_PROMPT_PATH_RE = re.compile(r"/[^\s`'\"<>|*?]+?\.md(?![A-Za-z0-9_.-])")
# 会話の中身が減った跡（Claude Code 2.1.283 の transcript の system の subtype と、消された道具の結果の置き換えの文）
COMPACT_MARKS = (b'"compact_boundary"', b'"microcompact_boundary"', b'"isCompactSummary":true',
                 b"[Old tool result content cleared]")
DELTA_HEAD = ("（works の包みより: この指示書は差分版。共有の規則は、この会話の前の回に読んだ全文版 `{full}` に在る。"
              "会話の中に規則の本文が見えない時——要約された・古い道具の結果が消された・<persisted-output> に置き換わった時も——は、"
              "先に `{full}` を Read で全部読め）\n\n")


def delta_text(delta: str, full) -> str:
    """包みが指示書に書く差分版（頭に全文版のパスを名指す 1 段を置く。会話から規則が消えていても役が読み直せるように）"""
    return DELTA_HEAD.format(full=os.path.realpath(str(full))) + delta


def user_text(line: bytes) -> Optional[str]:
    """stream-json の 1 行が user の指示文なら、その文（text の塊をつないだ物）。ほかは None"""
    try:
        d = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(d, dict) or d.get("type") != "user" or not isinstance(d.get("message"), dict):
        return None
    content = d["message"].get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c["text"] for c in content
                         if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str))
    return None


class Doubt(Exception):
    """版を決められない（指示書に触らず、理由を記録に残す）"""


def _variants(text: str) -> Optional[Tuple[pathlib.Path, pathlib.Path]]:
    """指示文に名指された .md のうち、隣に <stem>.variants.json が在る物 (指示書, variants.json)。無ければ None、2 つ以上は Doubt"""
    found = {}
    for m in _PROMPT_PATH_RE.finditer(text):
        p = pathlib.Path(m.group(0))
        v = p.with_name(p.name[:-len(".md")] + VARIANTS_SUFFIX)
        if os.path.lexists(str(v)):
            found[os.path.realpath(str(p))] = (p, v)
    if len(found) > 1:
        raise Doubt("several-prompts")
    return next(iter(found.values())) if found else None


def _load_variants(vpath: pathlib.Path) -> dict:
    """variants.json を読む: {full, delta（中身の bytes）, full_path, rules_sha, iteration}。形が違えば Doubt"""
    try:
        doc = json.loads(vpath.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise Doubt(f"variants-bad: {vpath} が読めない（{e}）") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("rules_sha"), str) or not doc["rules_sha"] \
            or not isinstance(doc.get("full"), str) or not isinstance(doc.get("delta"), str):
        raise Doubt(f"variants-bad: {vpath} の形が違う（full・delta・rules_sha が文字列でない）")
    out = {"rules_sha": doc["rules_sha"],
           "iteration": doc.get("iteration") if isinstance(doc.get("iteration"), int) else None}
    for key in ("full", "delta"):
        path = vpath.parent / doc[key]          # 絶対パスならそのまま
        try:
            if not path.is_file():
                raise OSError("通常のファイルでない")
            data = path.read_bytes()
            data.decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise Doubt(f"variants-bad: {key} の {path} が読めない（{e}）") from None
        out[key] = data
        out[key + "_path"] = path
    return out


def read_reads(cwd, home_dir=None) -> List[dict]:
    """Read のフックの記録（reads.jsonl）を古い順に。無い・読めない行は飛ばす"""
    try:
        text = (reads_dir(cwd, home_dir) / "reads.jsonl").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for ln in text.splitlines():
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _read_whole(reads: Sequence[dict], sid: str, path: str, sha: str) -> bool:
    """会話 sid の本人（subagent でない）が path を sha の中身で部分読みでなく読んだ跡が在るか"""
    real = os.path.realpath(path)
    return any(r.get("session_id") == sid and r.get("agent_id") is None and r.get("partial") is False
               and r.get("file_sha") == sha and isinstance(r.get("path"), str) and os.path.realpath(r["path"]) == real
               for r in reads)


def _transcript_clean(config_dir: pathlib.Path, sid: str) -> Optional[str]:
    """会話 sid の transcript（<設定>/projects/*/<sid>.jsonl）に中身が減った跡が無ければ None、あれば・見えなければ理由"""
    paths = sorted(config_dir.glob(f"projects/*/{sid}.jsonl")) if _ID_RE.match(sid) else []
    if not paths:
        return "transcript-missing"
    for p in paths:
        try:
            data = p.read_bytes()
        except OSError:
            return "transcript-missing"
        if any(m in data for m in COMPACT_MARKS):
            return "compacted"
    return None


def choose(session: Optional[dict], rules_sha: str, rows: Sequence[dict], reads: Sequence[dict],
           config_dir: pathlib.Path) -> Tuple[str, str]:
    """(版, 理由)。差分版は、継ぐ会話の鎖（fork の元を起動の記録で辿る）のどこかが同じ rules_sha の全文版をこの包みから
    受け取って読み切り、鎖のどの会話の transcript にも中身が減った跡が無い時だけ。理由は same-session・new-session・
    no-full-record・rules-changed・full-not-read・compacted・transcript-missing"""
    mode = (session or {}).get("mode")
    src = (session or {}).get("from")
    if mode not in ("sdk-resume", "sdk-fork", "continued") or not isinstance(src, str) or not src:
        return "full", "new-session"
    chain, cur, holder, why = [], src, None, "no-full-record"
    while cur and cur not in chain:
        chain.append(cur)
        mine = [r for r in rows if r.get("mode") == "merged" and isinstance(r.get("session"), dict)
                and r["session"].get("id") == cur]
        for r in reversed(mine):
            got = r.get("prompt")
            if not isinstance(got, dict) or got.get("variant") != "full":
                continue
            if got.get("rules_sha") != rules_sha:
                why = "rules-changed" if why == "no-full-record" else why
                continue
            if _read_whole(reads, cur, str(got.get("file") or ""), str(got.get("full_sha") or "")):
                holder = cur
                break
            why = "full-not-read"
        if holder:
            break
        parents = {r["session"].get("from") for r in mine
                   if r["session"].get("from") and r["session"].get("from") != cur}
        if len(parents) != 1:        # 鎖の根（新しい会話）か、元が 2 つ（疑い）
            break
        cur = parents.pop()
    if holder is None:
        return "full", why
    for sid in chain:
        bad = _transcript_clean(config_dir, sid)
        if bad:
            return "full", bad
    return "delta", "same-session"


def _write_atomic(path: pathlib.Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def prompt_variant(text: str, session: Optional[dict], cwd, home_dir, env=None) -> Optional[dict]:
    """指示文 text が名指す指示書に全文版か差分版を書き、起動の記録の `prompt` の欄を返す。variants.json が無ければ None
    （何もしない）。例外は出さない（決められない時は指示書に触らず、variant: null と理由を返す）"""
    env = os.environ if env is None else env
    try:
        found = _variants(text)
    except Doubt as e:
        return {"file": None, "variant": None, "rules_sha": None, "iteration": None, "full_sha": None, "reason": str(e)}
    if found is None:
        return None
    prompt, vpath = found
    info = {"file": os.path.realpath(str(prompt)), "variant": None, "rules_sha": None, "iteration": None,
            "full_sha": None, "reason": ""}
    try:
        v = _load_variants(vpath)
        info.update(rules_sha=v["rules_sha"], iteration=v["iteration"],
                    full_sha=hashlib.sha256(v["full"]).hexdigest())
        ours_delta = delta_text(v["delta"].decode("utf-8"), v["full_path"]).encode("utf-8")
        try:
            now_bytes = prompt.read_bytes()
        except OSError as e:
            raise Doubt(f"prompt-unreadable: {prompt}（{e}）") from None
        if now_bytes not in (v["full"], ours_delta):
            raise Doubt(f"prompt-unexpected: {prompt} の中身が全文版とも包みの差分版とも違う")
        config = pathlib.Path(env.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"))
        variant, why = choose(session, v["rules_sha"], read_launches(cwd, home_dir), read_reads(cwd, home_dir), config)
        want = v["full"] if variant == "full" else ours_delta
        if now_bytes != want:
            try:
                _write_atomic(prompt, want)
            except OSError as e:
                raise Doubt(f"write-failed: {prompt}（{e}）") from None
        info.update(variant=variant, reason=why)
    except Doubt as e:
        info["reason"] = str(e)
    except Exception as e:  # noqa: BLE001  中継を止めない（決められない時は触らない）
        info["reason"] = f"error: {type(e).__name__}: {e}"
    return info


def relay(src_fd: int, dst_fd: int, on_line: Callable[[bytes], bool]) -> None:
    """src_fd を読み切るまで dst_fd へ写し、終わったら dst_fd を閉じる（バイトは変えない）。on_line(改行を除いた 1 行) が
    偽を返すまで、行ごとに渡してから写す（1 行を写す前に指示書を書ける）。on_line の例外は偽と同じ（見るのをやめて写し続ける）。
    子が先に抜けた（EPIPE）・src が読めない時は写すのをやめる"""
    buf, watching = b"", True
    try:
        while True:
            try:
                chunk = os.read(src_fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            if watching:
                buf += chunk
                while watching and b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        watching = bool(on_line(line))
                    except Exception:  # noqa: BLE001
                        watching = False
                    _write_all(dst_fd, line + b"\n")
                if not watching:
                    _write_all(dst_fd, buf)
                    buf = b""
            else:
                _write_all(dst_fd, chunk)
        if buf:
            _write_all(dst_fd, buf)
    except OSError:
        pass
    finally:
        try:
            os.close(dst_fd)
        except OSError:
            pass


NO_TURN_EXIT = 75   # EX_TEMPFAIL。SDK は 'exited with code 75' と言い、Archon はそれを transient として起こし直す


class OutWatch:
    """relay_out が見た子の stdout（stream-json）。progressed: assistant の行を見た。held: 即時の死と決めて写さなかった
    result の行（無ければ None）"""

    def __init__(self) -> None:
        self.progressed = False
        self.held: Optional[bytes] = None


def watches_out(argv: Sequence[str]) -> bool:
    """16 の見張りを掛ける起動か（`--output-format stream-json` がちょうど 1 つ）。見分けられない形は掛けない"""
    try:
        found = find_opt(argv, "--output-format")
    except Unrecognised:
        return False
    return [v for _, _, v, _ in found] == ["stream-json"]


def exit_row(node: Optional[str], pid: int, rc: int, held: bytes) -> dict:
    """exits の 1 行: 写さなかった result の全文（result）と、その型・種・誤りか・本文の 1 行目（head）"""
    text = held.decode("utf-8", "replace")
    try:
        doc = json.loads(text)
    except ValueError:
        doc = {}
    doc = doc if isinstance(doc, dict) else {}
    head = (str(doc.get("result") or "").strip().splitlines() or [""])[0]
    return {"at": now(), "pid": pid, "node": node, "kind": "no_turn", "exit": rc, "subtype": doc.get("subtype"),
            "is_error": doc.get("is_error"), "num_turns": doc.get("num_turns"), "head": head, "result": text}


def no_turn(progressed: bool, result: dict) -> bool:
    """1 手も進まずに終わった子か: assistant の行が無く、result の num_turns が 0（か無い）。費用では決めない（run 43 は
    tokens 0・numTurns 0 で costUsd 1.15）"""
    turns = result.get("num_turns")
    return not progressed and not (isinstance(turns, int) and turns > 0)


def relay_out(src_fd: int, dst_fd: int, w: OutWatch) -> None:
    """子の stdout（src_fd）を行ごとに dst_fd へそのままのバイトで写し、終わったら両方を閉じる。assistant の行で
    w.progressed を立てる。result の行は届いた時に決める: no_turn なら写さずに w.held に置き、そうでなければすぐ写す
    （子の終わりまで留めると、result の後に stdin の終わりを待つ子と SDK が互いを待つ）。dst が閉じた（EPIPE）後も読み続ける"""
    buf = b""

    def put(data: bytes) -> None:
        try:
            _write_all(dst_fd, data)
        except OSError:
            pass

    try:
        while True:
            try:
                chunk = os.read(src_fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    doc = json.loads(line)
                except ValueError:
                    doc = None
                kind = doc.get("type") if isinstance(doc, dict) else None
                if kind == "assistant":
                    w.progressed = True
                elif kind == "result" and w.held is None and no_turn(w.progressed, doc):
                    w.held = line
                    continue
                put(line + b"\n")
        if buf:
            put(buf)
    finally:
        for fd in (src_fd, dst_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        view = view[n:]


# --- 木ごと止める（試し P15 の直しの形。scratchpad/probes-p14-p15-summary.md） ------------------------------------
# 止め方は tree_run（本流 role_run と同じ数え上げ→送る→数え直し）をそのまま使う。包みが足すのは、走っている間の見回りで
# 仲間（{pid: 開始時刻}）を溜めて stop_group に渡すことだけ（claude が先に抜けて親子の鎖が切れた孫も拾うため）
KILL_GRACE = tree_run.KILL_GRACE      # 2 秒（台帳 R31）
POLL = tree_run.POLL                  # 0.2 秒
LINGER = tree_run.LINGER              # 1 秒（試し P17）
PS_TIMEOUT = tree_run.PS_TIMEOUT      # 1 秒
STOP_SIGNALS = tree_run.STOP_SIGNALS


def watch(p: subprocess.Popen, known: Dict[int, float], born: float) -> None:
    """claude（p）の木の仲間を数えて known に足す（tree_run._tree_members。グループ・セッション・親子の鎖・前に数えた物）"""
    members, _ = tree_run._tree_members(p.pid, known, born if p.poll() is not None else None)
    if members:
        known.update({pid: m.started for pid, m in members.items()})


def _stop(p, known, born, first=signal.SIGTERM) -> None:
    why = tree_run.stop_group(p, first, born, known)
    if why:
        sys.stderr.write(f"works claude-adapter: 木を止め切れない: {why}\n")


def supervise(argv: Sequence[str], env_over: Optional[dict] = None, cwd: Optional[str] = None,
              on_line: Optional[Callable[[bytes], bool]] = None, out: Optional[OutWatch] = None) -> int:
    """argv（本物の claude と引数）を新しいセッションで起こして待ち、終了コードを返す（信号で死んだら 128+信号）。
    待つ間は POLL ごとに仲間を数えて溜める。止める信号を受けたか直下の親が替わったら、溜めた仲間ごと木を止め
    （tree_run.stop_group）、LINGER 待って 128+信号（親の替わりは SIGHUP）を返す。claude が自分で終わった後も
    残った仲間を止める。上限の勘定は tree_run と同じ（信号に気づくまで POLL、SIGKILL まで KILL_GRACE + PS_TIMEOUT、
    抜けるまで LINGER）。ただし見回りの ps の最中に届いた信号は、その ps が返るまで気づかない（ps が固まれば +PS_TIMEOUT）。
    on_line を渡すと stdin を継がせずに中継する（relay。印のある起動の 9）。渡さなければ stdin は子がそのまま継ぐ。
    out を渡すと stdout も継がせずに relay_out で写し、子が 1 手も進まずに result を出した（out.held）ら木を止めて
    NO_TURN_EXIT を返す（adapter.py の頭の 16）"""
    got: List[int] = []
    old = {s: signal.signal(s, lambda signum, _f: got.append(signum)) for s in STOP_SIGNALS}
    ppid = os.getppid()
    known: Dict[int, float] = {}
    born = time.time()
    env = dict(os.environ, **env_over) if env_over else None
    p = subprocess.Popen(list(argv), start_new_session=True, env=env, cwd=cwd,   # cwd は旗 isolated の起動だけ
                         stdin=subprocess.PIPE if on_line is not None else None,
                         stdout=subprocess.PIPE if out is not None else None)
    if on_line is not None:
        # 書く口は fd で渡して Python の stdin・p.stdin の物に触らない（終わりの時に daemon の糸が錠を持ったまま残らないように）
        dst = os.dup(p.stdin.fileno())
        p.stdin.close()
        threading.Thread(target=relay, args=(0, dst, on_line), daemon=True).start()
    out_thread = None
    if out is not None:
        src = os.dup(p.stdout.fileno())
        p.stdout.close()
        out_thread = threading.Thread(target=relay_out, args=(src, os.dup(1), out), daemon=True)
        out_thread.start()

    def drained() -> None:
        if out_thread is not None:
            out_thread.join(KILL_GRACE + PS_TIMEOUT + LINGER)

    stopped = False
    try:
        while True:
            if got or os.getppid() != ppid:
                signum = got[0] if got else signal.SIGHUP
                _stop(p, known, born, signum)
                stopped = True
                drained()
                time.sleep(LINGER)
                return 128 + signum
            if out is not None and out.held is not None:
                break
            try:
                rc = p.wait(POLL)
                break
            except subprocess.TimeoutExpired:
                watch(p, known, born)
        _stop(p, known, born)      # claude が残した孫（Bash の道具の別のグループ・別のセッション）。即時の死なら claude ごと
        stopped = True
        drained()
        if got:
            time.sleep(LINGER)
            return 128 + got[0]
        if out is not None and out.held is not None:
            return NO_TURN_EXIT
        return rc if rc >= 0 else 128 - rc
    finally:
        if not stopped:
            _stop(p, known, born)
        for s, h in old.items():
            signal.signal(s, h)
