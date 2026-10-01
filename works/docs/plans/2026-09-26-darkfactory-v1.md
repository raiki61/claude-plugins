# darkfactory 1 本目 Implementation Plan

> **注（実装の後に足した）:** 実装は台帳の Ruling R1–R21 で変わった（`.superpowers/sdd/2026-09-26-darkfactory-v1/progress.md` は作業用で git の外）。下の本文は書き換えていない。今の形は設計書と YAML が正本。主な変更:
> - R1: 筋書きの依頼 `request_ok.json` を種（`dev/target-seed/`）に置く。
> - R2: ブロックの `base_rev` は `default: ""`（空はその場の HEAD）。ラインはいつも `$base.output.rev` を渡す。
> - R3: 差分の審査の受け付けの「作業ツリーが変わった」は、cut が盤面に置く写し（porcelain と差分の digest）と比べる（判定の側は R14）。
> - R4: bash・script の節は全部 `timeout: 1728000000`、AI の節は全部 `idle_timeout: 1728000000`。
> - R7: ブロックのスクリプトは `import accept` の前に `.shared/core` を `sys.path` の頭に入れる。
> - R8: ブロックのテストはブロックごとのファイル（`test_blk_judge.py`・`test_blk_fix.py`・`test_blk_tests_delta.py`）。
> - R10: `dev/check.sh` は works 自身の工程だけを 1 本ずつ validate する。
> - R11: 出し直しの上限の筋書きは、模擬実行が `until_bash` を回さないので、失敗の節を collect で見る。
> - R12: AI の節の sandbox は `{enabled: true, allowUnsandboxedCommands: false}`。
> - Review Focus 3 の「`mutates_checkout: false` は include で落とされるため唯一の守り」は古い。落ちるのは工程の段の鍵で、節の段の鍵は別物（設計書 7 節の「読むだけの役」）。
> - R14: 判定の受け付けは、intake が盤面に置く作業ツリーの写し（`judge-snapshot.json`）と比べる。
> - R15: テストで出来るバイトコード（`__pycache__/`・`.pyc`）は触ったファイルに数えない。blk-tests は `PYTHONDONTWRITEBYTECODE=1` で回す。
> - R16（R13 を置き換え）: 指示書は `$LOOP_PREV.<役>-accept.output.reason` と `$cut.output.*` を本文で直に読む（節の `with:` で渡さない）。
> - R17: ラインの include の id は `judging`・`fixing`・`testing`・`reviewing`（ブロックの中の節の id と重ねない）。
> - R18: 実走の模型は隔離した開発用の Archon の設定の既定（opus）。ブロックの YAML に `model:` を書かない。
> - R19: 受け付けの節の名前は `judge-accept`・`fix-accept`・`review-accept`。
> - R20: 開発の殻の認証に既定の口座は無い（`CLAUDE_CODE_OAUTH_TOKEN` か `WORKS_KEYCHAIN_ITEM`）。
> - R21: 直す物が無い判定なら、ラインは修正から後を飛ばし、いつも走る節 `finish`（`returns`）で `no_fix_needed` を返す。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `works/` を Archon の pack として作り、人の修正依頼を「判定 → 修正 → テスト → 人の承認 → 修正差分の審査」の順に流すライン `darkfactory` を、graphloops から写した本物の受け付けの規則と記録の検証器で回す。

**Architecture:** 受け付けの規則・検証器は `works/.shared/core/` に graphloops の配置のまま写し、`core/accept.py` が Archon を知らない関数の口（`check_*`）を出す。ブロック（`blk-*`）は Archon の support workflow で、役の AI の節と、その返答を `core/accept.py` に通す script の節を `loop_group` で輪にする。ライン `darkfactory` はブロックを `include:` で並べ、人の関所を 1 つ持つ。

**Tech Stack:** Archon v0.11.1（公式の実行ファイル）・YAML・Python 3（pack の中は標準ライブラリだけ。テストだけ PyYAML を `uv run --with` で使う）・uv・git。

**Spec:** `works/docs/specs/2026-09-26-darkfactory-design.md`

## Global Constraints

