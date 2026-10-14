# PR を作業場に広げるライン（dispatch）の実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/whose-turn` の自分の番の PR を、空いている herdr の作業場に、選んだアカウントの Claude Code で起こし、`/catchup <番号>` と 2 ターン目の文を送るところまでを、AI を使わずにスクリプトでやる。

**Architecture:** `works/dispatch/` に、JSON で入出力する 8 つのノード（prs・sessions・accounts・slots・assign・launch・turn・report）を置き、入口の `dispatch.py` だけが流れを持つ。外とのやりとりは `herdr.py`・`gitx.py`・`claudex.py` の 3 つの口に寄せ、判断のノードは純粋な関数にする。開いている会話は、Claude Code の公式の口 `claude agents --json` で集め、`(リポジトリ, 枝)` の組で PR と突き合わせる。`whose-turn.py` は attention を正本に、リポジトリの写しの仕組みで works へ写す。決まりの柵と CI への載せは最初（Task 3）に張り、以後のタスクはその下で作る。

**Tech Stack:** Python 3.12（CI の版。`tomllib` を使う）、標準ライブラリだけ、`unittest`、`ast`（柵）。外の道具は herdr 0.9.x、Claude Code（`claude agents --json`）、git、gh。

**Spec:** `works/docs/specs/2026-10-14-catchup-dispatch-design.md`（以下、設計書）。作る前に全部読む。節の番号はそこを指す。

## Global Constraints

- 標準ライブラリだけで書く。`shell=True` を使わない（文は argv で渡す）。
- 設計書 4 節の D1〜D8 を守る。D1: `works/dispatch/` は `works/.shared/`・`works/dev/`・`works/darkfactory/`・`works/blk-*` を読まず import しない。D2: `works/dispatch/` に `.sh` を置かない。D5: こちらから期限を足さない（`timeout` の字を書かない。herdr の結末の語 `agent_prompt_stalled` は除く）。D6: `raiki61`・`claude-code-oauth-`・`/Users/`・`claude-p` の字を `works/dispatch/` に書かない（`vendor/` の写しは除く）。
- 設定のパスの既定は `~/.config/works/dispatch.toml`、環境変数 `WORKS_DISPATCH_CONFIG` で替える。`limit_percent` の既定は 95、`limits_dir` の既定は `~/.cache/claude-limits`。
- すべての JSON の出力は頭に `"schema": 1` を持つ。読む側は `schema` が 1 でなければ止まる。
- 結末の語は `sent`・`blocked`・`stalled`・`already_open`・`no_slot`・`no_account`・`launch_failed`・`send_failed` の 8 つだけ（設計書 2 節の 6 つに、起こせなかった時の `launch_failed` と、送る命令が誤りを返した時の `send_failed` を足す。設計書もこの 8 つに直す）。
- 試験は `works/dispatch/tests/` に置き、旧 works の `works/tests/run.sh` には載せない。CI へは根の `tests/run.sh` から載せる（Task 3）。
- 版上げ（attention・works の `plugin.json` と marketplace の `metadata.version`）は枝の最後の commit にする（リポジトリの直下の `CLAUDE.md` の「出荷」）。タグは作らない。
- 手元の試験は `nice -n 19` で回し、重い段は回さない（同じ `CLAUDE.md` の「試験」）。

## Review Focus

1. **同じ枝の名前が別のリポジトリにある。** `main` のような枝の名前は、ほかのリポジトリの clone にもある。sessions が別のリポジトリの会話の枝で PR を `already_open` にしてはいけない。会話の `cwd` の origin が対象のリポジトリと同じものだけを数える（Task 6 の試験）。
2. **PR が 0 件。** 報告に「自分の番の PR は無い」の 1 行を出し、終了コード 0 で何も起こさない（Task 9 の試験）。
3. **計画の後にペインが消える・herdr が落ちる。** launch がその PR を `launch_failed` にし、ほかの PR は続ける（Task 8 の試験）。
4. **2 ターン目の文に引用符・改行・`$` がある。** argv で渡し、シェルの展開を通さない（Task 5 の試験で、偽物の runner が受けた argv の文が元の文と同じ）。
5. **使用率の控えが壊れている（JSON でない・欄が無い）。** そのアカウントを使用率が分からないものとして扱い、順の最後に置き、報告の頭に 1 行出す。止めない（Task 4 の試験）。

---

### Task 1: whose-turn の機械向けの出力（`--json`）

**Files:**
- Modify: `attention/scripts/whose-turn.py`（`parser()` に `--json` を足す。`report()` の頭で分ける）
- Modify: `attention/README.md`（`/whose-turn` の節に `--json` を 1 行）
- Test: `tests/whose-turn-suite.py`

**Interfaces:**
- Produces: `python3 whose-turn.py [login] --repo OWNER/NAME --json` が標準出力に次を出す。`{"schema": 1, "repo": str, "login": str, "generated_at": ISO8601 UTC, "prs": [{"number": int, "url": str, "title": str, "head": str, "role": "implementer"|"reviewer", "days": int}]}`。`prs` は報告の「自分の番」の節と同じ集合・同じ順。`role` は PR の作者が login なら `implementer`、そうでなければ `reviewer`。`days` は報告の N 日と同じ数。
- `--json` は `--all`・`--materials`・`--out` と一緒に渡すと、argparse の誤りで終了コード 2。

