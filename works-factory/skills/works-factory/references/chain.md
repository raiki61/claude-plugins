# 何周もつなぐ（周の鎖）

1 回の run で閉じなかった残りを、続けて何周も回す時の手順。`WF` はこのプラグインの `bin/works-factory`。

```
WF workflow run works-factory-chain --cwd <対象> --input rounds=<1〜5> --input request=<依頼>
```

- 費用の上限は `--input budget_usd=<USD>` で付ける。
- 1 周が子の run 1 本で、残りが在れば次の周を起動する。
- 周の中の承認ノードには子の run の id で答える（`WF workflow status --cwd <対象>` で見る）。
- 当てるのは鎖の run（`WF apply <鎖の run> --cwd <対象>`）で、採る周までの最後の差分と、周ごとの表 `chain.md` が置き場に出る。
- `--input design_only=true` とは組めない（工場が起動を拒む）。
