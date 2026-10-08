# 独立設計の材料を形式に依らず渡し、全体の地図をいつも渡し、問いが立たない根拠を実物で検算する（依頼 238）Implementation Plan

状態: 入れた（works 0.2.26。merge 30666712）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## この文書の読み方（初めて読む人向け。本文の語はここで全部定める）

読み手: この計画の Task を 1 つずつ実装する AI の役（実装役）と、それを審査する役。どちらもリポジトリ claude-plugins の作業ツリー（枝 `wip/sdd-238`。起点の commit f0ae265e = works 0.2.21）を手元に持ち、名指したファイルを開ける。本文の「今」は起点の commit のコードの振る舞いで、名指したファイルが正本。外の資料（下の Spec）は、要る所をこの文書に書き写した。開かなくても実装できる。

番号と名:
- works: リポジトリの `works/` に在るプラグイン。Archon（AI の作業の流れを YAML で回す外の道具）の上で、人の修正依頼を直す工程（ライン darkfactory）を回す。run はその 1 回の実行。
- 依頼 238: この計画の元の依頼の番号（works を works 自身の修正に使う「自分食い」の依頼の連番）。設計だけの run（run id 8c866a2e）で独立設計を作り、人の関所で決めを足した物が Spec。
- 依頼 239: 別の枝 `wip/sdd-239` で進んでいる計画（部品の盤面の置き場を include の単位で分ける）。下の「依頼 239 との重なり」に、ぶつかる所を書いた。依頼 231: 先に入った「事前審査の block を修正案の役に返して固める壁打ち」（`works/docs/plans/2026-10-03-plan-converge.md`）。
- TDD: テスト駆動開発（先にテストを書いて落ちることを見てから直す）。

置き場と道具:
- パスは、断りが無ければリポジトリの根からの相対。`design.py:70` は `works/.shared/core/design.py` の 70 行目（起点の版）。
- 盤面: run ごとの状態の置き場（`$ARTIFACTS_DIR/board/`）。この計画は盤面のファイルの名も置き場も変えない。
- 写し: `works/.shared/core/graphloops/` と `works/.shared/core/gl-prompts/` は、本流の graphloops のバイト単位の写し。この計画は写しを変えない（写しの台帳 `works/.shared/core/COPIED_FROM` に行を足さない）。写しの rules（`graphloops/rules/review-loop.py`）の関数は呼んでよい。盤面からは `b.rules`、試験からは `board.rules_module()` で引ける。
- 固めた版 HEAD: 依頼を受けた時に固めた、対象のリポジトリ（run が直すリポジトリ）の commit。名指しの文書はこの版の追跡ファイルから読む（作業ツリーの今の中身ではない）。
- 試験の段: `works/tests/tiers.py` が試験の模块を FAST（速い段）と HEAVY（重い段。git・盤面・子のプロセスを使う）に分ける。この計画で触る試験の模块 `test_blk_eyes`・`test_blk_plan`・`test_report` はどれも HEAVY。各 Task は触った模块の名指したクラスだけを回し、速い段と根の柵（リポジトリの根の試験の束）は最後の Task で 1 度だけ回す。

独立設計の語:
- 独立設計（役 r2.design）: 修正案も実装も見ずに、目的の文と渡された材料だけから理想の設計を導く AI の役。道具を一切持たない（ファイルを読めない）。この「道具を持たない隔て」は設計書 `works/docs/specs/2026-09-29-structure-block-design.md` の 7 節が決めた物で、崩さない。材料は機械（`design.prep`）が先に読んで、指示書の頭に本文として貼る。
- 突き合わせ（役 r2.compare）: 修正の後に、独立設計と差分を構造で比べる役。同じ材料を `eyes.premise_section`（`works/blk-eyes/lib/eyes.py`）が頭に貼る。材料の並びは両方とも `design.premises(b, repo)` の 1 本から作る。
- 材料の控え: `design.premises` が返す `{given, withheld, seen}`。given は貼った物、withheld は貼らなかった物とその理由。行は `{kind, what}`（withheld は `why` も）。kind は許す一覧 `design.PREMISE_KINDS` の中だけ（一覧の外を貼る口を作らない柵。今は `human_answer`・`named_section`）。盤面の根の `design-premises.json` に書く。
- 名指しの節: 依頼の文が名指した設計書の節。今は Markdown のリンク・コードスパンの `` `<path>.md#<見出し>` ``・`` `<path>.md` N 節 ``・パスの無い「N 節」「§N」（依頼が名指した設計書がただ 1 本の時だけそれに結ぶ）を拾い（`_named_targets`）、`.md` の `#` 見出し（ATX 見出し）だけで節を切る（`_section`）。引けない名指しは本文を貼らず、withheld に理由の 1 行を載せる。
- 問いが立たない返し: 独立設計の返答の型（写しの schema）は `question_stands`（真偽）・`reason`・`premise_invalid_reason`・`design` を持つ。`question_stands` が偽なら、写しの rules が R2 の判定を `premise-invalid` にし、別の会話の judge（盤面の節 `stop.premise_check`）が根拠を検算してから人へ回す。報告では R2 の行として「直しきれずに残った物」と次の run の依頼（`next-request.json`）に載る。事前審査（`works/blk-plan/lib/planblk.py` の `design_only`）は、設計と突き合わせない旨と理由を指示書に書く。
- 出どころ: `パス:開始行-終了行` の形の名指し（例 `docs/spec.md:5-14`）。この計画では、渡す材料にも、問いが立たない根拠にも、この同じ形を使う。

## Spec の要約（`/Users/p03623/.cache/works-dogfood/carry/238/spec.md` が正本）

- (1) 材料: 名指しの節の抜き出しを形式に依らない形にする（形式ごとの表を足さない。持ち主の方針「言語・形式の知識を持たない。事実上の標準は使ってよい」）。当たった行そのものから見出しの形を読む。パスの無い名前（今回の依頼の「structure-block-design 7 節」）も、追跡ファイルの名から引く。加えて、対象のリポジトリの全体の地図をいつも渡す。
- 人の関所の決め（fork A）: 新しい kind `repo_map` を足し、根の `ARCHITECTURE.md`・`AGENTS.md` を r2.design と r2.compare に貼る。無ければ withheld に理由。
- 人の関所の決め（狭めない案）: R2 の `question_stands=false` の出口は残す。`premise_invalid_reason` に `パス:行` が在る時だけ、追跡ファイルと行の範囲に当たるかを検算する。無い時は拒まず「根拠の実物の名指しなし」と名指す。
- 事前審査が挙げた後退（関所で決め手つきで通した）: 任意の拡張子のリンクを設計書に数えると、`[x](src/foo.py#L10)` のようなコードへのリンクで実装のファイルが独立設計に貼られ（隔ての破れ）、パスの無い「N 節」の結び付けも外れる。数える拡張子は既に在る文書の拡張子の集合を使う。
- 期限・タイムアウトを足さない。本流の graphloops を変えない。