- 触ってよいのは `works/` の下だけ。graphloops・convergence-loops・リポジトリ直下の共有ファイル（`.github/`・`.claude-plugin/marketplace.json`・`tests/`）は触らない。
- 写す元の commit は `fbd40e3`（graphloops 0.20.3）。
- Archon は v0.11.1。実行ファイル `archon-darwin-arm64` の sha256 は `b9338474fd3151d5d5402d76ae278105e65835f2e3506a93f0e5e4a378d10ede`。manifest の `compatibility.archon` は `>=0.11.1 <0.12.0`。
- 期限: AI の節の `idle_timeout` と bash・script の節の `timeout` は全部 `1728000000`（20 日）。これより長い値・これ以外の新しい期限を書かない。
- pack の中（`works/.shared/`・`works/blk-*/scripts/`）の Python は標準ライブラリだけ。PyYAML はテスト（`works/tests/`）だけ。
- pack の中に `__pycache__` を作らない（テストは `PYTHONDONTWRITEBYTECODE=1` で回す）。pack の中に 64MB を超える物を置かない（Archon の実行ファイルは pack の外にしまう）。
- テストは `nice -n 19` で前景で回す。プロセスを止めるときは pid と cwd を確かめる。`pkill -f` を使わない。
- 受け付けのスクリプトは、拒否も終了コード 0 で `{"ok": false, "reason": "..."}` を 1 行出す。入力が読めないときだけ終了コード 2。出力の JSON は `ensure_ascii=False`。
- 読むだけの役の `allowed_tools` は `[Read, Grep, Glob]` の部分集合。AI の節は全部 `output_format` と `sandbox: {enabled: true}` を持つ。
- commit の末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push・tag はしない。

## Review Focus

1. 依頼のファイルが無い・JSON でない・欄が型の外 → AI を 1 回も起こす前に、どこが悪いかを言って止まる（Task 3 の `test_intake_*` と Task 5 の筋書き `bad-request`）。
2. 返答が型の欄を欠く（例: `units` が無い）→ 規則が例外で落ちるのでなく `ok: false` で欄の名前を言う（Task 3 の `test_judge_missing_units`）。
3. 読むだけの役が作業ツリーを変えた → 受け付けが `ok: false` で拒む（Task 3 の `test_judge_rejects_dirty_tree`）。Archon の `mutates_checkout: false` は include で落とされるため、ここが唯一の守り。
4. 拒んだ理由に日本語・引用符・改行が入る → 次の周のプロンプトと `until_bash` の比べが壊れない（Task 4 の `test_accept_script_reason_roundtrip`）。
5. 修正役が何も変えずに「済んだ」と言う → 決まった検査の節で run が落ちる（Task 6 の筋書き `no-change`）。

---

### Task 1: pack の骨組みと中身の写し

**Files:**
- Create: `works/archon-plugin.json`
- Create: `works/README.md`
- Create: `works/.shared/core/COPIED_FROM`
- Create（写し）: `works/.shared/core/graphloops/engine/*.py`（`graphloops/engine/` の `.py` 全部）・`works/.shared/core/graphloops/rules/review-loop.py`・`works/.shared/core/graphloops/graphs/review-loop.json`・`works/.shared/core/scripts/review-record.py`・`works/.shared/core/scripts/record_common.py`
- Create: `works/tests/run.sh`
- Test: `works/tests/test_core_copy.py`

**Interfaces:**
- Produces: `works/.shared/core/graphloops` を `sys.path` に足すと `from engine.rules import load_rules` が通る。検証器は `works/.shared/core/scripts/review-record.py`。`works/tests/run.sh` が `works/tests/test_*.py` を全部回す。

- [ ] **Step 1: 失敗するテストを書く** — `works/tests/test_core_copy.py`

```python
CORE = pathlib.Path(__file__).resolve().parents[1] / ".shared" / "core"

def test_rules_load_from_copy(self):
    sys.path.insert(0, str(CORE / "graphloops"))
    from engine.rules import load_rules
    gp = CORE / "graphloops" / "graphs" / "review-loop.json"
    rules = load_rules(gp, json.loads(gp.read_text()))
    for name in ("judge_output", "fix_plan_covers_units", "delta_review_output"):
        self.assertIn(name, rules.POST_CHECKS)
    self.assertTrue(hasattr(rules, "add"))

def test_copied_from_names_commit(self):
    self.assertIn("fbd40e3", (CORE / "COPIED_FROM").read_text())

def test_manifest(self):
    m = json.loads((ROOT / "archon-plugin.json").read_text())
    self.assertEqual(m["name"], "works")
    self.assertEqual(m["kind"], "workflow-pack")
    self.assertEqual(m["entrypoints"], {"darkfactory": "darkfactory/darkfactory.yaml"})
    self.assertEqual(m["compatibility"], {"archon": ">=0.11.1 <0.12.0"})
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: 3 件とも FAIL（ファイルが無い）

- [ ] **Step 3: 写しと骨組みを作る**
  - 写しは `git show fbd40e3:<path>` で取る（作業ツリーの今の姿でなく commit から）。`graphloops/` の下の配置を `works/.shared/core/graphloops/` に、リポジトリ直下の `scripts/` の 2 本を `works/.shared/core/scripts/` に、元の相対の位置のまま置く（engine の `PLUGIN_ROOT` と rules の相対の読み込みがそのまま効くように）。
  - `COPIED_FROM`: 1 行目に `fbd40e3`、続けて写した元のパスを 1 行ずつ。
  - `archon-plugin.json`: `{"schemaVersion": 1, "kind": "workflow-pack", "name": "works", "description": "持ち主の作業の生産ライン", "compatibility": {"archon": ">=0.11.1 <0.12.0"}, "entrypoints": {"darkfactory": "darkfactory/darkfactory.yaml"}}`
  - `README.md`: 何か（1 段落）・入れ方（`archon plugin install raiki61/claude-plugins/works@<tag>`）・開発の回し方（`dev/` を指す）・仕様書へのリンク。
  - `tests/run.sh`: `cd "$(dirname "$0")/.." && PYTHONDONTWRITEBYTECODE=1 exec uv run --no-project --with pyyaml python3 -m unittest discover -s tests -p 'test_*.py' "$@"`

- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh` / Expected: `OK`

