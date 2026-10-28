# 工場の版の自動の上げ（works-factory プラグインの PIN）

works-factory プラグインの殻（`works-factory/bin/works-factory`）は、工場 raiki61/works-factory の決まった commit（`works-factory/PIN` に書いた 40 桁の sha。以下 PIN）を取ってきて使う。PIN はこれまで手で上げていた（works-factory の窓口が `--ask` で頼み、作業の部署が PIN・CHANGELOG・要ればスキルを直す。受付 20261023-040706-fb72dd・20261023-084220-ad35ba）。持ち主の問い（2026-10-26「常に自動であげれないのか」）を受けて、工場の main が進んで CI が緑になったら上げる頼みが自動で立つ形にした（受付 20261026-055008-8aa008）。その後、持ち主の言葉（2026-10-28「都度最新にできないのかな。自動で。」「いやLLMも要らないような自動のあげかた」）を受けて、スキルに効く変更の照合（3.4）に当たりが無い上げは、作業の部署（AI の会話）を立てずにツールが自分で main に入れる形にした（機械の上げ。3.7。受付 20261027-220658-b1fdf1）。

## 1. 決め: 工場の CI の緑だけで上げる（案 A）

持ち主が 2026-10-26 に案 A を選んだ（「おし」。勧めた案 A への答え。受付 20261026-072130-ea695b）。会社の形（`.claude/company.toml`）の `[[land.after]]`（main に入れた後に呼ぶツールの並び。呼ぶこと、またその呼びを以下「合図」と言う）に `role = "工場の版の見張り"`・`tool = "works-factory-pin"` を並べた。

- 採った: 案 A。工場の main の CI（check の名 `tests`）が緑なら、上げて配る。代償: 工場の CI は本物の run（AI の役を起こす実走）を回さないので、CI を通るが実走で壊れる変更も利用者の手元に届く。戻すのは、前の PIN に戻す手の上げ 1 回。
- 採らない: 案 B（上げる前に、works-factory の窓口へ実走を頼み、緑の答えを待ってから `--land` する）。上げのたびに run 1 回分の費用と、run が終わるまでの待ちが掛かり、works-factory の窓口と実走の部署の手も要る。戻すのが 1 回の直しで済む A に比べ、毎回の費用が重い。

## 2. 流れ

1. claude-plugins の main に誰かが `--land` で入れると、works-dispatch が `[[land.after]]` の並びで、機械だけの役（会話を立てずにコマンドだけを回す役。works-dispatch の機械窓口）「工場の版の見張り」のツール `python3 scripts/works-factory-pin.py` を呼ぶ。手では `dispatch.py --call claude-plugins/工場の版の見張り works-factory-pin` で呼べる。
2. ツールは、まず自分が前に回した頼みが開いていないかを受付箱で見る。開いていれば 0 で黙る。
3. 次に、PIN の後の工場の main の commit を新しい順に見て、check の名 `tests`（工場の CI で、4 つに分けた試験の結果を 1 つにまとめる job）が緑の最初の物を上げ先にする。無ければ 0 で黙る。
4. 上げ先が在れば、前の PIN と上げ先の 2 つの木を比べ、スキルに効く変更を照合する（3.4）。
5. 照合に当たりが無ければ、機械の上げ（3.7）を打つ。ツールが代表の clone に一時のブランチを作り、PIN と `works-factory/CHANGELOG.md` の `## [Unreleased]` を書いて commit し、works-dispatch の `--land` で main に入れて 0 で終わる。版は `--land` が上げ、配布はその `--land` の後の合図の spread-plugins がする。ここで終われば AI は立たない。
6. 照合に当たりが在るか、機械の上げが失敗したら、上げ先・取り込む PR（main に入った順）・照合の結果（失敗ならその訳と `--land` の出力の終わり）と手順を出して 1 で終わる。works-dispatch がその出力の末尾 20 行を添えた頼みを作業に回し、作業の部署が立つ。
7. 作業の部署は `python3 scripts/works-factory-pin.py --write <上げ先の sha>` で PIN と `works-factory/CHANGELOG.md` の `## [Unreleased]` を書く。照合で当たりが在れば、スキル（`works-factory/skills/works-factory` の SKILL.md と references）を工場の PR と README に合わせて直し、CHANGELOG に利用者に効く違いを書き足す。
8. 作業の部署が `--land` で入れる。版は `--land` が上げ、配布は `--land` の後の合図の spread-plugins がする。