## 決めたこと（どれも 1 つの軸「目的と keep-essence を保って全体がより簡潔か」で選んだ）

keep-essence は `works/docs/keep-essence.md` の、どの作りでも残す works の 11 の仕組み。この計画に関わるのは 9（独立設計と R1〜R4）。

- **決め 1（問いの立て直しの口）:** 新しい種類を足さず、R2 の今の口（`question_stands=false` と `premise_invalid_reason`）だけを使い、根拠の名指しの検算を足す。
  - redesign-needed は凍結した目的の中の作り直しで、行き先が違う。
  - premise_drift は修正の中で測った前提の変化で、問いの立て方を扱わない。
  - fork の問いは目的の中の分岐を選ぶ物で、目的の外へ出ない。
  - 依頼 231 の壁打ちは事前審査の block を案に返す輪で、凍結した目的の中に居る。
  - 行き先は今の R2 の道のまま: judge（`stop.premise_check`）の検算 → 人。報告の残りの行から `next-request.json` へ。run の途中で目的は変えない。事前審査・差分の審査・R1/R3/R4 へ同じ口を広げることは、この計画では扱わない（下の「扱わない物」）。
- **決め 2（検算と名指し）:** `premise_invalid_reason` の中の `パス:行` と `パス:開始行-終了行` を全部拾う。どれかが固めた版の追跡ファイルの行の範囲に当たらなければ、受け付け（`design.check_design`）が理由を添えて拒む（今の拒否の輪。3 回で諦める）。1 つも無ければ拒まない。その時は事前審査の指示書と報告の冒頭 1 に「根拠の実物の名指しなし」と出す。拾うのは拡張子つきのパスだけ。URL（`https://x:443/`）と時刻（`10:15`）は拾わない。
- **決め 3（文書の拡張子）:** 名指しを設計書として数えるのは、拡張子が `impact.DOC_EXT`（`works/.shared/core/impact.py:79`。md・markdown・txt・rst・adoc・html・xml など。コードを含まない）に在るパスだけ。`changemap.PROSE_EXT`（`changemap.py:253`）とはまとめない。PROSE_EXT は yaml・json・toml を含み、差分の枠の都合（`diff -W`）で作った集合なので、まとめると changemap の振る舞いが変わる。新しい集合は作らない。
- **決め 4（パスの無い名前）:** `名前 N 節`・`名前 §N`・`名前 の「見出し」` の名前は、固めた版の追跡ファイルのうち拡張子が DOC_EXT に在り、拡張子を除いた名が名前と等しいか、`-`・`_`・`.` のどれかの後に名前で終わる物に解く。後ろの決まりは、日付を頭に付けた設計書（`2026-09-29-structure-block-design.md`）に届くため。
  - 1 本なら、その文書の名指しにする。
  - 2 本以上なら推測しない。withheld に候補を並べる。
  - 0 本なら名前の名指しと数えない。「N 節」は今どおりパスの無い番号として扱う（`BARE_NUM`）。日本語の地の文の「works の「…」」のような引用で、理由の行が大量に出るのを避けるため。
- **決め 5（見出しの形）:** 見出しの形は 2 つだけで、形式の名前は持たない。前置きの形は、行頭の同じ記号の並びと空白と題。下線の形は、題の行の次の行が 1 種類の記号の 3 文字以上だけでできている形。囲み（記号だけの行が挟む区間）の中は見出しに数えない。並びの列（箇条・表）は隣り合う行が同じ形になるので、隣の行と同じ記号・同じ長さの前置きの行は見出しに数えない。囲みの見分けと列の見分けは、形式に依る推測の決まりとして棚卸しの文書 `works/docs/language-neutral-inventory.md` に 1 項目足す。
- **決め 6（地図）:** 地図は対象のリポジトリの根に追跡されている `ARCHITECTURE.md`・`AGENTS.md` の 2 つだけにする（関所の決め。`docs/` の下や README は読まない）。中身は分類しない（分類の言葉はそれ自体が新しい表になる）。出どころつきで丸ごと貼り、engine の上限 `FILE_CAP`（40000 バイト）を超えたら切って、切った行の範囲を withheld に書く。1 つも無ければ「地図なし」の 1 行を必ず貼る。名の集合は core の `design.MAP_NAMES` に置き、`works/blk-fix/lib/fixrules.py:98` の `PROMPT_NAMES` と `AGENTS.md` が重なることを注記する（core から blk-fix へ依る向きは作らない）。読むのは機械で、役は道具を持たないまま。

## 依頼 239 との重なり（merge の見込み）

- 盤面のファイルの名・置き場・`b.work` の使い方は変えない。地図は今の `design-premises.json` の given・withheld の行として載せる。239 の `works/blk-plan/schemas/design-premises.schema.json` は `node` だけを要るので、行が増えても通る。新しい盤面のファイルも、239 の manifest の宣言の直しも要らない。
- 両方が触るファイルと場所:
  - `works/blk-eyes/lib/eyes.py`: 238 は 85 行の `PREMISE_ASK`、239 は 177 行の `_work`。
  - `works/blk-plan/lib/planblk.py`: 238 は 267 行の `design_only`、239 は 559-583 行の `collect_reads`。
  - `works/.shared/core/report.py`: 238 は 624 行の冒頭 1 の組み立てと、757 行の近くの新しい関数。239 は 65 行の import と 142-180 行。
  - `works/tests/test_report.py`: 238 は `HeadWhereDesignCase`（818 行）、239 は `HeadCase`（532 行）。
  - どれも離れた塊なので、merge は自動で済む見込み。
