# /catchup の図の書き方（図を描く前に読む）

/catchup（1 件の PR などについて、前回から何が起きたかを 1 枚の HTML のページに描く命令）のページに載せる図の書き方。図は、AI が書く欄の JSON（ページに描く文を書く JSON。`headline`・`where`・`turn`・`next` などと並ぶ）の `figure` に書く。読むのは、図を描くと決めたときにその都度、書く前。いつ描くか（描く条件・形は中身で選ぶ・3 枚まで）は、SKILL.md の手順 4 で読む欄の書き方の `figure` の項にあり、この文書はその続き。機械（`catchup_html.validate_fields`）が形を確かめ、直す所を 1 件 1 行で言う。


| 中身 | kind |
|---|---|
| 部品のつながり・データの流れ・構成 | `graph` |
| 誰が誰に何を送るかの順（API・認証の往復） | `sequence` |
| 時間の順の段（ジョブ・移行の手順・状態の移り） | `steps` |
| 画面の見た目（設定画面・フォーム） | `screen` |
| 項目ごとの値（既定値・権限・対応表） | `table` |
| 名前ごとの前 → 後の短い対比 | `compare` |
| 上のどれにも収まらない | `html` |

```json
{"kind": "graph", "dir": "LR", "groups": [{"id": "be", "text": "backend"}], "nodes": [{"id": "api", "text": "通知の設定の API", "group": "be", "in": "after", "points": [1]}, {"id": "db", "text": "利用者の表", "fields": [{"name": "notify_email", "type": "bool", "in": "after"}]}, {"id": "job", "text": "通知の送り手", "was": "全員に送る", "tone": "good", "sub": "設定を見てから送る", "points": [2]}], "edges": [{"from": "api", "to": "db", "text": "書く", "in": "after", "points": [1]}, {"from": "job", "to": "db", "text": "読む", "in": "after", "points": [2], "code": [{"path": "app/models/user.py", "find": "class NotifySetting"}]}], "play": [{"text": "利用者が設定を保存する", "nodes": ["api"], "edges": ["api>db"]}, {"text": "送る前に設定を読む", "nodes": ["job"], "edges": ["job>db"]}]}
{"kind": "sequence", "actors": [{"id": "ui", "text": "画面"}, {"id": "be", "text": "backend"}, {"id": "idp", "text": "認証の基盤"}], "steps": [{"from": "ui", "to": "be", "text": "ログインする"}, {"from": "be", "to": "idp", "text": "トークンを確かめる", "in": "after", "tone": "good"}], "play": true}
{"kind": "steps", "lanes": [{"id": "ci", "text": "CI"}, {"id": "prod", "text": "本番"}], "steps": [{"text": "移行を流す", "lane": "ci", "when": "配備の前", "tag": "新", "note": "列が在れば何もしない", "in": "after"}], "play": true}
{"kind": "screen", "title": "設定 › 通知", "items": [{"type": "toggle", "label": "メールで受け取る", "value": "on", "in": "after"}, {"type": "button", "label": "保存", "primary": true}]}
{"kind": "table", "columns": ["読む", "書く"], "rows": [{"label": "管理者", "cells": ["○", {"text": "○", "was": "×", "tone": "good"}]}]}
{"kind": "compare", "rows": [{"name": "送る相手", "before": "全員", "after": "設定で受け取る人だけ", "tone": "good"}]}
{"kind": "html", "html": "<svg viewBox=\"0 0 600 200\">…</svg>"}
```

- **前と後**: 前後で変わる図は、1 つの図の中で箱・線・行・部品に `in`（`before` は前だけに在る、`after` は後だけに在る）を付け、両方に在って字が変わるなら `was`（前の字）を書く（`was` が使えるのは箱・箱の列・画面の部品・表のセル。線の字が変わるなら、前の線に `in: "before"`、後の線に `in: "after"` を付けて 2 本にする）。機械が前と後の 2 枚に描き分ける。`tone` は変わった所の色（`bad` は悪かった所、`good` は良くした所）。変わっていない所には付けない
- **graph**: 座標は書かない（機械が並べる）。`group` は囲み、`sub` は箱の下の補足（60 字）、`fields` は表の列（`{name, type}`。列の前後も `in`・`was`）、`points` はその箱に当たる変更点の番号（欄の `points` は `figure` の外の、欄の最上位にある変更点の一覧で、`{"caption": …, "items": [{"title": …, "before": …, "after": …, "code": …}]}` の `items` の 1 項が変更点 1 点。番号はその並びを 1 から数えた順番。`in`・`was` の付いた箱には必ず書く。差分の外で作る物なら `[]`）、`code` はその箱の差分。`dashed: true` は弱い・任意のつながり
  - 線（edges）は、どこからどこへ・どんなデータが流れるか（入出力）を表す。線も `points` と `code` を持て、線の字を押すと項かコードが開く。線の `code` は変えた行より先に、**流れるデータの形を決めている所**を指す——受け先の API のリクエストとレスポンスの型、キューのメッセージの型、渡す資格情報の種類と Secret のキー、通信を許す規則（NetworkPolicy など）。線の字は流れる物の名前だけを 18 字まで（「渡す」より「文書を multipart で渡す」）。それより細かい形や資格の種類は字に足さず、押すと出る札とコードに任せる（字が長いと図が横に広がって縮む）。`in` の付いた線には `points` を必ず書く（差分の外でつなぐ物なら `[]`）
  - `code` は差分に無い file も指せる。この PR で変えていない受け先の API の型（リクエストの型・スキーマ）を見せたいときは、その file の path と、型の名前を `find` に書く。機械が PR の先頭の版から読み、`find` の行の前 2 行からその塊の終わりまで（8〜40 行）を「この PR では変えていない」と断って出す。箱や線を押すと、その横に札が出て、`points` の項（前と後）と、自分の `code` を開くボタンが並ぶ
- **steps**: `lanes` は担い手の列（`{id, text}`。省いてよい）で、段の `lane` はそのどれかの id。段の `text` は何をするか、`when` はいつ（「配備の前」）、`tag` は段に付ける短い印（「新」）、`note` は段の補足
- **screen**: 部品（`type`）は heading・text・field・textarea・select・radio・checkbox・toggle・button・tabs・list・alert。字は差分の画面の文言から写す（作らない）。見取り図であって画面そのものではないと、題か `caption` で分かるように
- **順に見せる（`play`）**: 順番に意味があるとき（処理の流れ・往復）だけ。graph はコマ（`{text, nodes: [id], edges: ["from>to"]}`）を 2〜10、sequence と steps は `true`。機械が画面に入った図を順に光らせ、線の上に点を流す
- **html**: 上の形に収まらないときだけ。20000 字まで。HTML・インラインの SVG・CSS・SVG の動き（animate）は使える。スクリプト・イベント（`on…`）・外を指す `url(`・フォームの送信は機械が止める。幅は枠（100%）に合わせ、字が枠からはみ出すと機械がページに注記を出す
- **字**: 箱・線・役者は 40 字、段は 60 字まで（長い説明は説明か変更点へ）。**ラベルは説明（欄の `explain`。この件が何のために何をどう変えるかの文）と作者（PR などを書いた人）の語だけ**、関係は機械の「名前の言及」（機械が書く文字の報告の「変更の地図」の節にある、変更ファイルの追加行がほかの変更ファイルの名前を挙げている所。呼び出しの当たり。材料を読んだ AI は、この一覧を手元に持っている）か本文が言うものだけ（推測なら「（未確認）」）。図の名詞を全部、説明か本文の語に指で当てられないなら描かない
