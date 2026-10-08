<!-- coldwrite:skip 内部の設計書。語は「目的と語」の節と works/README.md で定義 -->
# ライブラリの文書を 3 つの出どころから引く（手元の版・公式・Context7）

状態: 入れた（`.shared/core/libdocs.py`・`libdocs_local.py`・`libdocs_web.py`・`auth_launch.py` の Context7 の鍵）。残りは本物の run での確かめ（7 節）。

> **2026-10-09 追記: Context7 はやめた（持ち主の決め）。** 3 つめの出どころ（Context7 の HTTP API）と、その鍵の受け渡し（`auth_launch.py` の keychain の項目・run の控えと続きの行の項目の名）、役に貸す Context7 の MCP（包みの `--mcp-config` と `dev/toolset.py` の kind "mcp"）を消した。ライブラリの文書は手元の版と公式の 2 つから引き続き引く。量の取り分は 1 本のライブラリの分を手元 1/2・公式の残り（1/2）で先に分け、余りを手元 → 公式の順に埋める。網の止めは `WORKS_LIBDOCS_WEB=off`（前の名 `WORKS_CONTEXT7=off` は効かない）。節の題は「ライブラリの文書（手元の版・公式）」。下の本文は 2026-10-08 の決めのまま残す（履歴）。

## 平たく言うと（3 行）

- 修正役と修正案の役の指示書に貼るライブラリの文書を、Context7 だけでなく、run の中に入っている版のコード（手元）と、ライブラリの公式の文書（登録の要らない web）からも引く。
- Context7 は鍵なしの月の枠が利用者の run で毎回尽きていた（HTTP 429）。手元と公式は登録も鍵も要らないので、枠が尽きても文書が届く。
- Context7 の鍵は、利用者の env の `CONTEXT7_API_KEY` か keychain の項目（`WORKS_CONTEXT7_KEYCHAIN_ITEM`）から、Claude のトークンと同じ外の層で拾って子の環境にだけ置く。

## 目的と語

持ち主の決め（2026-10-08）: 「全部使う」。登録の要らない物を土台に、次の順で引き、今の量の上限（`BUDGET` 4000 トークン）の中で合わせる。

語:

- 手元（local）: run の作業ツリー（と、同じ git の main の作業ツリー）に今入っている仮想環境・`node_modules` の中のライブラリのファイル。版は入っている物そのもの
- 公式（official）: ライブラリの持ち主が出す文書を、登録の要らない口で取った物（PyPI の JSON・npm の registry・docs の場所の `llms.txt`・GitHub の raw の README）
- Context7: 今までの HTTP API（`https://context7.com/api`）。鍵があれば上限が上がる
- 役の自分の引き: 役が持つ WebSearch・WebFetch（と、`WORKS_CONTEXT7_MCP=on` の時の Context7 の MCP）

## 1. 決め