- 文の衝突が出るのは `works/CHANGELOG.md` の `[Unreleased]` だけ。両方の項目を残して解く。
- `design.py`・`test_blk_eyes.py`・`language-neutral-inventory.md` は 239 が触らない。
- 239 の Task 9（窓ごとの書き込みの照らし）に対して、238 は新しい書き込みを足さない。`design.check_design` は git を読むだけ。

## Global Constraints

- 期限・タイムアウトを新しく足さない（定数・引数・YAML のどれにも）。
- 写しと本流 `graphloops/` は変えない。`COPIED_FROM` に行を足さない。写しの指示書の文は 1 バイトも変えず、読み替えは機械が貼る頭の節（`DESIGN_PREMISE_REREAD`・`eyes.PREMISE_ASK`）で言う。
- 形式ごと・言語ごとの表（拡張子 → 見出しの正規表現のような物）を足さない。
- 独立設計の役に道具を足さない。材料は機械が読んで貼る。kind は `PREMISE_KINDS` の中だけ。
- 盤面のファイルの名と置き場を変えない（依頼 239 とぶつけない）。
- 新しい模块は作らない。試験はどれも `unittest.TestCase` のクラスの中に置く。
- 注記・docstring・拒否の文・貼る文は日本語。Python 3.12 が下限。
- 焦点の試験は `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.<module>.<Class>`。速い段は `works/` から `WORKS_TESTS=fast sh tests/run.sh`。根の柵は `sh ~/.cache/works-dogfood/rootfences.sh`。
- CHANGELOG は `works/CHANGELOG.md` の `[Unreleased]` だけに足す。版は上げない。
- commit のメッセージは日本語で、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。push はしない。

## Review Focus

1. Markdown の区切り線 `---` が節の間に空行つきで並ぶ設計書（この計画の文書そのもの）。囲みに数えて間の見出しを隠すと、名指しの節が「見出しが無い」になる。期待は、`---` を挟んでも `## B` の節が引けること。（Task 1 の `test_thematic_breaks_do_not_hide_headings`）
2. 依頼が `[x](works/.shared/core/design.py#L70)` のようなコードへのリンクと設計書の「3 節」を並べる。期待は、コードを貼らず、パスの無い「3 節」は今どおり 1 本の設計書に結ぶこと。（Task 2 の `test_code_link_is_not_a_named_doc`）
3. `# コメント` の行を含むコードの囲みが `#` 見出しの節の中に在る。期待は、節が囲みの中で切れないこと（今の振る舞い）。（Task 1 の `test_fenced_comment_does_not_end_section`）
4. 名指しの番号「2 節」に、見出し `## 2 上限` と表の行 `| 2 | x |` や箇条 `- 2 つ目` が並ぶ。期待は、列の行を見出しに数えず、決められないの withheld に落とさないこと。（Task 1 の `test_list_and_table_rows_are_not_headings`）
5. 問いが立たない根拠の文に URL（`https://example.com:443/a`）や時刻（`10:15`）だけが在る。期待は、それを名指しと数えて拒まず、「根拠の実物の名指しなし」と出すこと。（Task 4 の `test_url_and_time_are_not_anchors`）

---

### Task 1: 当たった行から見出しの形を読み、節を切る（形式に依らない抜き出し）

**Files:**
- Modify: `works/.shared/core/design.py`
  - 見出しの正規表現の定数 HEADING（75 行）を消す（この Task で消したので、名に括弧の印を付けない）。
  - 新しい関数 `_heads`・`_section_lines`・`_split_target` を足す。
  - `_section`（155-177 行）を差し替え、返りを変える。
  - `named_sections`（180-200 行）を新しい返りに合わせる。
  - `_named_hit`（231-236 行）は `_split_target` を使う。
  - 模块の docstring の named_sections の行（19-22 行）を直す。
- Modify: `works/docs/language-neutral-inventory.md`（節 7 に項目 7-7 を足し、件数の表の 7 の (C) を 7、計の (C) を 8 にする）
- Test: `works/tests/test_blk_eyes.py`（新しい class `SectionShapeCase(unittest.TestCase)`。`PrepCase` に 1 本）

**Interfaces:**
- Consumes: 写しの rules の `_md_slugs(text) -> set[str]`（GitHub の見出しのアンカーの書き方。重複は `-1`・`-2`）、`engine.render.cap_bytes`・`FILE_CAP`
- Produces:
  - `design._heads(lines: list[str]) -> list[dict]`。行ごとに `{"line": int（1 始まり）, "kind": "prefix" | "under", "mark": str（記号 1 文字）, "depth": int, "title": str}`。depth は、前置きの形なら記号の並びの長さ、下線の形なら、その下線の記号が文書の中で下線として初めて現れた順（0 始まり）。
  - `design._section_lines(text: str, *, num: str = "", anchor: str = "", slugs=None) -> tuple[int, int]`。名指しに当たる節の (開始行, 終了行)。1 始まりで両端を含む。引けなければ ValueError（理由の文）。slugs は写しの `_md_slugs`（None なら題の語の包含だけで当てる）。
  - `design._split_target(target: str) -> tuple[str, str, str]`。名指しの文字列 `<path>#<anchor>` か `<path> <N> 節` を (path, anchor, num) に分ける。path の拡張子は問わない。
  - `design._section(b, repo, target) -> tuple[str, str, str]`。返りは (節の本文, 出どころ `<固めた版のパス>:<開始>-<終了>`, 切った範囲 `<パス>:<k>-<終了>` か "")。引けなければ ValueError。
  - 名指しの節の貼り方: 見出しの行は `#### {target}（{出どころ}）`。上限を超えた時の withheld の why は `f"{FILE_CAP} バイトを超えた残り（{切った範囲}）"`。