- [ ] **Step 1: 失敗する試験を書く**（suite の `report()` の助けを使う。`args=("--json",)`）

```python
class Json(unittest.TestCase):
    def test_json_lists_my_turn_prs_with_head_and_role(self):
        mine = pr(number=7, title="直す", headRefName="feat/7", author={"login": "bob"}, isDraft=True)
        theirs = pr(number=8, headRefName="feat/8", reviewRequests=requests(user("alice")), author={"login": "bob"})
        out = json.loads(report(mine, theirs, who="bob", args=("--json",)))
        self.assertEqual(out["schema"], 1)
        self.assertEqual([p["number"] for p in out["prs"]], [7])
        self.assertEqual(out["prs"][0]["head"], "feat/7")
        self.assertEqual(out["prs"][0]["role"], "implementer")

    def test_json_role_is_reviewer_for_others_pr(self): ...  # bob にレビュー依頼がある alice の PR → role == "reviewer"

    def test_json_refuses_all(self):
        with self.assertRaises(SystemExit) as e, contextlib.redirect_stderr(io.StringIO()):
            flow.main(["bob", "--repo", "o/n", "--json", "--all"])
        self.assertEqual(e.exception.code, 2)
```

- [ ] **Step 2: 走らせて落ちるのを見る** — `nice -n 19 python3 tests/whose-turn-suite.py Json -v` → `--json` を知らない誤りで FAIL。
- [ ] **Step 3: 実装する** — `report()` の中の `pr_rows(me)` と `BUCKETS` の「自分の番」の `keep` をそのまま使い、行の印字の代わりに上の dict を `json.dumps(..., ensure_ascii=False)` で出す。並びと日数を報告と共有し、2 つ目の判定を書かない。排他は `ap.add_mutually_exclusive_group` ではなく `parse_args` の後で `ap.error()`（`--out` は outfile が足す旗なので）。
- [ ] **Step 4: 一式を走らせて通す** — `nice -n 19 python3 tests/whose-turn-suite.py` → `OK`（既存の 111 件も緑）。
- [ ] **Step 5: Commit** — `git commit -m "feat(attention): whose-turn に自分の番の PR を JSON で出す --json を足す"`

### Task 2: whose-turn を works へ写す

**Files:**
- Modify: `attention/scripts/whose-turn.py`・`attention/scripts/lib/outfile.py`（docstring に `scripts/shared-copies.py` の印の 1 文「この本文は複数のプラグインに写しで在る」と、正本がどちらかの 1 文を足す）
- Create: `works/dispatch/vendor/whose-turn.py`・`works/dispatch/vendor/lib/outfile.py`（`python3 scripts/shared-copies.py --sync attention/scripts/whose-turn.py` などで作る。手で写さない）

**Interfaces:**
- Produces: `works/dispatch/vendor/whose-turn.py`（Task 1 の `--json` を持つ写し）。

- [ ] **Step 1: 写しの柵が今は緑なのを見る** — `python3 scripts/shared-copies.py` → 終了コード 0。
- [ ] **Step 2: 印を足して、写し先を作り、`--sync` で配る。** 写し先のフォルダが無いと `--sync` が写し先を作らないなら、先に空のファイルを置いてから `--sync` する（`scripts/shared-copies.py` の `sync()` を読んで決める）。
- [ ] **Step 3: 柵が緑で、写しを 1 字変えると赤になるのを見る** — `python3 scripts/shared-copies.py` → 0。写しに 1 字足して → 1。戻す。
- [ ] **Step 4: Commit** — `git commit -m "feat(works): whose-turn と outfile を attention から dispatch へ写す"`

### Task 3: 土台（決まりの柵・CI・設定・JSON の入出力・schema の照らし）

**Files:**
- Create: `works/dispatch/tests/test_rules.py`（決まりの柵。この Task で最初に作り、以後のタスクはずっとこの下で作る）
- Modify: `tests/run.sh`（dispatch の試験を 1 行で載せる: `expect_output 0 "OK" "works/dispatch: 試験と決まりの柵" "$PY_BIN" -m unittest discover -s "$ROOT/works/dispatch/tests" -t "$ROOT"`。attention/whose-turn の段の近くに置く）
- Create: `works/dispatch/config.py`・`works/dispatch/jsonio.py`・`works/dispatch/schemas/`（以後のノードの schema を置く場所）
- Create: `works/dispatch/tests/__init__.py`・`works/dispatch/tests/schemacheck.py`・`works/dispatch/tests/test_config.py`

**柵（`test_rules.py`）の中身:** 設計書 4 節の D1〜D6・D8 の「機械」の行を試験にする（D7 は人が見る）。照らしから `vendor/` と `tests/` を外す。字で探すのは D1・D2・D5・D6 だけで、構造の決まりは Python の構文木（`ast`）で見る。
- D3: `works/dispatch/nodes/*.py` の import に、ほかのノードの名が無い。
- D4: `subprocess` を import してよいのは `herdr.py`・`gitx.py`・`claudex.py`・`nodes/prs.py`・`dispatch.py`（始める前の確かめ）だけ。`herdr.run` と `herdr.prompt` を呼んでよいのは `nodes/launch.py` と `nodes/turn.py` だけ（`ast.Attribute` の `herdr.run`・`herdr.prompt` と、`from herdr import run, prompt` の両方を見る）。
- D8: `schemas/` の各ファイルが JSON として読め、`"type": "object"` で `schema` を `required` に持つ。各ノードの試験が出力をそれで照らすのは、ノードのタスクの試験が持つ。
- 柵が張りぼてでないことを見るため、この Task の試験に「わざと破った小さな木を一時フォルダに作ると、その柵の関数が誤りを返す」を 1 つずつ書く（柵の関数は、照らす根のパスを引数で受ける形にする）。

