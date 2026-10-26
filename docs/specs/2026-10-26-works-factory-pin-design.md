# 工場の版の自動の上げ（works-factory プラグインの PIN）

works-factory プラグインの殻（`works-factory/bin/works-factory`）は、工場 raiki61/works-factory の決まった commit（`works-factory/PIN` に書いた 40 桁の sha。以下 PIN）を取ってきて使う。PIN はこれまで手で上げていた（works-factory の窓口が `--ask` で頼み、作業の部署が PIN・CHANGELOG・要ればスキルを直す。受付 20261023-040706-fb72dd・20261023-084220-ad35ba）。持ち主の問い（2026-10-26「常に自動であげれないのか」）を受けて、工場の main が進んで CI が緑になったら上げる頼みが自動で立つ形にした（受付 20261026-055008-8aa008）。

## 1. 決め: 工場の CI の緑だけで上げる（案 A）

持ち主が 2026-10-26 に案 A を選んだ（「おし」。勧めた案 A への答え。受付 20261026-072130-ea695b）。会社の形（`.claude/company.toml`）の `[[land.after]]`（main に入れた後に呼ぶツールの並び）に `role = "工場の版の見張り"`・`tool = "works-factory-pin"` を並べた。

- 採った: 案 A。工場の main の CI（check の名 `tests`）が緑なら、上げて配る。代償: 工場の CI は本物の run（AI の役を起こす実走）を回さないので、CI を通るが実走で壊れる変更も利用者の手元に届く。戻すのは、前の PIN に戻す手の上げ 1 回。
- 採らない: 案 B（上げる前に、works-factory の窓口へ実走を頼み、緑の答えを待ってから `--land` する）。上げのたびに run 1 回分の費用と、run が終わるまでの待ちが掛かり、works-factory の窓口と実走の部署の手も要る。戻すのが 1 回の直しで済む A に比べ、毎回の費用が重い。

## 2. 流れ

1. claude-plugins の main に誰かが `--land` で入れると、works-dispatch が `[[land.after]]` の並びで、機械だけの役（会話を立てずにコマンドだけを回す役。works-dispatch の機械窓口）「工場の版の見張り」のツール `python3 scripts/works-factory-pin.py` を呼ぶ。手では `dispatch.py --call claude-plugins/工場の版の見張り works-factory-pin` で呼べる。
2. ツールは、まず自分が前に回した頼みが開いていないかを受付箱で見る。開いていれば 0 で黙る。
3. 次に、PIN の後の工場の main の commit を新しい順に見て、check の名 `tests`（工場の CI で、4 つに分けた試験の結果を 1 つにまとめる job）が緑の最初の物を上げ先にする。無ければ 0 で黙る。
4. 上げ先が在れば、前の PIN と上げ先の 2 つの木を比べ、スキルに効く変更を照合する（3.4）。上げ先・取り込む PR（main に入った順）・照合の結果と手順を出して 1 で終わる。works-dispatch がその出力の末尾 20 行を添えた頼みを作業に回し、作業の部署が立つ。
5. 作業の部署は `python3 scripts/works-factory-pin.py --write <上げ先の sha>` で PIN と `works-factory/CHANGELOG.md` の `## [Unreleased]` を書く。照合で当たりが在れば、スキル（`works-factory/skills/works-factory` の SKILL.md と references）を工場の PR と README に合わせて直し、CHANGELOG に利用者に効く違いを書き足す。
6. 作業の部署が `--land` で入れる。版は `--land` が上げ、配布は `--land` の後の合図の spread-plugins がする。

同じ上げ先を何度も頼まない: 知らせた上げ先と時刻を、代表の clone の git の共通のディレクトリの `works-factory-pin.json` に覚える。回した頼みが開いている間は黙り、閉じた後も同じ上げ先なら黙る（作業の部署が上げずに閉じた上げ先を頼み直さない）。知らせた後に頼みが立っていなければ（works-dispatch が頼みに変えられなかった時）、次の呼びで知らせ直す。工場の main が進んで上げ先が変われば知らせ直す。

失敗のとき: 工場を読めない（gh の失敗・PIN が工場の main の祖先でない・工場が答えた commit の一覧の数が、PIN から工場の main の頭までの commit の数〔GitHub の比べの答えの ahead_by〕と合わない・git の失敗）ときは、理由を出して 1 で終わる。works-dispatch が頼みに変えて作業に回すので、黙って止まらない。その頼みが開いている間は、2 のとおり工場を読む前に黙るので、頼みは積まれない。