`_heads` と `_section_lines` の決まり（テストだけでは決まらないので、ここで固める）:
1. 記号の並び: 行頭の空白 3 つまでを除いた後、英数字でも空白でもない同じ文字の 1 文字以上の連なり。記号だけの行は、記号の並び 3 文字以上だけで、残りが空の行。
2. 囲み: 次の 3 つを全部満たす行から始まる区間。
   - 開く行は、3 文字以上の記号の並びに、空か空白を含まない 1 語（```` ```py ```` の言語名）が続く。
   - 開く行は下線でない（直前の行が、空でなく記号だけでもない本文の行なら下線）。
   - 開く行の次の行が空でない。
   - 区間は、後ろで初めて現れる「同じ記号で長さが開く行以上の、記号だけの行」までの全部（両端を含む）。閉じる行が無ければ囲みにしない。
   - 囲みの中の行は見出しに数えない。
3. 前置きの形: 囲みの外で、記号の並びの直後が空白で、その後に空でない題が続く行。題は、末尾の同じ記号の並びと空白を除いた物。前後どちらかの隣の行が同じ記号・同じ長さの前置きの形なら、列（箇条・表）とみなして数えない。
4. 下線の形: 囲みの外で、本文の行（空でなく、記号だけでなく、前置きの形でもない）の次の行が記号だけの行の時。題はその本文の行を strip した物。前置きの形を先に見る。
5. 当てる:
   - num の時は、題から頭の `§` と空白を除いた物が、`第` を任意に頭に置いた num で始まり、その直後が「`.` を任意に挟んで空白か行の終わり」か `節` の時（今の `_section` の番号の当て方と同じ。`2` は `2.1 細目` に当たらない）。
   - anchor の時は、まず slugs で GitHub のアンカーを作って等しい物（各見出しを `# <題>` の行に並べて、今の `_section` と同じ差分の数え方で重複の番号を付ける）。無ければ、題が anchor（URL の符号を解き、大小を問わない）を含む物。
   - 当たりがちょうど 1 つでなければ ValueError。0 個は `"見出しが無い"`、2 個以上は `f"当たる見出しが {n} 個あって決められない（行 {', '.join(行番号)}）"`。
6. 節の終わり: 当たった行の後ろで、初めて現れる見出しの 1 つ前の行（無ければ文書の末尾）。数える見出しは次のどちらか。
   - 当たりが前置きの形なら、同じ記号で depth が当たり以下の前置きの形。
   - 当たりが下線の形なら、同じ記号か、depth が当たりより小さい下線の形。
   - 終了行は、終わりの側の空行を除いた後の最後の行（本文も同じ範囲）。
7. 「英数字」は `str.isalnum()`（漢字・かなも英数字に数える）、「空白」は `str.isspace()` で見る。

- [ ] **Step 1: 落ちる試験を書く**（`works/tests/test_blk_eyes.py`。`PrepCase` の前に置く。`from board import …` の行に `rules_module` を足す）

```python
class SectionShapeCase(unittest.TestCase):
    """名指しの節を、当たった行そのものの形（前置き・下線）で切る。形式の名前も拡張子の表も使わない（依頼 238）"""
    slugs = staticmethod(rules_module()._md_slugs)

    def span(self, text, **kw):
        return design._section_lines(text, slugs=self.slugs, **kw)

    def test_atx_section_runs_to_same_or_shallower_heading(self):
        text = "# 設計書\n\n## 1 目的\n\nA\n\n## 2 上限\n\nB\n\n### 2.1 細目\n\nC\n\n## 3 撤収\n\nD\n"
        self.assertEqual(self.span(text, num="2"), (7, 13))
        self.assertEqual(self.span(text, anchor="2-上限"), (7, 13))

    def test_setext_and_rst_underlines_end_by_first_seen_order(self):
        text = "題\n=====\n\n一\n-----\n\nA\n\n二\n-----\n\nB\n\n次\n=====\n\nC\n"
        self.assertEqual(self.span(text, anchor="一"), (4, 7))
        self.assertEqual(self.span(text, anchor="二"), (9, 12))

    def test_adoc_equals_prefix(self):
        text = "= 文書\n\n== 1 目的\n\nA\n\n== 2 上限\n\nB\n\n=== 2.1 細目\n\nC\n\n== 3 撤収\n\nD\n"
        self.assertEqual(self.span(text, num="2"), (7, 13))

    def test_fenced_comment_does_not_end_section(self):
        text = "# 1 目的\n\n```py\n# コメント\nx = 1\n```\n\nA\n\n# 2 上限\n\nB\n"
        self.assertEqual(self.span(text, num="1"), (1, 8))

    def test_thematic_breaks_do_not_hide_headings(self):
        text = "## A\n\nA\n\n---\n\n## B\n\nB\n\n---\n\n## C\n\nC\n"
        self.assertEqual(self.span(text, anchor="b"), (7, 11))

    def test_list_and_table_rows_are_not_headings(self):
        text = "## 1 目的\n\n- 2 つ目\n- 3 つ目\n\n| 2 | x |\n| 3 | y |\n\n## 2 上限\n\nB\n"
        self.assertEqual(self.span(text, num="2"), (9, 11))

    def test_ambiguous_hit_names_candidate_lines(self):
        text = "## 上限 A\n\nA\n\n## 上限 B\n\nB\n"
        with self.assertRaisesRegex(ValueError, r"2 個あって決められない（行 1, 5）"):
            self.span(text, anchor="上限")

    def test_no_heading_is_value_error(self):
        with self.assertRaisesRegex(ValueError, "見出しが無い"):
            self.span("本文だけ\n", num="1")
```

`PrepCase` に足す 1 本: `test_named_section_over_cap_names_cut_lines`。今の `test_named_section_cap_is_engine_file_cap` と同じ組み方で、節 2 の本文を `"長い本文の行。\n" * 4000`（FILE_CAP を超える）にする。断言は次の 2 つ。
- withheld の 1 行の why が `f"{FILE_CAP} バイトを超えた残り（docs/spec.md:"` で始まる。
- 貼った本文の見出しの行に `（docs/spec.md:` が在る。

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_eyes.SectionShapeCase tests.test_blk_eyes.PrepCase.test_named_section_over_cap_names_cut_lines`
Expected: FAIL。`SectionShapeCase` は `_section_lines` が無い AttributeError。PrepCase の 1 本は why に範囲が無い断言の失敗。

- [ ] **Step 3: `_heads`・`_section_lines`・`_split_target` を足し、`_section`・`named_sections`・`_named_hit` をそれらに載せ替え、定数 HEADING を消す**

`_section` は `_split_target` → `_head_file` → `git show HEAD:<path>` → `_section_lines(text, num=…, anchor=…, slugs=b.rules._md_slugs)` の順で呼ぶ。cut は `cap_bytes` に任せる。切った範囲の開始行 k は、切った後の本文に丸ごと残った行の数の次の行。`_named_hit` は `_split_target` で path・番号を取る（`.md` の決め打ちを外す）。名指しを拾う側（`_named_targets`）は Task 2 で直すので、この Task では `.md` だけが届く。