**Interfaces:**
- Produces:
  - `config.Account = NamedTuple(name: str, command: str, config_dir: str | None = None)`（`config_dir` は、そのアカウントの Claude Code の設定のフォルダ。会話を集める `claude agents --json` と、始める前の attention の確かめに使う。None は Claude Code の既定のフォルダで、`CLAUDE_CONFIG_DIR` を付けずに呼ぶ）、`config.Slot = NamedTuple(workspace: str, path: str)`、`config.Repo = NamedTuple(repo: str, second_prompt: str, slots: tuple[Slot, ...])`、`config.Config = NamedTuple(limit_percent: int, limits_dir: str, accounts: tuple[Account, ...], repos: tuple[Repo, ...])`。
  - `config.load(path: str | None = None, env: Mapping = os.environ) -> Config`。パスは引数 → `WORKS_DISPATCH_CONFIG` → `~/.config/works/dispatch.toml`。`~` は展開する。`second_prompt_file` を読んで `second_prompt` に入れる。`accounts` が無ければ `(Account("default", "claude"),)`（D7）。形が違えば `config.ConfigError` を、何が足りないかの全部を 1 つの文にして上げる。
  - `jsonio.dump(obj: dict, out: str | None) -> None`（`schema` が無ければ 1 を足す。`out` が None なら標準出力）、`jsonio.load(path: str) -> dict`（`schema != 1` なら `jsonio.SchemaVersionError`）。
  - `tests/schemacheck.check(obj, schema: dict) -> list[str]`（誤りの一覧。`type`・`required`・`properties`・`items`・`enum` だけを解く小さな照らし。外のパッケージを入れない）。

- [ ] **Step 0: 柵を先に作る。** `test_rules.py` を書き、わざと破った木で各柵が誤りを返すことと、今の木（まだほぼ空）で緑なことを見る。`tests/run.sh` に載せ、`GL_TEST_ONLY` で dispatch の 1 行だけ回して緑を見る（`tests/run.sh` の頭の説明の通り、手元で一式は回さない）。
- [ ] **Step 1: 失敗する試験を書く** — `test_config.py`: 設計書 5 節の TOML（4 アカウント・1 リポジトリ・slots 2 つ）を一時ファイルに書いて `load()` すると `Config(limit_percent=95, ...)` になる／`accounts` の無い TOML で `accounts == (Account("default", "claude"),)`／`second_prompt_file` が無いと `ConfigError` の文にそのパスが入る／`WORKS_DISPATCH_CONFIG` が引数の無い時に効く／`jsonio.load` が `{"schema": 2}` で `SchemaVersionError`。
- [ ] **Step 2: 走らせて落ちるのを見る** — `nice -n 19 python3 -m unittest discover -s works/dispatch/tests -t . -v` → import の誤り。
- [ ] **Step 3: 実装する。** 試験からの import は、`works/dispatch/tests/__init__.py` で `works/dispatch` を `sys.path` の頭に入れて、`import config` の形で行う（`works/dispatch` はパッケージにしない。ノードを単独のコマンドとしても走らせるため）。
- [ ] **Step 4: 通す** — 同じ命令 → `OK`。
- [ ] **Step 5: Commit** — `git commit -m "feat(works): dispatch の決まりの柵・CI への載せ・設定と JSON の入出力の土台"`

### Task 4: accounts ノード

**Files:**
- Create: `works/dispatch/nodes/accounts.py`・`works/dispatch/schemas/accounts.schema.json`
- Test: `works/dispatch/tests/test_accounts.py`

**Interfaces:**
- Consumes: `config.Account`、`jsonio`。
- Produces: `accounts.rank(accounts: Sequence[Account], limits: Mapping[str, dict | None], limit_percent: int, now: float) -> list[dict]`。1 件は `{"name", "command", "seven_day": {"used": int|None, "resets_at": int|None}, "five_hour": {...}, "eligible": bool, "reason": str|None}`。選べるものが先で、設計書 2 節の 3 の順。選べないものは後ろに設定の順で並べる。`limits[name]` が None は控えが無いか読めない時。`accounts.read_limits(limits_dir: str, names) -> dict[str, dict | None]`（壊れた JSON は None）。`main(argv)`: `--config`・`--out`。

- [ ] **Step 1: 失敗する試験を書く**（2026-10-14 の実の値を使う）