- [ ] **Step 5: Commit** — `git add works && git commit -m "feat(works): pack の骨組みと graphloops の受け付けの中身の写し"`

---

### Task 2: 開発の殻（固定した版の Archon と使い捨ての対象リポジトリ）

**Files:**
- Create: `works/dev/archon.sh`
- Create: `works/dev/mktarget.sh`
- Create: `works/dev/check.sh`
- Create: `works/dev/target-seed/stats.py`・`works/dev/target-seed/test_stats.py`
- Test: `works/tests/test_dev.py`

**Interfaces:**
- Produces:
  - `works/dev/archon.sh <archon の引数…>`: 環境変数 `WORKS_DEV_HOME`（既定 `${TMPDIR:-/tmp}/works-dev`）の下に v0.11.1 の実行ファイルを落として sha256 を確かめ（違えば終了コード 1 で止まる）、`HOME`・`ARCHON_HOME`・`CLAUDE_CONFIG_DIR`・`XDG_*` をその下へ向け、`ARCHON_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1`、`CLAUDE_CODE_OAUTH_TOKEN` が空なら keychain の `claude-code-oauth-p1` から読んで（`WORKS_DEV_NO_AUTH=1` なら読まない）、実行ファイルを exec する。
  - `works/dev/mktarget.sh <dir>`: `<dir>` に git のリポジトリを作り、`target-seed/` を写し、`works/` を `.archon/workflows/works/` に写して（`tests/`・`dev/`・`docs/` は除く）commit し、パスを 1 行出す。
  - `works/dev/check.sh`: 使い捨ての対象を作り、`archon.sh validate workflows` と `archon.sh workflow test works`（その対象の中で）を回す。どちらかが赤なら終了コード 1。
- `target-seed/`: 試作と同じ仕込み（`stats.py` の `mean` の分母が `len(xs) - 1`、`clamp` が上限超えで `lo` を返す。`test_stats.py` 3 件のうち 2 件が赤）。

- [ ] **Step 1: 失敗するテストを書く** — `works/tests/test_dev.py`

```python
def test_mktarget_places_pack_without_dev_files(self):
    out = subprocess.run(["sh", str(DEV / "mktarget.sh"), str(tmp)], capture_output=True, text=True, check=True)
    pack = tmp / ".archon" / "workflows" / "works"
    self.assertTrue((pack / "archon-plugin.json").exists())
    self.assertTrue((pack / ".shared" / "core" / "COPIED_FROM").exists())
    for d in ("tests", "dev", "docs"):
        self.assertFalse((pack / d).exists())
    self.assertEqual(git(tmp, "status", "--porcelain"), "")   # 全部 commit 済み
    self.assertEqual(run_tests(tmp).returncode, 1)           # 仕込んだバグで赤

def test_archon_sh_refuses_wrong_checksum(self):
    # WORKS_DEV_HOME に中身の違う実行ファイルを置く → 終了コード 1、stderr に "sha256"
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k dev` / Expected: FAIL（スクリプトが無い）

- [ ] **Step 3: 殻を書く** — 落とすのは `gh release download v0.11.1 -R coleam00/Archon -p archon-darwin-arm64`。版と sha256 は `archon.sh` の先頭の 2 変数（`ARCHON_VERSION`・`ARCHON_SHA256`）に置く。keychain は `security find-generic-password -s claude-code-oauth-p1 -w`。token をファイルに書かない。

- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k dev` / Expected: `OK`。続けて `WORKS_DEV_NO_AUTH=1 sh works/dev/archon.sh version` / Expected: `Archon CLI v0.11.1`

- [ ] **Step 5: Commit** — `git commit -m "feat(works): 固定した版の Archon を隔離して回す開発の殻"`

---

### Task 3: 受け付けの口 `core/accept.py`

**Files:**
- Create: `works/.shared/core/accept.py`
- Create: `works/tests/replies/`（返答の見本。下の名前）
- Test: `works/tests/test_accept.py`

**Interfaces:**
- Consumes: Task 1 の写し。
- Produces（全部 `dict` を返し、例外で拒まない。拒否は `{"ok": False, "reason": str}`）:
  - `check_request(items: list, board: Path, reason: str) -> dict` — 写した rules の `add` を通し、通れば `board/request.json` に積んだバッチを書く。`{"ok", "reason"}`。
  - `check_judge(reply: dict, board: Path, base_rev: str, repo: Path) -> dict` — 作業ツリーが `base_rev` から変わっていれば拒む → 型（写した graph の `p2.diagnose` の schema）→ rules の `judge_output`（記録の `process.request_findings` に `board/request.json` を入れて渡す）。通れば `board/judgment.json` を書く。`{"ok", "reason", "open_units": [str], "judgment_file": str}`。
  - `check_fix(reply: dict, board: Path, base_rev: str, repo: Path) -> dict` — `reply["changes"][].unit_key` を plan に読み替えて rules の `fix_plan_covers_units`。`{"ok", "reason"}`。
  - `check_delta(reply: dict, board: Path, base_rev: str, repo: Path) -> dict` — 触ったファイルは `git diff --name-only <base_rev>`（未追跡も含む）から取り、rules の `delta_review_output`。作業ツリーが修正の後の姿から変わっていれば拒む。`{"ok", "reason"}`。
  - `role_schema(node: str) -> dict` — 写した graph の節の `schema` を `$ref` を開いて `note` を落とした JSON Schema（試作の `mkschema.py` と同じ）。`node` は `"p2.diagnose"` か `"p3.delta_review"`。
- 盤面の入れ物（内部）: 試作の `FakeBoard` の口（`dir`・`round=1`・`state={"validator": <写した review-record.py>, "inputs": {"review_rev": base_rev}}`・`record`・`loop_state`・`graph`・`output_of_round`）。git は `repo` を cwd にして呼ぶ。`HEAD` をその場で読まない。

- [ ] **Step 1: 失敗するテストを書く** — `works/tests/test_accept.py`。各テストは `dev/target-seed/` を一時ディレクトリの git に写した物を `repo` にする。

```python
def test_intake_accepts_request(self):          # replies/request_ok.json（where・text だけ）
    self.assertTrue(check_request(load("request_ok"), board, "持ち主")["ok"])
def test_intake_rejects_unknown_key(self):      # replies/request_extra_key.json（severity を足す）
    r = check_request(load("request_extra_key"), board, "持ち主")
    self.assertFalse(r["ok"]); self.assertIn("severity", r["reason"])
def test_judge_accepts_good_reply(self):        # replies/judge_ok.json（stats.py の 2 つのバグ。block に class_query、precedents の行）
    r = check_judge(load("judge_ok"), board, base, repo)
    self.assertTrue(r["ok"], r["reason"]); self.assertTrue((board / "judgment.json").exists())
    self.assertEqual(sorted(r["open_units"]), sorted(u["key"] for u in load("judge_ok")["units"] if u["label"] == "block"))
def test_judge_missing_units(self):             # judge_ok から units を消す
    r = check_judge(no_units, board, base, repo); self.assertFalse(r["ok"]); self.assertIn("units", r["reason"])
def test_judge_rejects_precedent_without_searched(self):   # replies/judge_notfound_no_searched.json
    self.assertIn("searched", check_judge(load("judge_notfound_no_searched"), board, base, repo)["reason"])
def test_judge_rejects_dirty_tree(self):        # repo に 1 ファイル足してから
    self.assertFalse(check_judge(load("judge_ok"), board, base, repo)["ok"])
def test_fix_accepts_covering_reply(self):      # judge_ok を通した後、replies/fix_ok.json
def test_fix_rejects_uncovered_unit(self):      # replies/fix_missing_unit.json（block の 1 つを欠く）→ ok False、欠けた key が reason に在る
def test_delta_accepts_good_reply(self):        # stats.py を直してから replies/delta_ok.json（faces 空・faces_none 20 字以上）
def test_delta_rejects_uncited_face(self):      # replies/delta_bad_cite.json（cite がファイルに無い字列）→ ok False
def test_role_schema_resolves_refs(self):
    self.assertNotIn("$ref", json.dumps(role_schema("p2.diagnose")))
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k accept` / Expected: FAIL（`accept` が無い）

- [ ] **Step 3: `accept.py` を書く** — 試作の `S/archon-spike/shim/gl_accept.py`（S = 本体のセッションの scratchpad `/private/tmp/claude-1341252503/-Users-p03623-src-claude-plugins/799d1c5c-a888-4cdb-bf0a-ac1aea9c5577/scratchpad`）を元にし、Interfaces の形に直す。型の検査は写した `engine/schema.py` の `validate_schema`。rules の `Reject` を `ok: False` に写す。見本の返答は、拒む検査を 1 つずつ満たすように手で書き、通らない見本は通らない理由が 1 つだけになるように作る。

- [ ] **Step 4: 緑を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k accept` / Expected: `OK`