- [ ] **Step 4: 棚卸しの文書に 7-7 を足す**

`### 7-7 (C) 名指しの節の囲みと列の見分け（design.py）— 変えない` を 7-6 の後に置く。中身は今の 7-x の形で 3 行。
- 場所: `works/.shared/core/design.py` の `_heads`。
- 決め打ち: 記号だけの行の対を囲み、隣り合う同じ前置きの行を列とみなす推測。形式の名前は持たない。
- 判断が要る理由: 区切り線の直後に空行の無い Markdown では、囲みに数えて節を隠しうる。

件数の表も直す。

- [ ] **Step 5: 通ることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_eyes.SectionShapeCase tests.test_blk_eyes.PrepCase tests.test_blk_eyes.PathCase`
Expected: PASS・失敗 0（今の `.md` の名指しの試験も通ったまま）

- [ ] **Step 6: Commit**

```bash
git add works/.shared/core/design.py works/docs/language-neutral-inventory.md works/tests/test_blk_eyes.py
git commit -m "feat(works): 名指しの節を当たった行の形（前置き・下線）で切り、出どころの行の範囲を添える（依頼 238 Task 1）"
```

---

### Task 2: 文書の拡張子なら形式を問わず名指しを拾い、パスの無い名前を追跡ファイルから引く

**Files:**
- Modify: `works/.shared/core/design.py`
  - コードスパンの `.md` の見出しの名指しの定数 CODE_SPAN_MD（70 行。この Task で消した）を `CODE_SPAN_ANCHOR` に置き換え、`CODE_SPAN_NUM`（72 行）の `\.md` を任意の拡張子にする。
  - 新しい定数 `NAME_NUM`・`NAME_QUOTE` と関数 `_is_doc`・`_docs_named` を足す。
  - `_named_targets`（108-136 行）は引数に repo を足し、`named_sections` の呼びを合わせる。
  - `import impact` を足す。
- Test: `works/tests/test_blk_eyes.py`（module の一番外に関数 `commit_file`。`PrepCase._with_named_section` をそれで書き直す。`PrepCase` に 5 本）

**Interfaces:**
- Consumes: Task 1 の `_section`・`_split_target`、`impact.DOC_EXT`、`_head_file`
- Produces:
  - `design._is_doc(path: str) -> bool`。`"://"` を含まず、拡張子（小文字）が `impact.DOC_EXT` に在る時に真。
  - `design._docs_named(repo, name: str) -> list[str]`。固めた版の追跡ファイルのうち、`_is_doc` が真で、拡張子を除いた名が name と等しいか、`-`・`_`・`.` の後に name で終わる物（並べた順）。
  - `design._named_targets(b, text: str, repo) -> tuple[list[str], list[tuple[str, str]]]`。返りの形は今と同じ（名指しの文字列の並び, 結べなかった (元の文字列, 理由) の並び）。
  - `CODE_SPAN_ANCHOR`: `` `<path>.<ext>#<anchor>` ``。`NAME_NUM`: `<名前> N 節`・`<名前> の §N`（名前は英数字で始まる `[\w.-]` の並びで、前が英数字・`/`・`.`・`-` でない）。`NAME_QUOTE`: `<名前> の「<見出し>」`。
  - パスの無い名前を解いた名指しは、解いたパスで今の形（`<path> N 節`・`<path>#<見出し>`）にする。候補が 2 本以上の時の withheld の why は `f"名の一致する追跡の文書が {n} 本あって決められない（候補: {', '.join(候補)}）"`。
  - パスの無い番号を結べない時の why は `"結び付けられる形の設計書の名指しが依頼に無い（リンク・`<path>#<見出し>`・`<path>` N 節・<名前> N 節 の形だけを数える）"`。
- `commit_file(repo, rel: str, text: str) -> None`（試験の手助け）。ファイルを書いて add と commit をする。

- [ ] **Step 1: 落ちる試験を書く**（`PrepCase`。どれも `self.board("r1r2", made=None)` の後に `commit_file` で文書を置き、盤面の依頼の文を差し替え、`design.named_sections(entry.open_board(self.bd), self.repo)` の (text, given, withheld) を見る）

- `test_adoc_link_section_is_given`: `docs/spec.adoc` に Task 1 の `test_adoc_equals_prefix` と同じ本文（節 2 の本文を `ADOC-2-BODY`）を置き、依頼は `[上限](docs/spec.adoc#上限) のとおり`。断言は次の 3 つ。
  - text に `ADOC-2-BODY` が在る。
  - given の what が `["docs/spec.adoc#上限"]`。
  - withheld が `[]`。
- `test_pathless_name_resolves_dated_spec`: `docs/specs/2026-09-29-structure-block-design.md` に `## 7 隔て\n\nSEVEN-BODY\n\n## 8 次\n\nX\n` を置き、依頼は `structure-block-design 7 節 を崩さない`。断言は次の 2 つ。
  - text に `SEVEN-BODY` が在る。
  - given の what が `["docs/specs/2026-09-29-structure-block-design.md 7 節"]`。
- `test_pathless_name_with_two_candidates_is_withheld`: `a/notes.md` と `b/notes.adoc` の両方に `## 1 x` を置き、依頼は `notes 1 節`。断言は次の 2 つ。
  - given が `[]`。
  - withheld がちょうど 1 行で、その why が「2 本あって決められない」と両方のパスを含む。
- `test_pathless_name_without_candidates_falls_back_to_bare_number`: 依頼は `[docs/spec.md の 2 節](docs/spec.md#2-上限) と nothing-here 3 節`（`_with_named_section` の SPEC）。断言は次の 2 つ。
  - given の what に `docs/spec.md 3 節` が在る。
  - withheld が `[]`（名前を数えず、今どおり 1 本の設計書に結ぶ）。