1. **順は 手元 → 公式 → Context7 → 役の自分の引き**。手元は今の版そのもので、署名と docstring・型の宣言はコードの正本。公式は持ち主の文で、版を合わせられる物は合わせる。Context7 は集めた物で正しさの保証が無い。どれでも取れなかったライブラリは節の頭に名指し、役に自分で引けと言う
2. **手元は作らずに探す**。仮想環境を作らない・入れない。単位のファイルの置き場から根まで上へ辿り、各段の `.venv`・`venv`・`.tox/*`・`.nox/*`（Python）と `node_modules`（JS/TS。Node の探し方と同じ）を見る。根は run の作業ツリーと、その git の main の作業ツリー（`.git` のファイルの `gitdir:` と `commondir` から。git を起こさない）。TDD の輪の試験が `uv run` などで run の作業ツリーに作った環境も、利用者が手元で作った環境も、在れば読む
3. **手元は import しない**。Python は `ast` で静的に読み（対象のコードを走らせない）、JS/TS は `.d.ts` と `package.json`・README を字で読む。環境の置き場は実パスが根の実パスの中に在る物だけ（置き場そのものか途中のフォルダが symlink で根の外を指せば見ない。修正役が書いた symlink で sandbox の外の支度の節に外を読ませないため）。読むファイルは置き場の実パスの中に在る物だけ（symlink で外を指す物は読まない）、1 本 1 MB まで。`*` の再輸出を辿る時は同じファイルを 2 度読まない
4. **手元で読んだ版と配る名を以後に使う**。依存の宣言の版（`>=` なら下の端）より入っている版が正しいので、公式と Context7 にはその版で問う。宣言の版と入っている版が違えば節に書く。輸入の名と配る名が違い宣言にも表にも無い物（`import serial`・配る名 `pyserial`）は、dist-info の Name で問う（輸入の名で問うと registry の別のプロジェクトを公式として貼る）
5. **公式は名と版だけを送る**。問いの URL はライブラリの名・版と、registry の答えに在った URL だけ。対象のコードの字も、単位が使う名も送らない（Context7 の問いより狭い）。鍵（`Authorization`）は付けない。docs の場所と転送の先は https で、host が点を持つ名の物だけ（IP の字・localhost・点の無い社内の名は不可。`libdocs_web.safe_url`）。host が替わる転送では Context7 の鍵の頭も落とす（`libdocs.SafeRedirect`）。答えは 4 MB まで読む。期限は足さない（R4。節の宣言の 20 日だけ）
6. **公式の口は小さく固い組**: Python は PyPI の JSON（`/pypi/<名>/<版>/json`、版が無ければ `/pypi/<名>/json`）の `info.description`（その版の README）と、`project_urls` の docs の場所の `llms-full.txt`・`llms.txt`（docs の場所の下、次に host の根。`# ` で始まる文書だけを受け、HTML は捨てる）。JS は npm の registry（`/<名>/<版>`、その版が無ければ `/<名>/latest`）と `homepage` の `llms*.txt`。版の文書は今の registry では `readme` を持たない（2026-10-08 に zod・express・@types/node で確かめた。在れば使う）ので、README は `repository` が GitHub の時の `raw.githubusercontent.com` の `v<版>`・`<版>`・版の文書の `gitHead` の commit の `[<directory>/]README.md`（最初に取れた 1 本）。ライブラリ 1 本の問いは PyPI で多くて 6 本、npm で 9 本
7. **控えは Context7 と同じ置き場と長さ**。公式の取れた物と見つからない物を、盤面の周の置き場 `libdocs/<名>@<版>.official.json` と、包みの家の `libdocs/` に同じ名で控える（家は 7 日）。名と版だけで引くので問いの digest は付けない。取れなかった物（網の誤り・5xx）は控えない。文書 1 本は 400,000 字までにして控える。手元は控えない（今入っている物を毎回読む。網に出ない）
8. **量の分け方**: 文書の取れたライブラリの数で `BUDGET` を割り、1 本の分の中を 手元 1/2・公式 1/4・Context7 1/4 で先に分け、余りを 手元 → 公式 → Context7 の順に、入らなかった断片で埋める（手元が空なら公式と Context7 が使う）
9. **`WORKS_CONTEXT7=off` は網に出ない**（今までどおり。公式も Context7 も引かない）。手元は網に出ないので読む
10. **Context7 の鍵は外の層で拾う**。起こし役 `auth_launch.py exec` が、`WORKS_CONTEXT7_KEYCHAIN_ITEM` を名指していればその項目を利用者の HOME で読み、子（Archon）の環境の `CONTEXT7_API_KEY` に置く（名指しが受け継いだ env より先。Claude のトークンの `WORKS_KEYCHAIN_ITEM` と同じ）。読めなければ 1 行（項目の名だけ）を出して鍵なしで起こす（Context7 は任意なので止めない）。名指しが無ければ受け継いだ `CONTEXT7_API_KEY` のまま。値は標準出力・引数・控えに出さない。run の控え（`<家>/runs/<run-id>.json`）と続きの行は項目の名だけを持つ
11. **Archon v0.11.1 は env を script の節に渡す**（確かめた。下の 3 節）。だから鍵は Archon の子の環境に置けば支度の節に届く

## 2. 節の形

題は `## ライブラリの文書（手元の版・公式・Context7）`。頭の文は順と信頼の差を言う。数の行の下に出どころごとの行を置き、どれも数と名で言う（黙って落とさない）:

- `- 手元の版: 読めた N 本（名 版）／入っていない M 本（名）／読めなかった K 本（名: 理由）`
- `- 公式の文書: 取れた N 本（盤面の控えから・ほかの run の控えから）／見つからない M 本（名）／取れなかった K 本（名: 理由）`
- Context7 の行は今までどおり（枠切れ・Context7 に無い・版が合わない・取れなかった）
- `- どこからも文書が無い: 名、名（WebSearch・WebFetch で公式の文書を自分で引け）`

本文はライブラリごとに 手元 → 公式 → Context7 の順に断片を並べ、どの断片にも出どころ（ファイルのパスか URL）を付ける。

## 3. Archon v0.11.1 の env（確かめた所）