- [ ] **Step 5: Commit** — `git commit -m "feat(works): 受け付けの口（依頼・判定・修正・差分）を写した規則で"`

---

### Task 4: YAML の決まりの検査と受け付けのスクリプトの形

**Files:**
- Create: `works/tests/test_yaml_rules.py`
- Create: `works/tests/yaml_bad/`（違反の見本 YAML。1 本 1 違反）
- Create: `works/.shared/core/script_io.py`
- Test: `works/tests/test_script_io.py`

**Interfaces:**
- Produces:
  - `script_io.main(fn: Callable[[dict, Path, str, Path], dict], reply_env: str = "INPUTS_REPLY") -> int` — 環境変数 `INPUTS_REPLY`（`with: {reply: {from: "$節.output"}}` で届く JSON の文字列）・`INPUTS_BASE_REV`・`ARTIFACTS_DIR` を読み、`fn(reply, ARTIFACTS_DIR/"board", base_rev, Path.cwd())` を呼び、結果を 1 行の JSON で出す。`INPUTS_REPLY` が JSON でなければ `{"ok": false, "reason": "返答が JSON として読めない: …"}` で 0。環境変数が欠ければ stderr に名前を出して 2。各ブロックの `scripts/*.py` は `.shared/core` を `sys.path` に足して（`Path(__file__).resolve().parents[2] / ".shared" / "core"`）これを呼ぶだけの数行にする。
  - `test_yaml_rules.check_file(path: Path) -> list[str]`（違反の文の一覧）: 全部の節の `timeout`・`idle_timeout` が `1728000000`／AI の節（`prompt:` か `command:` を持つ節）は `output_format` と `sandbox.enabled: true` と `idle_timeout` を持つ／`allowed_tools` が `[Read, Grep, Glob]` の部分集合でない AI の節は `blk-fix` の `fix` だけ／`loop_group` は `max_iterations: 3` と `until_bash`。`loop_group` の中の節も辿る。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_each_bad_yaml_is_red(self):
    for p in sorted((TESTS / "yaml_bad").glob("*.yaml")):
        self.assertTrue(check_file(p), p.name)       # timeout_25days / ai_no_output_format / ai_no_sandbox / readonly_with_edit / loop_no_max
def test_pack_yaml_is_green(self):
    files = sorted(ROOT.glob("*/*.yaml"))
    for p in files: self.assertEqual(check_file(p), [], p.name)
def test_accept_script_reason_roundtrip(self):
    # script_io.main に「reason に日本語・" ・' ・改行を含む ok False を返す fn」を渡し、標準出力を json.loads して元と一致
def test_script_io_non_json_reply(self):         # INPUTS_REPLY="not json" → 終了コード 0、ok False
def test_script_io_missing_env(self):            # INPUTS_BASE_REV 無し → 終了コード 2
```

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k "yaml or script_io"` / Expected: FAIL

- [ ] **Step 3: `script_io.py` と検査を書く**

- [ ] **Step 4: 緑を確かめる** — 同じコマンド / Expected: `OK`（この時点で pack の YAML は 0 本なので `test_pack_yaml_is_green` は空で通る）

- [ ] **Step 5: Commit** — `git commit -m "feat(works): YAML の決まりの検査と受け付けのスクリプトの入口"`

---

### Task 5: ブロック `blk-judge`

**Files:**
- Create: `works/blk-judge/blk-judge.yaml`
- Create: `works/blk-judge/commands/diagnose.md`
- Create: `works/blk-judge/scripts/intake.py`・`works/blk-judge/scripts/accept.py`・`works/blk-judge/scripts/collect.py`
- Create: `works/blk-judge/fixtures/pass.stubs.yaml`・`works/blk-judge/fixtures/bad-reply.stubs.yaml`・`works/blk-judge/fixtures/bad-request.stubs.yaml`
- Test: `works/tests/test_blocks.py`

**Interfaces:**
- Consumes: `accept.check_request`・`check_judge`・`role_schema("p2.diagnose")`・`script_io.main`。
- Produces（ブロックの口）:
  - `inputs:` `request`（対象リポジトリの中の依頼の JSON のパス）・`base_rev`
  - `returns: collect`、`outcome_field: ok`。`collect` の `output_format`: `{ok: boolean, open_units: array<string>, judgment_file: string, one_shot: string}`（全部 required）