- `test_code_link_is_not_a_named_doc`: 依頼は `` [x](works/.shared/core/design.py#L70) と `docs/spec.md` 2 節、§3 も ``（`_with_named_section` の SPEC）。断言は次の 3 つ。
  - text に `design.py` の中身（`def premises`）が無い。
  - given の what が `["docs/spec.md 2 節", "docs/spec.md 3 節"]`。
  - withheld が `[]`。

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_eyes.PrepCase`
Expected: 新しい 5 本のうち、`test_adoc_link_section_is_given`・`test_pathless_name_resolves_dated_spec`・`test_pathless_name_with_two_candidates_is_withheld` が FAIL（今は `.md` しか拾わず、名前を引かない）。後の 2 本は今も PASS（守りの試験）。今の試験は PASS。

- [ ] **Step 3: `_is_doc`・`_docs_named`・新しい正規表現を足し、`_named_targets` を直す**

拾う順は次のとおり。
1. リンクとコードスパンの `#` つき（`_is_doc` のパスだけ）。
2. `CODE_SPAN_NUM`（`_is_doc` のパスだけ）。
3. リンクと `CODE_SPAN_NUM` の当たりを除いた文の `NAME_NUM`・`NAME_QUOTE`（`_docs_named` が 1 本以上の物だけ。0 本は拾わない）。
4. 残りの文（リンク・`CODE_SPAN_NUM`・候補が 1 本以上の名前の当たりを除いた文）の `BARE_NUM`。

docs の本数（パスの無い番号を結ぶ相手）には、1〜3 で数えた設計書のパスを重ねずに数える。名前の候補が 2 本以上の物は docs に数えない（withheld の 1 行だけにし、`BARE_NUM` にも回さない）。模块の docstring の named_sections の行も、拾う形に合わせて直す。

- [ ] **Step 4: 通ることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_eyes.SectionShapeCase tests.test_blk_eyes.PrepCase tests.test_blk_eyes.PathCase`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/design.py works/tests/test_blk_eyes.py
git commit -m "feat(works): 文書の拡張子なら形式を問わず名指しを拾い、パスの無い名前を追跡ファイルの名から引く。コードへのリンクは数えない（依頼 238 Task 2）"
```

---

### Task 3: 対象のリポジトリの地図（kind repo_map）を独立設計と突き合わせにいつも貼る

**Files:**
- Modify: `works/.shared/core/design.py`
  - 定数 `MAP_NAMES`・`MAP_HEAD`・`MAP_ASK` と関数 `repo_map` を足す。
  - `PREMISE_KINDS`（85 行）に `"repo_map"` を足す。
  - `premises`（203-213 行）が地図の節を 3 つ目に並べる。
  - `CLAIM_WORDS`（80 行）と `claims_given`（223-228 行）を直す。
  - `DESIGN_PREMISE_REREAD`（66 行）の括弧に「・対象のリポジトリの地図」を足す。
  - 模块の docstring の premises の行（17 行）を直す。
- Modify: `works/blk-eyes/lib/eyes.py`（`PREMISE_ASK`（85 行）の「依頼が名指した設計書の節」の後に「・対象のリポジトリの地図」を足す）
- Test: `works/tests/test_blk_eyes.py`（`PrepCase` に 4 本。今の `test_design_prompt_is_built_only_from_allowed_kinds_without_structure_outputs` の kinds の集合に `"repo_map"` を足す。`PathCase` に 1 本）

**Interfaces:**
- Consumes: Task 2 の `commit_file`、`cap_bytes`・`FILE_CAP`
- Produces:
  - `design.MAP_NAMES = ("ARCHITECTURE.md", "AGENTS.md")`。注記で `fixrules.PROMPT_NAMES` との重なりを言う。
  - `design.MAP_HEAD = "### 対象のリポジトリの地図"`。
  - `design.MAP_ASK` = 「対象のリポジトリの根に在る地図の文書（依頼を固めた版のファイルから機械が貼った。見出しの括弧は出どころのパス:行）。依頼が名指していなくても、仕組みの中に既に在る実物（信用の起点・外との通信の経路・守る物）から設計を始めよ。」
  - `design.repo_map(repo) -> tuple[str, list[dict], list[dict]]`。返りは (節の本文, given, withheld)。本文は空にならない。
    - 在るファイルは `#### {名}:{1}-{行数}` の見出しの下に本文を貼り、given に `{"kind": "repo_map", "what": "<名>:1-<行数>"}`。
    - 上限で切ったら withheld に `{"kind": "repo_map", "what": 名, "why": f"{FILE_CAP} バイトを超えた残り（{名}:{k}-{行数}）"}`。
    - 1 つも無ければ、本文に `- 地図なし: 根の ARCHITECTURE.md・AGENTS.md は固めた版に無い` の 1 行。withheld に `{"kind": "repo_map", "what": "ARCHITECTURE.md・AGENTS.md", "why": "対象のリポジトリの根に追跡されていない"}`。
    - 根のパスだけを読む（`_head_file` の末尾の一致は使わない。`docs/AGENTS.md` は読まない）。
  - `premises(b, repo)` の節の並びは 人の答え → 名指しの節 → 地図。
  - `claims_given`: kind `repo_map` の行は、文が「地図」か what のパスの部分（`:` の前）を含めば当たる。

- [ ] **Step 1: 落ちる試験を書く**
  - `test_design_prompt_carries_repo_map`: `commit_file(self.repo, "ARCHITECTURE.md", "# 全体\n\nMAP-BODY 信用の起点は署名\n")`。`design.prep` の prompt を見る。断言は次の 4 つ。
    - `MAP-BODY` が在る。
    - `ARCHITECTURE.md:1-3` が在る。
    - `design.MAP_HEAD` が在る。
    - 控え `design-premises.json` の given に `{"kind": "repo_map", "what": "ARCHITECTURE.md:1-3"}` が在る。
  - `test_compare_prompt_carries_repo_map`: 同じ置き方で `self.board("r1r2")`・`self.enter()`・`eyes.prep(self.bd, "r2-compare", self.rnd, self.repo)` の prompt に `MAP-BODY` が在る。
  - `test_no_map_is_named_not_silent`: 文書を置かずに `design.repo_map(self.repo)` を見る。断言は次の 3 つ。
    - text に `地図なし` が在る。
    - given が `[]`。
    - withheld が `[{"kind": "repo_map", "what": "ARCHITECTURE.md・AGENTS.md", "why": "対象のリポジトリの根に追跡されていない"}]`。
  - `test_map_only_from_root`: `commit_file(self.repo, "docs/AGENTS.md", "SUBDIR-MAP\n")`。`repo_map` の text に `SUBDIR-MAP` が無く、`地図なし` が在る。
  - `PathCase` に `test_unpassed_map_claim_matches_repo_map`: `design.claims_given(["地図が渡されていない"], [{"kind": "repo_map", "what": "ARCHITECTURE.md:1-3"}])` が 1 行を返す。

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_eyes.PrepCase tests.test_blk_eyes.PathCase`
Expected: 新しい 5 本が FAIL（`repo_map` が無い・地図が貼られない）。kinds の集合を直した試験も FAIL。

- [ ] **Step 3: `repo_map` を足し、`premises`・`PREMISE_KINDS`・`CLAIM_WORDS`・`claims_given`・`DESIGN_PREMISE_REREAD`・`eyes.PREMISE_ASK` を直す**

`premises` の柵（kind が一覧の外なら BoardGap）は今のまま通す。

- [ ] **Step 4: 通ることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_eyes`
Expected: PASS・失敗 0。今の試験で、控えの withheld を等式で縛っていた物が地図なしの行で落ちたら、その行を期待に足す（落としてよい行は無い）。

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/design.py works/blk-eyes/lib/eyes.py works/tests/test_blk_eyes.py
git commit -m "feat(works): 対象のリポジトリの根の ARCHITECTURE.md・AGENTS.md を地図（kind repo_map）として独立設計と突き合わせにいつも貼り、無ければ地図なしと名指す（依頼 238 Task 3）"
```

---

### Task 4: 問いが立たない根拠のパス:行を検算し、無ければ「根拠の実物の名指しなし」と名指す

**Files:**
- Modify: `works/.shared/core/design.py`
  - 定数 `ANCHOR`・`UNANCHORED`・`PREMISE_MISS` と、関数 `anchors`・`anchor_misses`・`anchor_note` を足す。
  - `check_design`（318-327 行）に検算を足す。
- Modify: `works/blk-plan/lib/planblk.py`（`design_only` の 267-268 行）
- Modify: `works/.shared/core/report.py`
  - 新しい関数 `_design_unanchored` を `_premise_hypotheses`（757 行）の後に置く。
  - 冒頭 1 の組み立て（624 行の後）に `lines += _design_unanchored(b)` を足す。
- Test:
  - `works/tests/test_blk_eyes.py`（`AcceptCase` に 4 本。`SectionShapeCase` の後に新しい class `AnchorCase(unittest.TestCase)` を置き、2 本）
  - `works/tests/test_blk_plan.py`（`test_design_not_stands_is_not_a_face` の断言 1 行）
  - `works/tests/test_report.py`（`HeadWhereDesignCase` に 2 本）

**Interfaces:**
- Consumes: `_head_file`、Task 2 の `commit_file`
- Produces:
  - `design.anchors(text: str) -> list[tuple[str, int, int]]`。文の中の `パス:行` と `パス:開始-終了` を (パス, 開始, 終了) で、出た順に返す。`パス:行` は開始と終了が同じ。パスは拡張子つきで、`/` 区切りの段を持ってよい。前が英数字・`/`・`.`・`:`・`-` の当たりは拾わない（URL の `host:port` を外す）。
  - `design.anchor_misses(text: str, repo) -> list[str]`。当たらない名指しごとに `"<パス>:<開始>[-<終了>]（<理由>）"` の文を返す（パスと行は文の字のまま）。理由は `_head_file` の ValueError の文か、`f"行の範囲の外（ファイルは {n} 行）"`。
  - `design.UNANCHORED = "根拠の実物の名指しなし"`。
  - `design.anchor_note(text: str) -> str`。`anchors(text)` が空なら `f"（{UNANCHORED}）"`、在れば ""。
  - `design.PREMISE_MISS = "premise_invalid_reason の名指しが固めた版の実物に当たらない（追跡されたファイルと、その行の範囲を名指せ）: "`。
  - `check_design`: 型の確かめの後、`reply["question_stands"]` が偽なら、`anchor_misses(reply.get("premise_invalid_reason") or reply["reason"], repo)` が空でない時に `Reject(PREMISE_MISS + "・".join(misses))`。真の時と、名指しが無い時は今どおり通す。
  - `planblk.design_only`: 問いが立たない時の reason を `r + design.anchor_note(r)` にする（r は今の `got.get("premise_invalid_reason") or got["reason"]`）。
  - `report._design_unanchored(b) -> list[str]`。`design.made(b.dir)` の控えが在り、`question_stands` が偽で `anchor_note` が空でない時だけ、1 行を返す: `f"独立設計は問いが立たないと返したが、{design.UNANCHORED}（{_one_line(r)}）"`。ほかは `[]`。

- [ ] **Step 1: 落ちる試験を書く**

`AnchorCase`（盤面なし）:

```python
class AnchorCase(unittest.TestCase):
    """問いが立たない根拠の名指し（パス:行）の拾い方（依頼 238）"""

    def test_path_line_and_range_are_anchors(self):
        self.assertEqual(design.anchors("design.py:70 と works/.shared/core/design.py:70-75 を見よ"),
                         [("design.py", 70, 70), ("works/.shared/core/design.py", 70, 75)])

    def test_url_and_time_are_not_anchors(self):
        self.assertEqual(design.anchors("https://example.com:443/a の応答の時刻 10:15 を使う"), [])
        self.assertEqual(design.anchor_note("https://example.com:443/a"), f"（{design.UNANCHORED}）")
```

`AcceptCase` の 4 本。どれも `self.board("r1r2", made=None)`・`commit_file(self.repo, "docs/spec.md", "一\n二\n三\n")`・`entry.snapshot(pathlib.Path(self.bd), design.SNAPSHOT_NAME, pathlib.Path(self.repo))` の後に、`design.accept_reply(self.bd, json.dumps(返答, ensure_ascii=False), self.repo)` を見る。返答は `{**DESIGN_INVALID, "premise_invalid_reason": <文>}`。
- `test_premise_anchor_in_range_is_accepted`: 文は `"docs/spec.md:2-3 に既に在る"`。断言は `ok` が真。
- `test_premise_anchor_out_of_range_is_rejected`: 文は `"docs/spec.md:9 に既に在る"`。断言は次の 2 つ。
  - `ok` が偽。
  - reason に `design.PREMISE_MISS` と `docs/spec.md:9（行の範囲の外（ファイルは 3 行））` が在る。
- `test_premise_anchor_untracked_is_rejected`: 文は `"nowhere.md:1 に在る"`。断言は次の 2 つ。
  - `ok` が偽。
  - reason に `固めた版にファイルが無い` が在る。
- `test_premise_without_anchor_is_accepted`: `DESIGN_INVALID` のまま。断言は `ok` が真（拒まない）。

`test_blk_plan.py` の `test_design_not_stands_is_not_a_face`: 断言を `DESIGN_NOT_STANDS.format(reason="識別子は既にある（根拠の実物の名指しなし）")` に替える。

`test_report.py` の `HeadWhereDesignCase` の 2 本。`self.board(tmp)` の盤面で、`tmp / "design.json"` に返答の JSON を書いて `report._design_unanchored(b)` を見る。
- `test_unanchored_premise_is_named`: `{"question_stands": False, "reason": "立たない", "premise_invalid_reason": "識別子は既にある", "design": ""}`。断言は 1 行で、`根拠の実物の名指しなし` と `識別子は既にある` を含む。
- `test_anchored_or_standing_design_adds_nothing`: 2 つの返答を見る。断言はどちらも `[]`。
  - premise_invalid_reason が `"docs/spec.md:2 に在る"` の返答。
  - `question_stands` が真の返答。

- [ ] **Step 2: 落ちることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_eyes.AnchorCase tests.test_blk_eyes.AcceptCase tests.test_report.HeadWhereDesignCase tests.test_blk_plan`
Expected: FAIL。`AnchorCase` と report の 2 本は関数が無い AttributeError。範囲の外・未追跡の 2 本は `ok` が真の断言の失敗。test_blk_plan の 1 本は注記が無い失敗。範囲の中と名指しなしの 2 本は今も PASS（守りの試験）。

- [ ] **Step 3: `anchors`・`anchor_misses`・`anchor_note` と定数を足し、`check_design`・`planblk.design_only`・`report` を直す**

`anchor_misses` の行数は `git show HEAD:<解いたパス>` の `splitlines()` の数で数える。開始が 1 以上、開始が終了以下、終了が行数以下なら当たり。

- [ ] **Step 4: 通ることを確かめる**

Run: `works/` から `PYTHONDONTWRITEBYTECODE=1 WORKS_TESTSLOT= python3 -m unittest tests.test_blk_eyes tests.test_blk_plan tests.test_report`
Expected: PASS・失敗 0

- [ ] **Step 5: Commit**

```bash
git add works/.shared/core/design.py works/blk-plan/lib/planblk.py works/.shared/core/report.py works/tests/test_blk_eyes.py works/tests/test_blk_plan.py works/tests/test_report.py
git commit -m "feat(works): 独立設計が問いは立たないと返した根拠のパス:行を固めた版で検算し、名指しが無ければ事前審査と報告に「根拠の実物の名指しなし」と出す（依頼 238 Task 4）"
```

---

### Task 5: CHANGELOG と仕上げ（速い段・根の柵）

**Files:**
- Modify: `works/CHANGELOG.md`（`[Unreleased]` に `### Added` と `### Changed`）

**Interfaces:**
- Consumes: Task 1〜4 の全部
- Produces: CHANGELOG の 3 項目（下書き。字は整えてよいが、中身は落とさない）
  - Added: 「独立設計（r2.design）と突き合わせ（r2.compare）に、対象のリポジトリの根に追跡されている `ARCHITECTURE.md`・`AGENTS.md` を地図として毎回貼る（出どころのパス:行つき。上限を超えた残りは行の範囲で名指す）。無ければ『地図なし』と貼り、渡した物の控えにも理由を残す。」
  - Changed: 「依頼が名指した設計書の節を、`.md` の `#` 見出しに限らず、当たった行の形（行頭の記号の並び・次の行の下線）で切る（AsciiDoc の `=`・reStructuredText の下線・Markdown の setext も引ける）。名指しはリンクとコードスパンの文書の拡張子のパス全般と、パスの無い `<名前> N 節`・`<名前> の「見出し」`（追跡ファイルの名で引く）を拾う。コードへのリンクは設計書に数えない。貼る節に出どころのパス:行を添える。」
  - Changed: 「独立設計が問いは立たないと返した時、`premise_invalid_reason` の中のパス:行が固めた版の追跡ファイルの行の範囲に当たらなければ受け付けで拒む。名指しが無い時は拒まず、事前審査の指示書と報告の冒頭 1 に『根拠の実物の名指しなし』と出す。」

- [ ] **Step 1: CHANGELOG に上の 3 項目を足す**

- [ ] **Step 2: 速い段と根の柵を 1 度だけ通す**

Run:
1. `works/` から `WORKS_TESTS=fast sh tests/run.sh`
2. `sh ~/.cache/works-dogfood/rootfences.sh`

Expected:
- どちらも失敗 0。
- `grep -n "CODE_SPAN_MD\|^HEADING" works/.shared/core/design.py` が何も出さない。
- `git diff f0ae265e -- works/.shared/core/graphloops works/.shared/core/gl-prompts works/.shared/core/COPIED_FROM` が空。

- [ ] **Step 3: Commit**

```bash
git add works/CHANGELOG.md
git commit -m "docs(works): 依頼 238 の CHANGELOG（独立設計の材料・地図・問いが立たない根拠の検算）"
```

---

## この計画が扱わない物

- 事前審査・差分の審査・R1/R3/R4 に、問いの立て直しを返す口を広げること。R1/R3/R4 の返答の型は写しの graph の schema で変えられず、関所は R2 の口を残す案を選んだ。広げるなら、works の物である事前審査と差分の審査の返答の欄から、別の依頼として `next-request.json` に回す。
- 地図を `docs/` の下や README・CLAUDE.md・SECURITY.md に広げること（Spec の独立設計は 6 つの名を挙げたが、関所が根の 2 つに絞った）。
- `changemap.py:161` の `OUTLINE_PATTERNS`（拡張子ごとの見出しの型の表）を Task 1 の形の読み取りにまとめること。効くが今回の目的の外。
- `changemap.PROSE_EXT` と `impact.DOC_EXT` を 1 つにまとめること（決め 3）。
- 問いが立たない根拠を、渡した材料か実測した制約に現れるパスと行に限ること（Spec の独立設計 4 節）。関所の決めは「追跡ファイルと行の範囲に当たるか」だけ。