- script・bash の節は `runSubprocess`（`packages/workflows/src/dag-executor.ts`）で起き、host の run は `{ ...process.env, ...options.env }` を子に渡す（options.env は節の入力・codebase の env・資格だけ）
- `process.env` は起動の頭で `stripCwdEnv`（`packages/paths/src/strip-cwd-env.ts`）が掃除する: cwd（対象）の `.env`・`.env.local`・`.env.development`・`.env.production` に在る鍵と、CLAUDECODE・認証以外の CLAUDE_CODE_*・NODE_OPTIONS などだけを消す。`CONTEXT7_API_KEY` は消さない（対象の `.env` に同じ名が在る時だけ消える）
- Archon の家の `.env`（`$ARCHON_HOME/.env`。隔離した家では `$WORKS_DEV_HOME/archon-home/.env`）も読まれる。works は使わない（鍵をファイルに書かない）
- 名が KEY・TOKEN・SECRET・PASSWORD で終わる env の値は、節の出力・誤りの文から `[REDACTED]` に替わる（`collectSubprocessCredentialValues`）。`CONTEXT7_API_KEY` も当たる
- AI の節（Claude の子）も同じ `process.env` を継ぐ（`providers/claude/provider.ts` の `buildSubprocessEnv`）。鍵は役の Bash からも見える。Claude のトークン（`CLAUDE_CODE_OAUTH_TOKEN`）と同じ扱いで、それより広くはしない

## 4. 部品

- `libdocs_local.py`（層 L3）: `roots(repo)`・`py_uses(text)`・`js_uses(text)`・`read(roots, lib, files)`。標準ライブラリだけ
- `libdocs_web.py`（層 L3）: `safe_url(url)`・`https_site(url)`・`fetch(lib, version, get)`・`fragments(docs, uses)`。網は get で差し替える
- `libdocs.py`: 見つけた行に `uses`（単位が使う名）を足し、3 つを順に引いて節を組む。`http_get` は 4 MB まで読み、転送は `SafeRedirect` を通す
- `auth_launch.py`: `context7_env(env, runner)` を足し、exec の子の環境に置く

## 5. 試験

- `tests/test_libdocs_local.py`: 偽の `.venv/lib/python3.x/site-packages` と `node_modules` を一時の置き場に作る。import しない（`__init__.py` の頭に `raise SystemExit` を置いても読める）・名の解き（再輸出を辿る）・版・symlink の外は読まない・main の作業ツリーの根
- `tests/test_libdocs_web.py`: 偽の HTTP の口。PyPI・npm（本物と同じく readme の無い版の文書）・llms.txt・GitHub の README（tag・gitHead・directory）・HTML の捨て・見つからない・誤り・送る URL に名と版だけ・IP の字と localhost と http を拒む
- `tests/test_libdocs.py`: 3 つが順に並ぶ・量の上限・手元の版で Context7 の版を指す・どこからも無い物の名指し・off でも手元・公式の控え（盤面・家）・鍵は Context7 の URL にだけ
- `tests/test_auth_launch.py`: 名指しの項目の鍵を子にだけ置く・受け継いだ鍵はそのまま・読めなくても起こす・値を出さない

## 6. 危うい所

- 手元の main の作業ツリーの環境は、run の版と違う commit の依存かもしれない。読んだ版を節に書き、宣言の `==` と違えば言う
- 公式の `llms-full.txt` は大きい物がある。4 MB で切って、単位が使う名を含む節を先に選ぶ
- 公式の口に期限は無い（R4）。応えない server は節を止める。Context7 と同じ扱いで、`WORKS_CONTEXT7=off` で網ごと切れる
- 版の分からないライブラリの PyPI の版なしの JSON（`/pypi/<名>/json`）は全部の版の一覧を持ち、大きい物（botocore で約 3.9 MB）は 4 MB で切れて「JSON が読めない」になりうる。手元か宣言で版が分かれば版つきの小さい JSON を引く
- Python の手元の読み取りは `*` の再輸出を深さ 4 まで辿る。大きいパッケージで遅くなりうる（同じファイルは 2 度読まず、同じ (モジュール, 名) は辿り直さない）

## 7. 本物の run で確かめる事

- 鍵なしの利用の家で、Context7 が 429 でも手元と公式の文書が節に載ること
- `WORKS_CONTEXT7_KEYCHAIN_ITEM` で起こした run の支度の節が鍵つきで Context7 を引くこと（控えの `_quota.json` の `keyed` が true）