- 節: `intake`（script。`with: {request: $INPUTS.request}`。依頼を読んで `check_request`。拒めば終了コード 1 で run を止める）→ `judge-loop`（`loop_group`、`fresh_context: false`、`max_iterations: 3`、`until_bash: test $accept.output.ok = true`）の中に `judge`（`command: diagnose`、`allowed_tools: [Read, Grep, Glob]`、`sandbox: {enabled: true}`、`idle_timeout: 1728000000`、`output_format:` は `role_schema("p2.diagnose")` を 1 度出して貼った物）と `accept`（script。`with: {reply: {from: "$judge.output"}, base_rev: $INPUTS.base_rev}`、`output_format: {ok, reason, open_units}`）→ `collect`（script。`board/judgment.json` から出口を組む）。
- `diagnose.md` に残す物（graphloops `prompts/review-loop/p2.diagnose.md` から）: 反証の木・出自・上方展開・一撃と `one_shot_closes`・ラベル・`class_query`（欄で書く、版を書かない、直す site を全部数える）・零処方から世界の解へ・`precedents`（not_found なら `searched`）・安定キー・questions。削る物: P1 の素材・前の周の記録・台帳・隔離フレームの観察の穴。差し込み: 依頼 `$INPUTS.request` のパス（Read させる）・`$LOOP_PREV.accept.output.reason`。

- [ ] **Step 1: 失敗するテストを書く** — `works/tests/test_blocks.py`

```python
def test_judge_output_format_matches_role_schema(self):
    y = yaml.safe_load((ROOT / "blk-judge" / "blk-judge.yaml").read_text())
    judge = find_node(y, "judge")
    self.assertEqual(judge["output_format"], role_schema("p2.diagnose"))
def test_judge_ok_sample_passes_yaml_output_format(self):
    self.assertEqual(validate_schema(load("judge_ok"), find_node(y, "judge")["output_format"]), [])
```
筋書き（`fixtures/`、全部 `exec-code: true`）:
  - `pass`: `judge` に `judge_ok` の中身、`fixture: {expect: completed, inputs: {request: request_ok.json, base_rev: <種の commit>}}` — 依頼のファイルは `mktarget.sh` が種に置く（Task 2 の種に `request_ok.json` を足す）
  - `bad-reply`: `judge` に `judge_notfound_no_searched`、`fixture: {expect: failed, fail-node: judge-loop}`
  - `bad-request`: `fixture: {expect: failed, fail-node: intake, inputs: {request: missing.json, …}}`

- [ ] **Step 2: 赤を確かめる** — Run: `nice -n 19 sh works/tests/run.sh -k blocks` と `sh works/dev/check.sh` / Expected: FAIL

- [ ] **Step 3: YAML・指示書・3 本のスクリプトを書く** — `base_rev` の値は筋書きの `inputs` で渡す（種の commit は `mktarget.sh` が出す。`check.sh` が筋書きの `base_rev` を差し替えずに済むよう、種の commit を決まった日時と作者で作って hash を固定する）。

- [ ] **Step 4: 緑を確かめる** — `nice -n 19 sh works/tests/run.sh` と `sh works/dev/check.sh` / Expected: 両方緑（`workflow test` が 3 本とも期待どおり）

- [ ] **Step 5: Commit** — `git commit -m "feat(works): 判定のブロック（依頼の受け付け・判定の輪）"`

---

### Task 6: ブロック `blk-fix`

**Files:**
- Create: `works/blk-fix/blk-fix.yaml`・`works/blk-fix/commands/fix.md`・`works/blk-fix/scripts/accept.py`・`works/blk-fix/scripts/assert_changed.py`・`works/blk-fix/scripts/collect.py`
- Create: `works/blk-fix/fixtures/pass.stubs.yaml`・`works/blk-fix/fixtures/no-change.stubs.yaml`
- Modify: `works/tests/test_blocks.py`

**Interfaces:**
- Consumes: `accept.check_fix`・`script_io.main`・blk-judge の出口（`judgment_file`・`open_units`）。
- Produces: `inputs:` `judgment_file`・`open_units`・`base_rev`。`returns: collect`、`outcome_field: ok`。出口 `{ok: boolean, files: array<string>, changes_file: string}`。
- 節: `fix-loop`（`loop_group`、同じ決まり）の中に `fix`（`command: fix`、`allowed_tools: [Read, Grep, Glob, Edit, Write, Bash]`、`sandbox: {enabled: true}`、`output_format` は `{changes: [{unit_key, files, what}]}`・`additionalProperties: false`）と `accept`（`check_fix`）→ `assert-changed`（script。`git diff --name-only <base_rev>` と未追跡が空なら終了コード 1）→ `collect`。
- `fix.md` に残す物（`prompts/review-loop/p3.fix.md` から）: 単位ごとに根本から直す・テストを消さない緩めない・git commit しない・直した単位ごとに changes の 1 行。差し込み: `$INPUTS.judgment_file`（Read させる）・`$INPUTS.open_units`・`$LOOP_PREV.accept.output.reason`。

