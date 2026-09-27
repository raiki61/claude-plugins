# 最終報告の冒頭——人が決めること（writer の仕事。まず本文だけを書く）

問いの台帳: {{record.questions | pick key,kind,status,reason,resolution,options,depends,origin}}
根本ユニット: {{record.units | pick key,label,disposition}}
記録の process（**置き場と 1 行要約**。要る所だけ Read で読め）: {{ref:record.process}}
盤面: 周 {{round}}／{{loop | pick outcome,stop_reason,escalated,open_units,purpose_known,purpose_unusable}}
止めた所と理由（無ければ空）: {{?record.process.halted}}
最後の周の検証器の出力（履歴）: {{?out.p4.record.out}}
言語: {{inputs.lang}}

**冒頭 3 行は「人が決めること」だけ**——台帳で held / escalate のもの（別 PR に積むか・どの観点を見直すか・設計の岐路・前提不成立・誰がどこで動かすか）。盤面の stop_reason が gates_deferred（init --input gates=merge で変異の検算を合流に回した run）なら、「合流した版を gates=merge 無しの run で回し、最後の関門（最終のコードで変異の検算を撃ち直す）を通す——収束と言えるのはその run だけ。差分がゲートに触れていたなら、P1 のゲートの検算もその run で撃つ」を 1 項として必ず入れる。盤面の stop_reason が stop（人が途中で止めた run）なら、止めた周・理由の本文・答えないまま外した問い（unanswered）を 1 項として必ず入れる——続けるなら新しい run を始めること、止めた周の工程は走っていないこと（記録の not_run）も添える。無ければ「人が決めることは無い」と 1 行。台帳で resolved / decided にした問いは「ループが自分で決めたこと」として根拠つきで冒頭の直後に。

人に聞くところは、ループを見ていない人が初見で読んで決められる形に: ①急ぐものと後でよいものを分け、件数を先に言う ②1 件ずつ独立して読める ③1 件につき、何を決めるのか・なぜこれが出てきたか（きっかけの実物）・選択肢ごとに何が起きるか・決めないと何が止まるか ④選ぶ側の材料を出す——ただし書いてよいのは judge が台帳に書いた options と reason だけで、writer が新たに 1 つを推すな。**内部の語彙（[block]・do-now・defer・零処方・R1〜R4・素材名・安定キー）で書かれた問いは、それだけでは決められない。** 返答はこの部分の本文そのもの（Markdown）。
