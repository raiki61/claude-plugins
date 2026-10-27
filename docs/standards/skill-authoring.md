# スキルの書き方の標準（本文の長さ・別ファイルへの分け方・description）

スキル（`skills/<名前>/SKILL.md`）とコマンド（`commands/<名前>.md`）の本文をどれだけの長さにし、詳しい手順をどう別ファイルに分け、`description` をどう書くか。
今のずれ: 2026-10-18 に、17 本のうち 11 本が当時の決まり 1 の上限（本文 5,000 字）を超えていて、各プラグインの担当が分けた（どれをどこへ頼んだかは [README](README.md) の「ずれの台帳」の 2 回目）。字数の上限は 2026-10-27 に外した（決まり 1）。これから書く・直す人は、自分のスキルをこの標準に合わせる。
読むのは、スキルやコマンドを新しく書く・直すエージェントと人（直す前に読む）と、この標準を機械で守らせる検査を書く点検（CI とルートの `tests/` を受け持つ部署）。

Claude Code ではコマンドとスキルは同じ物として動く（[Extend Claude with skills](https://code.claude.com/docs/en/skills)「Custom commands have been merged into skills.」）。違いはスキルが別ファイルを置くフォルダを持つことだけなので、この標準は両方に当てる。以下「スキル」は両方を指す。
対象は、marketplace に載るプラグインのルートの `skills/*/SKILL.md` と `commands/*.md`。[README](README.md) の 6 つのプラグインに加え、works と works-factory も含む（このリポジトリの持ち主が 2026-10-18 に頼んだ。my_notes の社長室の受付 20261018-001029-21a565）。プラグインのルートより深い所の物（works の `.shared/borrow/` に写した第三者のスキルや、`blk-*/commands/` の工場の指示書）は Claude Code のスキルとして読み込まれないので対象の外。

## なぜ要るか

スキルの読み込みは 3 段で進む。`name` と `description` は会話の始まりから常に載り、本文は呼ばれたときに丸ごと読まれ、同梱の別ファイルは本文の案内で要るときにだけ読まれる（[Agent Skills の概要](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)。メタデータは約 100 トークン、本文は 5k トークン未満、別ファイルは読むまで費用なし）。

Claude Code では、読み込まれた本文は会話に残り続け、1 行ごとに毎回の費用になる。会話が自動で圧縮されると、各スキルの最新の呼び出しの**頭の 5,000 トークンだけ**が付け直される（[Extend Claude with skills](https://code.claude.com/docs/en/skills)「keeping the first 5,000 tokens of each」。付け直す全部のスキルで合わせて 25,000 トークンまで）。
本文が 5,000 トークンを超えるスキルは、圧縮の後に後ろの手順を失ったまま動く。2026-10-18 に測ると、works-dispatch の dispatch は本文が約 45,000 トークンあり、圧縮の後は頭の 1 割ほどしか残らない。この標準は、これを字数の上限でなく、本文の並べ方（決まり 2）と分け方（決まり 3）で防ぐ（決まり 1）。

## 決まり

1. **本文（frontmatter の後ろ）は 500 行未満にする。字数（トークン）の上限は置かない。**
   - 500 行は公式の 4 つの文書が揃う数（[Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)「Keep SKILL.md body under 500 lines」ほか）。
   - 字数の上限は持ち主の決めで外した（2026-10-27、受付 20261027-042859-0ad720。持ち主の言葉「myturn とかのスキルプロンプトトークンに上限があるなら撤廃していい」）。2026-10-18 から 10-27 までは 5,000 字以下を上限にしていた（圧縮の後に付け直す頭の 5,000 トークンに収める。日本語は 1 字あたり 0.77〜0.87 トークンと測った）が、毎回の呼び出しで要る手順がそれより長いスキル（attention の my-turn の直しで 5,381 字）を、分けて遠くするか削るかしかなくなった。
   - 上限を外しても、圧縮の後に頭の 5,000 トークンしか残らない事実は変わらない（上の「なぜ要るか」）。これは数で縛らず、決まり 2 の並べ方（後ろが落ちても動ける順）と決まり 3 の分け方（一緒に使わない場面を別ファイルへ）で防ぐ。
2. **本文に残すのは、毎回の呼び出しで要る物だけにする。** 何をするスキルか・起動の 1 行・どの別ファイルをいつ読むかの案内・落とし穴（踏むと壊れる所）。いちばん大事な指示と落とし穴は本文の頭の近くに置き、頭から、毎回の呼び出しで要る順に並べる（圧縮の後は頭しか残らないので、後ろが落ちても、残った頭だけで手順を踏み外さないようにする。[Extend Claude with skills](https://code.claude.com/docs/en/skills)。落とし穴を別ファイルに出すと、エージェントが読むきっかけに気づかないことがある。[agentskills.io の Best practices](https://agentskills.io/skill-creation/best-practices)）。
3. **詳しい手順と資料は、主題ごとの別ファイルに分ける。** 置き場は `skills/<名前>/references/<主題>.md`（スクリプトは `scripts/`）。分ける単位は「一緒に使わない場面」（例: 初めての設定・部署を立てる・main に入れる・片付け）で、1 つの呼び出しで読む別ファイルが 1〜2 本で済むようにする。同じ事を本文と別ファイルの両方に書かない（片方だけ直して食い違う）。
4. **別ファイルは本文から 1 段で指し、何が入っていていつ読むかを添える。** 例: 「`--land` で止まったら [references/land.md](references/land.md)（止まる訳ごとの直し方）を読む」。ただ「詳しくは references/ を見よ」とは書かない（[agentskills.io の Best practices](https://agentskills.io/skill-creation/best-practices)）。別ファイルから更に別ファイルを指さない（指された先は頭だけ読まれることがある。[Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)）。
   - 読ませる別ファイルは、本文から相対パスの Markdown のリンクで指す（上の例の形）。走らせるコマンドの中でパスを書くときは、スキルのフォルダの中の物を `${CLAUDE_SKILL_DIR}`（その `SKILL.md` の在るフォルダ）で、プラグインのほかの所の物（`hooks/` など）を `${CLAUDE_PLUGIN_ROOT}` で指す（[Extend Claude with skills](https://code.claude.com/docs/en/skills) の置き換えの表）。
   - 別ファイルの中から `scripts/` のスクリプトを走らせるのはよい（読まずに走らせる物なので、頭だけ読まれる心配が無い）。指さないのは、読ませる別ファイルから、更に読ませる別ファイルへの連なり。
5. **100 行を超える別ファイルは、頭に目次を置く。** 目次は、ファイルの頭の 20 行以内に置いた、そのファイルの見出し（`##`）を並べた箇条書き。公式の閾値は 100 行（Claude Platform の指針）と 300 行（skill-creator）で割れる（[二次のノート](https://github.com/raiki61/my_notes/blob/master/reference/secondary/ai/skill-authoring-guides-agree-on-three-stage-loading-and-splitting-body-split-on-length-unit-and-description-voice.md)の「別ファイルへの分け方と指し方」）。この標準は 100 行を採る。理由が書かれているのは 100 行の方で（頭だけ読まれても全体が分かるように。[Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)）、日本語の行は長いので短い方に合わせても困らない。
6. **`commands/` のコマンドを別ファイルに分ける（決まり 3）なら、分けるときに `skills/<同じ名前>/SKILL.md` へ移す。** コマンドのファイルは別ファイルを置くフォルダを持たない。スキルにしても呼び出しの名前は変わらない（[Extend Claude with skills](https://code.claude.com/docs/en/skills)「both create `/deploy` and work the same way」）。分けないコマンドは移さない（[配る形の標準](plugin-manifest.md)の決まり 5「今 `commands/` に在る物は移さない」）。
7. **`description` には、何をするかと、いつ使うか（言われる言い回し）の両方を書き、1,024 字以下にする。** 1,024 字は仕様の上限（[agentskills.io の Specification](https://agentskills.io/specification)）で、目指す長さではない。description は会話の始まりから常に載るので、短いほど毎回の費用が減る。主な使いどころを先に書く（Claude Code はスキルの一覧で説明を切ることがあり、公式は大事な使いどころを先に置くよう勧める「Put the key use case first」。[Extend Claude with skills](https://code.claude.com/docs/en/skills)）。
   - 人称は公式で割れる（三人称か、「Use this skill when…」で始める形か）。日本語の文は人称を持たないので、「〜する。〜と言われたときに使う。」の形（今のスキルとコマンドの多くが取る形）を標準にする。三人称を勧める側の理由（システムプロンプトに差し込まれるので視点を揃える。[Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)）と、「Use this skill when…」の形を勧める側の理由（いつ動くかを告げる。[agentskills.io の Optimizing descriptions](https://agentskills.io/skill-creation/optimizing-descriptions)）を、どちらもこの形で満たす。
8. **分ける・削るときは、元の振る舞いを確かめてから入れる。確かめは機械の照合を先にし、スキルを走らせる試しは、1 本の分割につき、前の版と分けた版の 1 対（1 回ずつ）までにする。** 公式の評価は「スキル有りと無し（直すときは前の版）を比べる」で揃い、作る時期だけが割れる（[二次のノート](https://github.com/raiki61/my_notes/blob/master/reference/secondary/ai/skill-authoring-guides-agree-on-three-stage-loading-and-splitting-body-split-on-length-unit-and-description-voice.md)の「評価と反復」）。この標準で多いのは今あるスキルを分ける直しなので、前の版を基準にする。直す人は次の順で比べる。
   1. 機械で照合する。前の版の本文の行が、分けた版の本文か別ファイルのどこかに残っているか（下の「守らせ方」の一行で照合できる。消した・書き替えた行は、訳を添えて一覧にする）と、本文から指した別ファイルが在るか（決まり 4 の検査で見る）。費用が掛からず、何度でも同じ答えが出る。公式の評価の指針も、照合できる所はコードで決まった答えを出す採点を選ぶよう勧める（[Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)「We recommend choosing deterministic graders where possible」）。
   2. 走らせて比べるのは、機械で照合できない所だけにする: 要る別ファイルを読みに行くか、最初に打つコマンドと最初に止まる所（持ち主に問う・ゲートで待つ）が前の版と同じか。本文から別ファイルへ出した場面（決まり 3）のうち、分けたことで振る舞いが変わりやすい 1 つ（最初に読む別ファイルが変わる場面など）を選び、その場面に当たる頼みを 1 つ選んで、新しい会話（書いた会話の文脈が残ると、書き漏れが隠れる。[Extend Claude with skills](https://code.claude.com/docs/en/skills)「A fresh session matters」）で前の版と分けた版に 1 回ずつ頼む。言い回しの揺れは見ない。ほかの場面も走らせたいときは、走らせる前に、見込みの額（1 回の `--max-budget-usd` の額 × 回数）を添えて社長室（my_notes の、持ち主への中継の部署）に問う（問い方はルートの CLAUDE.md の「判断の線」の試しの項。1 対に絞るのは持ち主の承認で、my_notes の社長室の受付 d543d2）。起動方法（一時の worktree・フックを切る・走らせるアカウントの選び方）はルートの CLAUDE.md の「判断の線」の試しの項と「手元の操作」の試しの `claude -p` の行に従う。
      - 試しを止めるのに第一に頼るのは、頼みの文に書く目安（何をしたら止まるか・どこまでで足りるか）である。頼みは最後までやらせず、「最初に読むファイル・最初に打つコマンド・最初に人に問う所か待つ所を書いたら、コマンドは打たずに止まって」のように、最初の手が見えたら終わる頼み方にする。範囲の決まらない頼みは長く回る（[Agent SDK の agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop)「fine for well-scoped tasks but can run long on open-ended prompts」）。中でサブエージェントを立てるスキル（見直しのループなど）を最後まで走らせると、1 回で数十ドルになる（2026-10-18 に、6 本の分割の確かめで 27 回走らせ、1 回で 38 ドルの回があった）。
      - `--max-budget-usd` は、目安が外れたときの歯止めとして付ける。上限の額は、ふつうの試しでは当たらない 1 ドルにする（最初の手で止める頼みは、2026-10-18 に 2 ターン・0.21 ドルだった）。使った額は上限を越えることがあるので余裕を残す（[CLI reference](https://code.claude.com/docs/en/cli-reference)「Spend can pass the cap, so leave headroom.」）。人が見ていない走りに額の上限を置くのは、Anthropic の勧める形である（[Session budgets](https://platform.claude.com/docs/en/managed-agents/budgets)「Reach for it whenever a session runs without a human watching」）。`--max-turns` はターンの数を止めるだけで額は止めない（2026-10-18 に 7 ターンで 38 ドルの回があった）。`--max-budget-usd` はサブエージェントの分も数える（[CLI reference](https://code.claude.com/docs/en/cli-reference)「Spend from subagents counts toward the cap.」）。
      - 結果は `--output-format json` でファイルに残す（`stream-json` なら最後の行が結果）。上限に当たると `claude -p` は 0 以外で終わり、結果の `subtype` が `error_max_budget_usd` になり、`session_id` が残る（[Agent SDK の agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop)「carry total_cost_usd, usage, num_turns, and session_id so you can track cost and resume even after errors」）。使った額は戻らないが、会話はそこまで残っている。
      - 上限で止まった回は、捨てて最初から走らせ直さない（前の回の額が無駄になり、1 対の数も越える）。まず出力を読み、目安で見ようとした物（最初に読むファイル・最初に打つコマンド・最初に止まる所）がもう出ていれば、それで足りるので続けない。出ていなければ、同じ回を続きから再開する: 会話の記録は起動した場所とアカウントごとに残るので、同じ作業場（一時の worktree を読み終えるまで消さない）・同じアカウント（元の回と同じ `CLAUDE_CONFIG_DIR` と認証のトークン）で、元の回と同じフラグ（`--settings '{"disableAllHooks":true}'` など）に `--resume <session_id> --max-budget-usd 1` を足し、目安を言い直した頼み（例: 「ここで止まって、最初に読むファイルと最初に打つコマンドを書いて」）を渡す。再開した回では、前の回の分は新しい上限に数えない（[CLI reference](https://code.claude.com/docs/en/cli-reference)「totals restored from earlier runs don’t count toward it」）。2026-10-18 に、上限で止まった回を `--resume` で続け、続きから終わるのを確かめた（上限に当たった時に途中だったツールの結果は残らず、続けた回が読み直した）。続けた分は同じ 1 回に数える。続けた回も上限に当たったら、もう続けず、頼みの文の目安が効かなかったことを、直しの納品の残った疑問に書く。
      - 回数を足して確かさを買わない。エージェントの振る舞いは回ごとに揺れる（[Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)「agent behavior varies between runs」）。前と後を数回ずつ走らせても、違いが分けたことによるのか揺れなのかは分けられない。確かさは 1 の機械の照合で持つ。
      - 前と後で違いが出たら、走らせ直さず、違った所に当たる本文と別ファイルを読み、分けたことで消えた・遠くなった指示が無いかを照合する。
   3. 試した頼みと手順 1・2 の結果は、直しの納品か commit の本文に書く。

## 守らせ方

決まり 1（行数）と決まり 4・5（指した別ファイルが在るか、100 行を超える別ファイルに目次が有るか）は、ルートの `tests/run.sh` が呼ぶ `tests/skill-body-case.py` で見る（[README](README.md) の台帳の 2-1）。今満たさないスキルは検査の中の外す一覧に載せて緑で始め、満たしたら一覧から消す。決まり 2・3・6・7・8 と、決まり 4 のうち「別ファイルから更に別ファイルを指さない」は、書いた人と見直しの目が見る。決まり 8 のうち `claude -p` に `--max-budget-usd` を付けることも書いた人が見る（機械で断るフックの頼み〔受付 20261018-025604-fb63b1〕は持ち主が取り下げた。訳は[改善の台帳](../reform/ledger.md)の「頼み d47868」）。決まり 8 の手順 1（前の版の本文の行が、分けた版のスキルのフォルダのどこかに残っているか）は、次の一行で照合できる（残っていない行を出す。書き替えた行は訳を添えて一覧にする）:

```
python3 -c 'import re,sys,pathlib;b=re.sub(r"\A---\n.*?\n---\n","",open(sys.argv[1]).read(),flags=re.S);n="".join(p.read_text() for p in pathlib.Path(sys.argv[2]).rglob("*.md"));[print(l) for l in b.splitlines() if l.strip() and l.strip() not in n]' <前の版の SKILL.md か commands/*.md> <分けた版の skills/<名前>/>
```

圧縮の後に付け直す全部のスキルの合計の枠（25,000 トークン）も決まりにしない。1 つの会話で呼ぶスキルの数は使う人で決まり、書く側で抑えられないから。

手元で本文の行数（と字数）を見るには:

```
python3 -c 'import re,sys;s=open(sys.argv[1]).read();b=re.sub(r"\A---\n.*?\n---\n","",s,flags=re.S);print(len(b),"字",len(b.splitlines()),"行")' <SKILL.md のパス>
```