```python
NOW = 1791963000
LIMITS = {
    "main": {"seven_day": {"used_percentage": 86, "resets_at": 1792119600}, "five_hour": {"used_percentage": 1, "resets_at": 1791979200}},
    "p1":   {"seven_day": {"used_percentage": 38, "resets_at": 1792155600}, "five_hour": {"used_percentage": 1, "resets_at": 1791979200}},
    "p2":   {"seven_day": {"used_percentage": 86, "resets_at": 1792119600}, "five_hour": {"used_percentage": 0, "resets_at": 1791979200}},
    "p3":   {"seven_day": {"used_percentage": 79, "resets_at": 1792382400}, "five_hour": {"used_percentage": 24, "resets_at": 1791968400}},
}
def test_order_is_nearest_weekly_reset_then_lower_use_then_config_order(self):
    got = rank(ACCTS, LIMITS, 95, NOW)
    self.assertEqual([a["name"] for a in got], ["main", "p2", "p1", "p3"])
def test_over_limit_weekly_is_excluded(self): ...      # main の seven_day 96 → eligible False、reason に "seven_day"
def test_over_limit_five_hour_is_excluded(self): ...   # p2 の five_hour 96 → eligible False
def test_exactly_limit_is_eligible(self): ...          # 95 は選べる（「95% を超えたら」なので）
def test_past_reset_counts_as_zero(self): ...          # resets_at < NOW の週の枠 → used 0、eligible True
def test_missing_or_broken_limits_go_last_but_eligible(self): ...  # limits["p1"] = None → eligible True、順の最後
```

- [ ] **Step 2: 落ちるのを見る。**
- [ ] **Step 3: 実装する。** 並べの鍵は `(not eligible, unknown, seven_day.resets_at, seven_day.used, 設定の順)`。
- [ ] **Step 4: 通し、出力を `schemacheck` で `accounts.schema.json` に照らす試験も緑にする。**
- [ ] **Step 5: Commit** — `git commit -m "feat(works): dispatch の accounts ノード（週の枠の切り替わりの近い順）"`

### Task 5: 外への口（herdr・git・Claude Code）

**Files:**
- Create: `works/dispatch/herdr.py`・`works/dispatch/gitx.py`・`works/dispatch/claudex.py`
- Test: `works/dispatch/tests/test_herdr.py`・`works/dispatch/tests/test_gitx.py`・`works/dispatch/tests/test_claudex.py`

**Interfaces:**
- 3 つとも、呼び出しを `runner(argv: list[str]) -> subprocess.CompletedProcess` で受ける（既定は `subprocess.run(argv, capture_output=True, text=True)`）。試験は偽物の runner を渡す。
- Produces（herdr.py）:
  - `panes(runner=...) -> list[dict]`: `herdr pane list` の `result.panes` を返す。各 dict の鍵は `pane_id`・`workspace_id`・`cwd`・`agent`（無ければ None）・`agent_status`。
  - `workspace_labels(runner=...) -> dict[str, str]`: `herdr workspace list` から workspace_id → label。
  - `methods(runner=...) -> set[str]`: `herdr api schema` の出力からメソッドの名の集合。
  - `run(pane: str, command: str, runner=...) -> None`: `herdr pane run <pane> <command>`。書く口その 1。
  - `prompt(target: str, text: str, wait: bool, runner=...) -> str`: `herdr agent prompt <target> <text> [--wait]`。`--wait` の時は herdr の JSON の結果から状態（`idle`・`done`・`blocked`）を返し、herdr の誤りの符号が `agent_prompt_stalled` なら `"stalled"` を返す。`--wait` が無い時は `"sent"`。書く口その 2。
  - `wait_ready(pane: str, runner=...) -> str`: 起こした直後に、会話が見つかって入力を待つまで待ち、状態を返す。中身は Task 10 で手元の herdr で確かめて決める。この Task では `herdr agent wait <pane> --until idle` を呼ぶ形で書き、試験は argv だけを縛る。
  - 失敗（終了コードが 0 でない）は `herdr.HerdrError(argv, stderr)`。
- Produces（gitx.py）: `branch(cwd) -> str | None`・`is_clean(cwd) -> bool`（`git status --porcelain --untracked-files=no` が空）・`origin_repo(cwd) -> str | None`（`git remote get-url origin` を `OWNER/NAME` に直す。https と `git@host:` の両方の形）。
- Produces（claudex.py）: `sessions(config_dir: str | None, runner=...) -> list[dict]`。`claude agents --json` を走らせ、返った並びをそのまま返す（2026-10-14 に Claude Code 2.1.299 で見た 1 件の形は `{"pid", "cwd", "kind", "startedAt", "sessionId", "name", "status"}`）。`config_dir` が None でなければ、子の環境に `CLAUDE_CONFIG_DIR=<config_dir>` を入れる（runner は `env` も受ける形にする）。起こすのはシェルの関数ではなく PATH の `claude` の実体（`subprocess` はシェルを通らないので、何もしなくてもそうなる）。失敗は `claudex.ClaudeError(argv, stderr)`。

- [ ] **Step 1: 失敗する試験を書く** — `claudex.sessions("~/x")` の子の環境に `CLAUDE_CONFIG_DIR` が展開済みのパスで入り、`sessions(None)` では入らない／JSON でない出力で `ClaudeError`。偽物の runner が受けた argv を見る試験: `prompt("wX:p1", "a 'b'\n$c", wait=False)` の argv の最後の前が `"a 'b'\n$c"` そのまま（Review Focus 4）／`prompt(..., wait=True)` が `--wait` を付け、偽物が返した `{"result": {"agent_status": "idle"}}` 形の出力（形は Step 3 で `herdr agent prompt --help` と `herdr api schema` を見て合わせる）から `"idle"` を返す／stalled の誤りで `"stalled"`／`origin_repo` が `git@github.com:o/r.git` と `https://github.com/o/r` を `o/r` にする。
- [ ] **Step 2: 落ちるのを見る。**
- [ ] **Step 3: 実装する。** herdr の出力の形は、手元の `herdr pane list`・`herdr workspace list`・`herdr api schema` の実物を読んで合わせる（書く命令は走らせない）。
- [ ] **Step 4: 通す。**
- [ ] **Step 5: Commit** — `git commit -m "feat(works): dispatch の herdr・git・Claude Code の口"`