同じ上げ先を何度も頼まない: 知らせた上げ先と時刻を、代表の clone の git の共通のディレクトリの `works-factory-pin.json` に覚える。回した頼みが開いている間は黙り、閉じた後も同じ上げ先なら黙る（作業の部署が上げずに閉じた上げ先を頼み直さない）。知らせた後に頼みが立っていなければ（works-dispatch が頼みに変えられなかった時）、次の呼びで知らせ直す。工場の main が進んで上げ先が変われば知らせ直す。

失敗のとき: 工場を読めない（gh の失敗・PIN が工場の main の祖先でない・工場が答えた commit の一覧の数が、PIN から工場の main の頭までの commit の数〔GitHub の比べの答えの ahead_by〕と合わない・git の失敗）ときは、理由を出して 1 で終わる。works-dispatch が頼みに変えて作業に回すので、黙って止まらない。その頼みが開いている間は、2 のとおり工場を読む前に黙るので、頼みは積まれない。

## 3. 決めた事（案・推し・代償）

### 3.1 きっかけ: claude-plugins の main に入れた後の合図

- 採った: `[[land.after]]`（tests/ci-watch.py と同じ形）。代償は、claude-plugins の main に誰も入れない間は見張りも止まること。手で `--call` を打てば回る。
- 採らない: 手元の定期の起動（cron・launchd）。持ち主が置かないと決めている（works-dispatch/docs/ledger.md の「cron・launchd で刻む形: 採らない」）。
- 採らない: 工場からの知らせ（工場の GitHub Actions から claude-plugins へ repository_dispatch を送る）。works-factory の側に常駐の仕組みを足すことになり、works-factory の決まり E10 で先に持ち主の決めが要る。
- 採らない: claude-plugins の GitHub Actions の定期。版の上げ（`--land`）と配布（spread-plugins）が手元にしか無く、Actions から main へ直に push すると `--land` の列とゲートを外れる。機械の上げ（3.7）も同じ訳で、ツールの中で push せずに `--land` を打つ。

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

### 3.7 照合に当たりの無い上げ: 機械で `--land` まで打つ

この節は設計の記録で、読み手に求める作業は無い。ツール（`scripts/works-factory-pin.py`）の `land_pin` を直す・不具合を調べる人が、機械の上げの手順と落とし穴を知るために読む。今壊れている物の話ではない。

- 採った: 照合（3.4）に当たりが無ければ、ツールが自分で上げて `--land` で入れる。手の上げで作業の部署がしていたのは、`--write` を打ち、照合に当たりが無ければそのまま `--land` を打つことだけで、判断が無い。判断の要る、照合に当たりの在る上げと、機械の上げが失敗した上げだけを作業に回す。
- 採らない: 照合に当たりが在っても機械で上げる。スキルが古いまま利用者に届く。
- 採らない: ツールの中で main へ直に push する（`--queue-run` で列には並べる）。版の上げ（`--land` の bump）とゲート（`[land]` の `check`）と配布の合図を写すことになり、`--land` と割れる。

手順（`land_pin`）:

1. 代表の clone（`~/src/claude-plugins`。main を出しておく本社の clone）で origin の main を取り直し、その main の `works-factory/PIN` を読む（以下、取り直した PIN）。上げ先は、2 の 3 で決めた、上げる先の工場の commit。取り直した PIN と、見張りが読んだ PIN（works-dispatch がツールを走らせる一時の場所の木の物で、取り直していない）を、次のように分ける。
   - 取り直した PIN が上げ先と同じ: ほかの上げが先に入れたので、打たずに 0 で黙る。
   - 取り直した PIN が見張りが読んだ PIN と違い、上げ先でもない: ほかの上げが先に入ったので、打たずに 0 で黙り、次に main に入れたときの合図で見直す。作業には回さない。
   - 取り直した PIN が見張りが読んだ PIN のまま: 手順 2 へ進む。