## 3. 決めた事（案・推し・代償）

### 3.1 きっかけ: claude-plugins の main に入れた後の合図

- 採った: `[[land.after]]`（tests/ci-watch.py と同じ形）。代償は、claude-plugins の main に誰も入れない間は見張りも止まること。手で `--call` を打てば回る。
- 採らない: 手元の定期の起動（cron・launchd）。持ち主が置かないと決めている（works-dispatch/docs/ledger.md の「cron・launchd で刻む形: 採らない」）。
- 採らない: 工場からの知らせ（工場の GitHub Actions から claude-plugins へ repository_dispatch を送る）。works-factory の側に常駐の仕組みを足すことになり、works-factory の決まり E10 で先に持ち主の決めが要る。
- 採らない: claude-plugins の GitHub Actions の定期。版の上げ（`--land`）と配布（spread-plugins）が手元にしか無く、Actions から main へ直に push すると `--land` の列とゲートを外れる。

### 3.2 版の上げ方: `--land` の決まりのまま（minor）

PIN は試験・文書のファイルでないので、`--land` は `## [Unreleased]` の Changed を見て minor を上げる（docs/releasing.md の「上げ幅の決め方」）。前の上げ（0.6.0〜0.10.0）も minor だった。patch にするには決まりの方を変えることになり、要らない。

### 3.3 CHANGELOG: PR の題からは組まない

`--write` が書くのは、PR の番号と比べの URL の 1 行だけ（例: 「工場の固定 commit（`works-factory/PIN`）を 20b4a2ef に上げた。取り込んだ PR は raiki61/works-factory#841・#839・…。差分は https://github.com/raiki61/works-factory/compare/… 。」）。工場の PR の題は工場の中の作り手に向けた文で（例: 「#837 組を当てた後の確かめ直しで、…組を戻さない」）、プラグインの利用者に効く違いを言わない。利用者に効く違いは、照合に当たったときに作業の部署が書き足す。

### 3.4 スキルに効く変更: 機械で照合し、当たれば作業の部署が直す

照合するのは 4 つ。

- スキルの .md が `` ` `` で引いた語・パスのうち、前の PIN の木の `bin`・`lib`・`workflows` に在って上げ先の木の同じ所に無い物（名前の替わりと消し。0.9.0 の `design_only` → `design_talk` の形）
- 本線と周の鎖の yaml（`workflows/line/works-factory-line.yaml`・`workflows/chain/works-factory-chain.yaml`）の頭の `inputs` の、足した・消した・中身（既定と説明）を変えた名前
- 工場の `bin`・`lib` が読む環境変数 `WORKS_FACTORY_*` の、足した・消した名前
- 工場の `README.md` と殻（`bin/works-factory`・`bin/apply`）の変更

当たれば止めて人に回すのではなく、作業の部署（AI）がスキルを直す（前の 2 回の手の上げと同じ仕事）。作業の部署が決められない物は、納品の残った疑問で頼み元に返す。代償: 名前も入力の説明も README も変えずに振る舞いだけを変えた工場の変更は拾えない。名前を替えても、前の名前を移しの扱いとして `bin`・`lib`・`workflows` に残していれば、消えとして拾えない。そのときはスキルが古いまま上がる。

### 3.5 main へ入れる所: `--land`

PR は立てない。このリポジトリは main へ PR を通さず、`--land` のゲート（会社の形の `[land]` の `check`）を通してから fast-forward する決まり（ルートの CLAUDE.md の「判断の線」）。

### 3.6 配布: 続ける

`--land` の後の合図に spread-plugins が在るので、入れれば全アカウントに配られる。新しく作る物は無い。

## 4. 残る癖

- 合図で立った頼みの頼み元は、その時に main に入れた部署の頼み元になる（works-dispatch の calls.fire。CI の見張りと同じ）。上げの納品は works-factory の窓口でなく、その頼み元に届く。
- ツールが読むのは origin の既定のブランチの中身（works-dispatch がツールを一時の worktree で走らせる）。この役とツールは main に入ってから呼べる。
- 頼みに載るのは出力の末尾 20 行なので、照合の当たりが多いと前の行が落ちる。手順の行は最後に出し、全文は `--write` の出力で見る。照合の 1 行は 300 字で切る。