### Task 6: sessions ノードと slots ノード（固定の作業場）

**Files:**
- Create: `works/dispatch/nodes/sessions.py`・`works/dispatch/nodes/slots.py`・`works/dispatch/schemas/sessions.schema.json`・`works/dispatch/schemas/slots.schema.json`
- Test: `works/dispatch/tests/test_sessions.py`・`works/dispatch/tests/test_slots_contract.py`

**Interfaces:**
- Consumes: `claudex.sessions`・`herdr.panes`・`herdr.workspace_labels`・`gitx.branch`・`gitx.origin_repo`・`gitx.is_clean`、`config.Repo`・`config.Account`。
- Produces:
  - `sessions.collect(listed: dict[str, list[dict]], branch_of, origin_of) -> list[dict]`。`listed` はアカウントの名 → そのアカウントの `claudex.sessions` の結果。1 件 `{"account", "session_id", "cwd", "status", "repo", "branch"}`。`repo` と `branch` は `cwd` から git で読む（読めなければ None）。herdr は使わない。
  - `sessions.open_keys(sessions: list[dict]) -> set[tuple[str, str]]`: `(repo, branch)` の組の集合（None を含む組は入れない）。assign はこれと `(対象のリポジトリ, PR の head)` を突き合わせる（Review Focus 1）。
  - `slots.fixed(repo: Repo, panes: list[dict], labels: dict, session_cwds: set[str], branch_of, is_clean) -> list[dict]`。設定の slots の順に 1 件ずつ `{"workspace", "pane", "path", "branch", "free": bool, "reason": str|None}`。`reason` は `"no_pane"`（その名の workspace が無い）・`"agent"`（herdr がそのペインに会話を見ている。入力待ちを含む）・`"session"`（どれかのアカウントの会話の `cwd` が、その作業場の path と同じか、その下にある）・`"dirty"`（追跡ファイルに変更）・`"path_mismatch"`（ペインの cwd が設定の path と違う）。
  - 2 つとも `main(argv)`: `--config`・`--repo`・`--out`。

- [ ] **Step 1: 失敗する試験を書く。** `test_slots_contract.py` は作業場のノードの約束の試験で、差し替えの実装も同じ試験を通す（設計書 3 節）。関数を 1 つ受けて回す形にする: `def contract(impl): ...`。中身: 会話のあるペイン（状態 `idle` でも）は `free == False, reason == "agent"`（持ち主の決め: 入力待ちの会話を閉じない）／会話が無く clean なら `free == True`／dirty なら `reason == "dirty"`／herdr のペインに会話が無くても、どれかのアカウントの会話の `cwd` がその path にあれば `reason == "session"`／workspace が無ければ `reason == "no_pane"`／出力が `slots.schema.json` に合う。`test_sessions.py`: 2 つのアカウントの一覧を合わせる／別の origin の会話は、枝の名前が同じでも組が違う（`("o/other", "main")` と `("o/r", "main")` を別に数える）／git で読めない `cwd` の会話は組に入らない。
- [ ] **Step 2: 落ちるのを見る。**
- [ ] **Step 3: 実装する。** ペインの対応は workspace の label で引く（`labels[pane["workspace_id"]] == slot.workspace`）。1 つの workspace に複数のペインがあれば、最初のペインを使い、`reason` は付けない（固定の作業場は 1 ペインの前提。違う時の扱いは Task 10 で持ち主に見せる）。
- [ ] **Step 4: 通す。**
- [ ] **Step 5: Commit** — `git commit -m "feat(works): dispatch の sessions と slots（固定の作業場）"`

### Task 7: assign ノード

**Files:**
- Create: `works/dispatch/nodes/assign.py`・`works/dispatch/schemas/plan.schema.json`
- Test: `works/dispatch/tests/test_assign.py`

**Interfaces:**
- Consumes: Task 1 の `prs`、Task 6・Task 4 の出力の dict の並び。
- Produces: `assign.plan(repo: str, prs: list[dict], open_keys: set[tuple[str, str]], accounts: list[dict], slots: list[dict]) -> list[dict]`（`open_keys` は Task 6 の `sessions.open_keys` の結果）。1 件 `{"number", "title", "head", "outcome": "assigned"|"already_open"|"no_account"|"no_slot", "account": dict|None, "slot": dict|None}`。並びは prs の順。`main(argv)`: `--repo`・`--prs`・`--sessions`・`--accounts`・`--slots`（JSON のパス）・`--out`。

- [ ] **Step 1: 失敗する試験を書く** — `(repo, head)` が `open_keys` にある PR は `already_open`／枝の名前が同じでも別のリポジトリの組なら数えない／選べるアカウントが 0 なら残りは全部 `no_account`／全部が先頭の選べるアカウントに入る／空きの作業場が足りなければ後ろの PR から `no_slot`／空きの中に head と同じ枝の作業場があれば、設定の順より先にそれを使う／1 つの作業場に 2 件入らない／`already_open` は作業場もアカウントも取らない。
- [ ] **Step 2: 落ちるのを見る。**
- [ ] **Step 3: 実装する。** 決める順は、`already_open` → `no_account` → 作業場（同じ枝の空きを先、無ければ設定の順の最初の空き）→ `no_slot`。
- [ ] **Step 4: 通す（schema の照らしも）。**
- [ ] **Step 5: Commit** — `git commit -m "feat(works): dispatch の assign ノード"`

