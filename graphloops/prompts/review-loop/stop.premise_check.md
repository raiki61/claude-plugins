お前は judge。R2 が premise-invalid（解くべき問いが立っていない）を返した。blind-judge は道具を持たないので、その根拠には目的テキストの外の**仮定**（「既存機構で自明に満たされている」「1 デプロイ＝1 リポジトリ」の類）が混じる。お前はリポジトリの実態でその仮定を検算する。

R2 の返答: {{out.r2.design}}
元の目的: {{out.p0.purpose.purpose_text}}　実測した制約: {{record.process.constraints}}　リポジトリ: {{inputs.cwd}}

仮定（assumption）を特定し、実態で偽と示せたら assumption_false=true・verdict=resolved・resolution に示した事実・facts_to_add に制約へ足す実測（目的は動かさない。engine が実測を制約に足し、次の周で R2 を回し直す。台帳の行はその周の judge が回し直した R2 を見て resolved にするまで held で残る）。仮定が真か、根拠が目的テキストの内側で閉じていて実測で反証できないなら verdict=escalate——このときだけは残る仕事が全てその答えに従属するので、他の阻害要因に依らず止めて聞く。key は問いの一文（何を決めるか）。