- [ ] **Step 1: 失敗するテストを書く** — `test_fix_ok_sample_passes_yaml_output_format`。筋書き: `pass`（`fix` に `fix_ok`。exec-code の作業ツリーは HEAD のままなので `assert-changed` を stub して完走を見る）・`no-change`（`fix` に `fix_ok`、`assert-changed` は実行させる → `expect: failed, fail-node: assert-changed`）
- [ ] **Step 2: 赤を確かめる** — `nice -n 19 sh works/tests/run.sh -k blocks`・`sh works/dev/check.sh` / Expected: FAIL
- [ ] **Step 3: 書く**
- [ ] **Step 4: 緑を確かめる** — 同じ / Expected: 緑
- [ ] **Step 5: Commit** — `git commit -m "feat(works): 修正のブロック（受け付けと、何も変えずに済んだと言うのを止める検査）"`

---

### Task 7: ブロック `blk-tests` と `blk-delta`

**Files:**
- Create: `works/blk-tests/blk-tests.yaml`・`works/blk-tests/fixtures/green.stubs.yaml`
- Create: `works/blk-delta/blk-delta.yaml`・`works/blk-delta/commands/delta-review.md`・`works/blk-delta/scripts/cut.py`・`works/blk-delta/scripts/accept.py`・`works/blk-delta/scripts/collect.py`・`works/blk-delta/fixtures/pass.stubs.yaml`・`works/blk-delta/fixtures/bad-cite.stubs.yaml`
- Modify: `works/tests/test_blocks.py`

**Interfaces:**
- `blk-tests`: `inputs:` `cmd`。節 `run`（bash。`$INPUTS.cmd` を走らせ、ログを `$ARTIFACTS_DIR/board/tests.log` に置き、`{"ok": true, "green": <終了コード 0 か>, "log": <パス>}` を出す。赤でも `ok: true`——赤を人の関所に見せるのがこの段の仕事）。`returns: run`、`outcome_field: ok`。
- `blk-delta`: `inputs:` `base_rev`。節 `cut`（script。`git diff <base_rev>` を `board/fix.diff` に書き、`{ok, files: [...], diff_file}`）→ `delta-loop`（`loop_group`）の中に `review`（`command: delta-review`、`allowed_tools: [Read, Grep, Glob]`、`sandbox: {enabled: true}`、`output_format` は `role_schema("p3.delta_review")`）と `accept`（`check_delta`）→ `collect`（`{ok, faces: integer}`）。`returns: collect`、`outcome_field: ok`。
- `delta-review.md` に残す物（`prompts/review-loop/p3.delta_review.md` から）: 修正が新しく作った写し・塞がない入口・宣言と実装のずれを探す／where は触ったファイル、cite は今の姿に在る字列／無ければ faces 空と faces_none（20 字以上）。差し込み: `$cut.output.diff_file`・`$cut.output.files`・`$LOOP_PREV.accept.output.reason`。

- [ ] **Step 1: 失敗するテストを書く** — `test_delta_ok_sample_passes_yaml_output_format`・`test_delta_output_format_matches_role_schema`。筋書き: blk-tests `green`（exec-code で `cmd: "true"`）、blk-delta `pass`（`review` に `delta_ok`、`cut` を stub）・`bad-cite`（`review` に `delta_bad_cite` → `fail-node: delta-loop`）
- [ ] **Step 2: 赤を確かめる** — `nice -n 19 sh works/tests/run.sh -k blocks`・`sh works/dev/check.sh` / Expected: FAIL
- [ ] **Step 3: 書く**
- [ ] **Step 4: 緑を確かめる** — 同じ / Expected: 緑
- [ ] **Step 5: Commit** — `git commit -m "feat(works): テストと修正差分の審査のブロック"`

---

### Task 8: ライン `darkfactory`

**Files:**
- Create: `works/darkfactory/darkfactory.yaml`・`works/darkfactory/fixtures/wiring.stubs.yaml`・`works/darkfactory/fixtures/tests-red.stubs.yaml`
- Modify: `works/tests/test_blocks.py`