### Task 8: launch ノードと turn ノード

**Files:**
- Create: `works/dispatch/nodes/launch.py`・`works/dispatch/nodes/turn.py`・`works/dispatch/schemas/launch.schema.json`・`works/dispatch/schemas/turn.schema.json`
- Test: `works/dispatch/tests/test_launch_turn.py`

**Interfaces:**
- Consumes: `herdr.run`・`herdr.wait_ready`・`herdr.prompt`・`herdr.panes`。
- Produces:
  - `launch.start(row: dict, h=herdr) -> dict`: `h.run(row["slot"]["pane"], row["account"]["command"])` の後に `h.wait_ready(pane)` し、`h.panes()` を読み戻して、そのペインの `agent == "claude"` を確かめる。返り値 `{"number", "pane", "status": "ready"|"launch_failed", "detail": str|None}`。`HerdrError` と、読み戻しで会話が見えない時は `launch_failed`。
  - `turn.send(pane: str, text: str, wait: bool, h=herdr) -> dict`: `{"pane", "status": "idle"|"done"|"blocked"|"stalled"|"sent"|"failed", "detail"}`。
  - `turn.catchup_then_second(number: int, pane: str, second: str, h=herdr) -> str`: 1 ターン目 `/catchup <number>` を `wait=True` で送り、`idle` か `done` の時だけ 2 ターン目を `wait=False` で送る。結末の語 `sent`・`blocked`・`stalled`・`send_failed` のどれかを返す（`HerdrError` は `send_failed`）。
  - 2 つとも `main(argv)`。

- [ ] **Step 1: 失敗する試験を書く**（偽物の herdr を module の形で渡す）— 起こした後の読み戻しで会話が無ければ `launch_failed`／`run` が `HerdrError` なら `launch_failed`／1 ターン目が `blocked` なら 2 ターン目を送らず `blocked`／1 ターン目が `stalled` なら `stalled`／`idle` なら 2 ターン目を `wait=False` で送り `sent`／送った文が設定の文と 1 字も違わない。
- [ ] **Step 2: 落ちるのを見る。**
- [ ] **Step 3: 実装する。**
- [ ] **Step 4: 通す。**
- [ ] **Step 5: Commit** — `git commit -m "feat(works): dispatch の launch と turn（2 ターン目は 1 ターン目が止まらずに終えた時だけ）"`

### Task 9: report ノードと入口（`dispatch.py`）

**Files:**
- Create: `works/dispatch/nodes/report.py`・`works/dispatch/dispatch.py`・`works/dispatch/nodes/prs.py`
- Test: `works/dispatch/tests/test_report.py`・`works/dispatch/tests/test_dispatch.py`

**Interfaces:**
- Consumes: 全ノード。
- Produces:
  - `prs.fetch(repo: str, runner=...) -> dict`: `python3 <works/dispatch/vendor/whose-turn.py> --repo <repo> --json` を走らせて読む。`main(argv)`。
  - `report.lines(plan: list[dict], results: dict[int, str], notes: list[str]) -> list[str]`: 頭に notes（控えの無いアカウントなど）、PR ごとに 1 行 `#<番号> <タイトル>  <workspace|->  <アカウント|->  <結末>`、PR が 0 件なら `自分の番の PR は無い` の 1 行。
  - `dispatch.preflight(cfg, h=herdr, runner=...) -> list[str]`: 設計書 6 節の確かめ。足りない物の文の一覧（空なら進む）。使用率の控えが無いアカウントは止めずに notes へ。アカウントのコマンドは `zsh -ic 'whence <cmd>'`、attention は各アカウントの設定のフォルダの `plugins/installed_plugins.json`。`config_dir` が None のアカウントは、attention の確かめを飛ばして notes に 1 行出す。
  - `dispatch.main(argv) -> int`: `--config`・`--repo`（省略時は設定の最初の repo）・`--dry-run`。流れは設計書 2 節。launch は全部先に、turn は `concurrent.futures.ThreadPoolExecutor` で PR ごとに並べる。終了コード: 確かめが足りなければ 2、それ以外は 0（`blocked` や `no_slot` は誤りではない）。

- [ ] **Step 1: 失敗する試験を書く** — `test_report.py`: 0 件の 1 行（Review Focus 2）／notes が頭に出る。`test_dispatch.py`（全ノードの外の口を偽物にして `main` を回す）: `--dry-run` で `herdr.run` と `herdr.prompt` が 1 回も呼ばれない／確かめが足りないと 2 で、何も起こさない／2 件の PR で、1 件目の launch が `launch_failed` でも 2 件目は `sent` まで進む（Review Focus 3）。
- [ ] **Step 2: 落ちるのを見る。**
- [ ] **Step 3: 実装する。**
- [ ] **Step 4: 通す。**
- [ ] **Step 5: Commit** — `git commit -m "feat(works): dispatch の report と入口（--dry-run）"`

## 改訂（2026-10-14、Task 9 の後）: 固定の作業場から PR ごとの clone へ

