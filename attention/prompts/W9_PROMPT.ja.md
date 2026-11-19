---
source_sha256: bb324b467c124e673a6df4a5713a3706d4f2c64a892962a8cdcae76a3160fb70
about: W9 直しの案と相乗り（旧の手順 12・13・14。設計書 my-turn-dig-redesign.md の段 14）。items は段 13 で行き先が下書きか報告だけの台帳の件、lenses は script の観点の表の文。items・diffs の行は script が組む。
---
{{prFiles}}

システムの構造:
{{structure}}

{{lenses}}

台帳の指摘（id [種類]: 指摘 | 場所）:
{{items|bullets}}

一般の構造との違いと判断: {{diffs|join:"; "|or:"（無し）"}}

1. fixes: この指摘から組む直しの案を、この順で選ぶ: "remove"（2 か所に在る物を 1 か所から作る・前提を消す）、次に "type"（スキーマか型で、ずれる値を書けなくする）、次に "tool"（出来合いのツール）、最後に "self-made"。上の段で防げるなら下の段を出さない。出来合いのツールの上に自分で書く決まりは自作に数える。案ごとに worldSolution（世の中が同じことをどう解くか。確かめた公式の一次の出典の URL。無ければ "none" と探した語）と items（案が乗る指摘の id〔L1・L2…〕。カンマ区切り）。案の中に指摘の文を書き直さず、id で指す（案が崩れても指摘が残るように）。
2. groups: 指摘の間の組: 1 つの直しで一緒に片づく案か指摘（"one-fix"）と、ほかの指摘を壊す案（"conflict"）。members は案の番号（並べた順に F1・F2…）と指摘の id をカンマ区切りで。組が本当に成り立つかを確かめる。見て無ければ組を返さない。
3. outside: 同じ環境・仕組み・ツールを作る予定の open な issue と PR を、`gh issue list --state open --search <語>` と `gh pr list --state open --search <語>`（語: 仕組みと、それが要る環境の名前）で探す。当たった物ごとに、向こうの環境に乗れるか、向こうがこちらの部品を使えるかを言う。searched: 探した語（必ず）。
案と組は合わせて {{limit}} 件まで。大事な物を先に。