2. 同じ名前のブランチの worktree が在れば、鍵（`git worktree add --lock` の理由欄に書いた、作った処理の pid）を見る。その処理が居れば、同じ上げを走らせているので打たずに 0 で黙る。居なければ、殺された機械の上げの残りなので消す。
3. origin の main の頭から、一時の worktree とブランチ `works-factory-pin/<上げ先の頭 12 字>` を、自分の pid の鍵を掛けて作る。git は代表の clone の worktree ごとの git の設定のうち `company.role` など `company.*` の項目（works-dispatch が、その worktree をどの役の部署の作業場かと見分けるのに読む物）を新しい worktree に写す。写ったままだと一時の worktree が部署の作業場に見えるので、この項目を消す。このツール自身の `--write <上げ先の sha>`（2 の 7。`works-factory/PIN` を上げ先の sha に、`works-factory/CHANGELOG.md` の `## [Unreleased]` に取り込んだ PR と比べの URL の 1 行を書く）と同じ関数で PIN と CHANGELOG を書いて commit する。
4. works-dispatch の `--repo <代表の clone> --land <ブランチ>` を打つ。works-dispatch は合図のツールに自分のパスを環境変数 `WORKS_DISPATCH`・`WORKS_DISPATCH_PYTHON` で渡す（works-dispatch/docs/land.md の「外のツールが列に並ぶ」）。`--land` はブランチの名前で部署を探すので、会話の無いこのブランチも入れられる。
5. 入ったかは、`--land` の終了の値でなく、origin の main の PIN が上げ先になったかで決める（取り直せないときだけ、`--land` の終了の値 0 を入ったとみる）。入らなければ、`--land` の出力の終わり 12 行を添えて作業に回す。
6. 入っても入らなくても、作った worktree とブランチを消す（入らなかった commit は、作業の部署が上のツールの `--write` を打てば同じ物を作り直せる）。消せなければ注記を出し、次の機械の上げが 2 の残りとして消す。`--land` はリベースしたブランチを origin に push するので、入らなくても origin に同じ名前のブランチが残る。origin にそのブランチが在れば `git push origin --delete` で消し、消せなければ注記の 1 行を出す（2026-10-27 の上げ先 9a7c5d8d で origin に残ったのを受けた直し。受付 20261027-235947-6e9cec）。

列の鍵: `--land` は、main へ push し終えたところで列（`[land]` の `queue`）の順番を手放し、その後で合図（`[[land.after]]`）を呼ぶ（works-dispatch/dispatch/landing.py の `hold.drop()` の後の `after`）。合図の中の機械の上げが打つ `--land` は、ほかの `--land` と同じ列に並び、外の `--land` と待ち合って止まることは無い。`--call` で手で呼んだときも同じ列に並ぶ。

再入: 機械の上げの `--land` も、main に入れた後の合図で spread-plugins・CI の見張り・このツールを呼ぶ。spread-plugins は上げた版を配る（配布はこれで済む）。このツールは、機械の上げが `--land` に渡した環境変数 `WORKS_FACTORY_PIN_LANDING`（works-dispatch は合図のツールに自分の環境を継いで渡す）を見て、工場を読まずに 0 で黙る。黙らせないと、工場の main がさらに進んでいれば上げの中で上げを重ね、外の `--land` が終わるまでの時間が延びる。さらに進んだ分は、次に誰かが main に入れたときに上げる。

ゲート: 機械の上げの `--land` も `[land]` の `check` を全部回す。最後の初見読み（gates の branch-check）は AI（haiku）を起こして CHANGELOG の 1 行を読むが、これはゲートの読み手で、作業の部署は立たない。詰まりが出たら `--land` が止まり、作業に回る。

## 4. 残る癖

- 合図で立った頼みの頼み元は、その時に main に入れた部署の頼み元になる（works-dispatch の calls.fire。CI の見張りと同じ）。上げの納品は works-factory の窓口でなく、その頼み元に届く。
- 機械の上げの `--land` の合図で立った頼み（その後の spread-plugins の失敗など）には頼み元が無い（機械の上げのブランチは部署の属性を持たない）。頼みは回るが、納品の返り先が無い。
- 機械の上げは、外の `--land` の合図の中で `--land` をもう 1 回まるごと回すので、外の `--land` が終わるまでの時間がゲート 1 回分（初見読みを含めて数分）延びる。
- 機械の上げの commit には頼みの受付が無い。何を入れたかは CHANGELOG の行と、上げた `--land` の出力で見る。
- ツールが読むのは origin の既定のブランチの中身（works-dispatch がツールを一時の worktree で走らせる）。この役とツールは main に入ってから呼べる。
- 頼みに載るのは出力の末尾 20 行なので、照合の当たりが多いと前の行が落ちる。手順の行は最後に出し、全文は `--write` の出力で見る。照合の 1 行は 300 字で切る。