持ち主が決めた（「0~10個たくわえるんじゃなくて」）。設計書 3 節を書き直した。Task 6 の slots（固定の作業場）は使わなくなるので、Task 10 で外す。結末の語は `no_slot` をやめ、`provision_failed` を足す。

### Task 10: 作業場を PR ごとの clone に替える

**Files:**
- Modify: `works/dispatch/config.py`（`Repo` から `slots` を外し、`source: str`・`clone_root: str`・`copy_files: tuple[str, ...]` を足す。`source` と `clone_root` は必須、`copy_files` は省略可）
- Modify: `works/dispatch/gitx.py`（書く関数 `clone(source, path)`・`set_origin(path, url)`・`fetch(path)` を足す。`origin_url(cwd) -> str | None` も足す）
- Create: `works/dispatch/nodes/provision.py`・`works/dispatch/schemas/provision.schema.json`
- Modify: `works/dispatch/herdr.py`（書く関数 `create_workspace(cwd, label) -> dict`（`herdr workspace create --cwd <cwd> --label <label> --no-focus`。返り値は作った作業場と最初のペイン）と `close_workspace(workspace_id)` を足す）
- Modify: `works/dispatch/nodes/assign.py`（slots を受けず、`clone_path` を案に付ける。`already_open` は (リポジトリ, 枝) の組か、PR の clone のフォルダの下の会話）
- Modify: `works/dispatch/dispatch.py`（slots の代わりに provision を launch の前に呼ぶ。`--dry-run` の報告に作るか使い直すかを出す）
- Delete: `works/dispatch/nodes/slots.py`・`works/dispatch/schemas/slots.schema.json`（`pick_repo` は `config.py` へ移す）
- Modify: `works/dispatch/tests/fences.py`（D4 の表: 書く関数と、呼んでよいノードの対応）
- Test: `works/dispatch/tests/test_provision.py`、既存の試験を合わせて直す

**Interfaces:**
- `provision.clone_path(repo: Repo, number: int) -> str`: `<clone_root>/<repo の名前の後ろ半分>-pr-<番号>`。
- `provision.prepare(row: dict, repo: Repo, h=herdr, g=gitx) -> dict`: `{"number", "path", "pane", "workspace", "created": bool, "status": "ready"|"provision_failed", "detail"}`。フォルダが無ければ clone・origin の向け直し・fetch・`copy_files` の写し。有れば、その origin が対象のリポジトリかを確かめて fetch だけ。違うリポジトリなら `provision_failed`（上書きしない）。herdr の作業場は、cwd がそのフォルダのペインを `h.panes()` から探し、無ければ `h.create_workspace(path, <フォルダの名前>)`。最後に、フォルダが git の clone で origin が対象のリポジトリであること、ペインが有ることを読み戻す。
- `assign.plan(repo: Repo, prs, open_keys, open_cwds: set[str], accounts) -> list[dict]`: 1 件 `{"number", "title", "head", "url", "outcome": "assigned"|"already_open"|"no_account", "account", "clone_path"}`。

- [ ] **Step 1: 失敗する試験を書く。** `test_provision.py` は一時のフォルダに本物の git のリポジトリを作り、元の clone に見立てる（origin は `https://github.com/o/r.git` にしておく）: 無ければ作り、作った clone の origin が元の clone の origin の URL で、`copy_files` が写り、偽物の herdr に `create_workspace(path, "r-pr-7")` が 1 回呼ばれる／2 回目は作らずに使い直し（`created == False`）、ペインが有れば `create_workspace` を呼ばない／同じ名前のフォルダが別のリポジトリなら `provision_failed` で、中身を変えない／`copy_files` の無いファイルは飛ばして `detail` に名を出す。`test_assign.py` を新しい形に直し、会話の cwd が clone のフォルダの下なら `already_open` を足す。`test_rules.py` に、provision の外で `gitx.clone` を呼ぶと D4 が赤、を足す。
- [ ] **Step 2: 落ちるのを見る。**
- [ ] **Step 3: 実装する。**
- [ ] **Step 4: 一式を通す。** `nice -n 19 python3 -m unittest discover -s works/dispatch/tests -t .` → OK。
- [ ] **Step 5: Commit** — `git commit -m "feat(works): dispatch の作業場を PR ごとの clone にする（固定の作業場をやめる）"`

### Task 11: 片付け（`dispatch.py --clean`）

**Files:**
- Create: `works/dispatch/nodes/clean.py`・`works/dispatch/ghx.py`（`pr_state(repo, number) -> str`。`gh pr view <番号> --repo <repo> --json state`）
- Modify: `works/dispatch/gitx.py`（`unpushed(cwd) -> bool`: 手元にしか無い commit があるか。`git log --branches --not --remotes --oneline` が空でないか）
- Modify: `works/dispatch/dispatch.py`（`--clean` と `--apply`）
- Test: `works/dispatch/tests/test_clean.py`

**Interfaces:**
- `clean.candidates(repo: Repo, folders: list[str], pr_state, open_cwds, is_clean, unpushed) -> list[dict]`: `<clone_root>` の `<名前>-pr-<番号>` のフォルダごとに `{"path", "number", "removable": bool, "reason"}`。消してよいのは、PR が `MERGED` か `CLOSED`、そのフォルダの下の会話が無い、未コミットの変更が無い、手元にしか無い commit が無い、の全部を満たす時だけ。
- `clean.remove(row, h=herdr) -> dict`: フォルダを消し、そのフォルダのペインに会話が無ければ herdr の作業場を閉じる。消した後にフォルダが無いことを読み戻す。