**Interfaces:**
- Consumes: 4 つのブロックの口（Task 5〜7）。
- Produces: 入口 `darkfactory`。`interactive: true`。`inputs:` `request`・`test_cmd`。節: `base`（bash。`git rev-parse HEAD` を `{ok, rev}` で）→ `judge`（include blk-judge、`with: {request: $INPUTS.request, base_rev: $base.output.rev}`）→ `fix`（include blk-fix、`with: {judgment_file: $judge.output.judgment_file, open_units: $judge.output.open_units, base_rev: $base.output.rev}`）→ `tests`（include blk-tests、`with: {cmd: $INPUTS.test_cmd}`）→ `gate`（`approval`、メッセージにテストの緑赤とログのパス、`capture_response: true`）→ `delta`（include blk-delta、`with: {base_rev: $base.output.rev}`）。`returns: delta`、`outcome_field: ok`。

- [ ] **Step 1: 失敗するテストを書く** — `test_line_includes_all_blocks`（`include` の値の集合 = `{blk-judge, blk-fix, blk-tests, blk-delta}`）。筋書き（include で入った script の節は Archon の模擬実行では必ず stub が要るので、配線だけを見る）: `wiring`（全部 stub、`expect: completed`、`reached: [gate, delta__collect]`）・`tests-red`（`tests__run` に `green: false`、`--pause-at-gates` 無しで関所は自動で通り完走すること）
- [ ] **Step 2: 赤を確かめる** — `sh works/dev/check.sh` / Expected: FAIL
- [ ] **Step 3: 書く**（stub の鍵の綴りは `archon.sh workflow run darkfactory --dry-run --stubs-init <path>` が出す物を正本にする）
- [ ] **Step 4: 緑を確かめる** — `nice -n 19 sh works/tests/run.sh`・`sh works/dev/check.sh` / Expected: 両方緑。`validate` に `darkfactory` の WARNING が無いこと
- [ ] **Step 5: Commit** — `git commit -m "feat(works): ライン darkfactory（判定→修正→テスト→人の承認→差分の審査）"`

---

### Task 9: works のスキル

**Files:**
- Create: `works/skills/works/SKILL.md`
- Create: `works/.claude-plugin/plugin.json`
- Modify: `works/tests/test_core_copy.py`（名前はそのまま、テストを 1 本足す）

**Interfaces:**
- `SKILL.md` の frontmatter: `name: works`、`description:` に起動の言葉（「darkfactory に回して」「works で直して」）と、回さない物（誤字・コメント・文言の直し）。本文: 依頼の JSON の書き方（欄は `where`・`text` 必須、`mechanism`・`measured`・`false_positive_if` 任意、ほかは拒まれる）・起動の 1 行（`archon workflow run raiki61/works:darkfactory --input request=<パス> --input test_cmd="<コマンド>"`）・人の関所で見る物（テストの緑赤とログ、判定の `one_shot`）と答え方（`archon workflow approve|reject <run-id>`）・止め方（前景を Ctrl-C → `archon workflow resume <run-id>`）。起動・待つ・承認の一般は `archon-cli` スキルに任せると書く。
- `plugin.json`: `{"name": "works", "description": "...", "version": "0.1.0"}`。リポジトリ直下の `marketplace.json` には足さない（持ち主に確かめる物として README に書く）。

- [ ] **Step 1: 失敗するテストを書く** — `test_skill_frontmatter`（`name: works`・`description` が在る・本文に `raiki61/works:darkfactory` が在る）
- [ ] **Step 2: 赤を確かめる** / Expected: FAIL
- [ ] **Step 3: 書く**
- [ ] **Step 4: 緑を確かめる** / Expected: `OK`
- [ ] **Step 5: Commit** — `git commit -m "feat(works): works のスキル"`

---

### Task 10: 実走（持ち主に費用の了承を取ってから）

**Files:**
- Create: `works/dev/real-run.sh`
- Modify: `works/README.md`（実走の手順と結果の欄）

**Interfaces:**
- `real-run.sh`: `mktarget.sh` で対象を作り、`archon.sh workflow run darkfactory --input request=request_ok.json --input test_cmd="python3 -m unittest -q"` を前景で回す。関所で止まったら、テストの結果を見て `archon.sh workflow approve <run-id>` → `archon.sh workflow resume` で最後まで。

- [ ] **Step 1: 持ち主に「1 回約 0.5 ドル（sonnet・OAuth の名目の額）の実走を撃ってよいか」を聞く**
- [ ] **Step 2: 撃つ** — Expected: 判定の輪が通り（拒否 → 出し直しが起きてもよい）、修正の後の `python3 -m unittest` が緑、関所で止まる、承認後に `delta` が `ok: true` で終わる
- [ ] **Step 3: 結果を README の実走の欄に書く**（所要・費用・拒否の回数・赤になった所）。赤なら直す課題として計画に足す
- [ ] **Step 4: Commit** — `git commit -m "docs(works): 実走の結果"`