- [ ] **Step 1: 失敗する試験を書く** — 開いている PR は消さない／会話の有るフォルダは消さない／未コミットか手元だけの commit が有れば消さない／条件を全部満たせば候補／`--clean` だけでは何も消さず候補を並べる／`--clean --apply` で候補だけを消し、会話の有るペインの herdr の作業場は閉じない。
- [ ] **Step 2: 落ちるのを見る。**
- [ ] **Step 3: 実装する。**
- [ ] **Step 4: 通す。**
- [ ] **Step 5: Commit** — `git commit -m "feat(works): dispatch の片付け（--clean。既定は候補を並べるだけ）"`

### Task 12: 持ち主の前で、手元の herdr と Claude Code で確かめる

試験では縛れないことを、持ち主が見ている前で決める（設計書 9 節）。持ち主の許しなしに herdr の書く命令を走らせない。

- [ ] **Step 1:** `~/.config/works/dispatch.toml` と 2 ターン目の文のファイルを、持ち主の値で作る（リポジトリには入れない）。
- [ ] **Step 2:** `python3 works/dispatch/dispatch.py --dry-run` を、guided-resolver を読める gh のアカウントのシェルで走らせ、案を持ち主と見る。
- [ ] **Step 3:** 持ち主が選んだ PR 1 件で本当に走らせる。見ること: clone を作る時間、herdr の作業場が開くか、`wait_ready` が会話の見つかる前のペインで待てるか、複数行の 2 ターン目の文が 1 つの文として届くか、起こした会話が `claude agents --json` に選んだアカウントで出るか。
- [ ] **Step 4:** 違えば外への口だけを直し、試験を実物に合わせて足す。直したら Step 3 をもう一度。
- [ ] **Step 5: Commit** — `git commit -m "fix(works): dispatch の外への口を手元の herdr と Claude Code の振る舞いに合わせる"`（直した時だけ）

### Task 13: 前提の文書・セットアップ（`init` と `check`）・`/works:dispatch` の入口

持ち主の頼み（2026-10-14「そういう前提みたいなのをそのプラグインに書いておかないといけないし、セットアップみたいなスキルもいるんじゃないの」）。

- 前提（herdr が動いている／`claude agents --json` を持つ Claude Code／各アカウントに attention／対象を読める gh／リポジトリごとの代表 clone が既定の枝にいる／アカウントごとの起動のコマンド／使用率の控えは任意）を、README と手順書に書き、7 つとも `check` でも確かめる（今の preflight に、Claude Code の版と、代表 clone の枝を足す）。
- `dispatch.py init --repo <OWNER/NAME> --source <代表 clone>`: 設定が無い時だけ下書きを書く（有れば上書きせず足す分を出す）。アカウントは `claude agents --json` が通る設定のフォルダの候補をコメントで並べ、起動のコマンドは人が書く。`copy_files` は代表 clone の追わない小さな設定のファイル（`.env*`・`*.local.*` など。依存と生成物のフォルダは除く）を候補で並べる。2 ターン目の文のファイルは空の雛形。
- `dispatch.py check`: 始める前の確かめを単独で走らせ、足りない物と直し方を 1 行ずつ出す。
- `/works:dispatch` は割り振り、`/works:dispatch setup` は `init` と `check` を走らせて出力をそのまま見せる。どちらも判断させない。

元の Task 13 の中身（以下）も含む。

### Task 13（元の中身）: `/works:dispatch` と文書

振る舞いが Task 12 で決まってから書く。先に書くと、実物と食い違う。

**Files:**
- Create: `works/skills/dispatch/SKILL.md`
- Modify: `works/README.md`（dispatch のラインの節: 何をするか、設定の書き方、`--dry-run`、`--clean`、herdr と Claude Code の版の前提）・`works/.claude-plugin/plugin.json` の `description`・`works/CHANGELOG.md` と `attention/CHANGELOG.md` の `[Unreleased]`

**Interfaces:**
- `SKILL.md` の中身は、`python3 ${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py $ARGUMENTS` を走らせ、出力をそのまま見せる、だけ。判断も言い換えもさせない。`model:` は書かない。

- [ ] **Step 1: SKILL.md を書き、`/works:dispatch --dry-run` を持ち主の会話で 1 回打って、報告がそのまま出るのを見る。**
- [ ] **Step 2: README・plugin.json の description・2 つの CHANGELOG を書く。**
- [ ] **Step 3: Commit** — `git commit -m "feat(works): /works:dispatch の入口と文書"`

### Task 14: 版上げ（枝の最後の commit）

- [ ] **Step 1:** `VERSION_BUMP_STRICT=1` で全段の試験を回す（リポジトリの直下の `CLAUDE.md` の「出荷」の 1。重い段を含むので、持ち主に回してよいか先に聞く）。
- [ ] **Step 2:** `[Unreleased]` を版に。attention は `0.26.0`（機能の追加）、works は `0.3.0`（ラインの追加）、marketplace の `metadata.version` を 1 つ上げる。
- [ ] **Step 3: Commit** — `git commit -m "chore: attention 0.26.0・works 0.3.0 に上げる（dispatch のライン）"`
- [ ] **Step 4:** push と main への取り込みは、持ち主に聞いてから（外への書き込み）。
