# PR の差分だけを見せて回す

依頼のファイルを渡さず、PR の差分を工場に見せて、直す所を工場自身に見つけさせる入口。`WF` はこのプラグインの `bin/works-factory`。

```
WF workflow run works-factory-line --cwd <PR の head のブランチを checkout した作業ツリー> --input pr=<番号> [--input test_cmd=<試験のコマンド>]
```

- `request` は渡さない。PR は `--input pr=<番号>` で名指す。
- `--cwd` は、その PR の head のブランチを checkout した作業ツリーにする。run は `gh` のログインで PR の base と head を読み、PR の head の commit が `--cwd` で checkout した commit（対象の `HEAD`）と違えば止まる。
- run の始めに、入口の検査（AI の役が動く前に入力を確かめる所）が 1 行を出し、その行は「diff <base>..HEAD (N files), 0 requests」になる。依頼の行が 0 件の run で正しく、判定の段は PR の差分だけを見る。

## 入口が断る形

- `--input request=<ファイル>` で、ファイルの中が `{"pr": [<番号>]}` だけの物。依頼のファイルの中の `pr` は前の run から持ち越す番号で、差分を名指す物ではない。依頼の行が無く、`base` も `pr` の入力も無いと差分が空になり、空の run として断られる。PR は `--input pr=<番号>` で名指す。
- `--input request=<ファイル>` で、`findings` が空で、ほかの項目（`pr`・`issue`・`answers`・`prior_failures`・`constraints`・`theme`）も全部空の物（`{"findings": []}` など）。入れ物だけで中身が無く、判定の段が観点を全部回した後に依頼の所で止まるので、AI が動く前に入口が断る。PR の差分だけを見せるなら、上の形のとおり `request` を渡さない。依頼のファイルを渡すなら中身を書く。`findings` が空でもほかの項目が在る物（工場が自分で書く次の run の依頼のファイル）は通る。
- `--input base=<版>` と `--input pr=<番号>` を一緒に渡す形。2 つの別の差分を名指すので、どちらを使うか決まらない。片方だけ渡す。

詳しくは取り置きの工場の `README.md` の「Showing the factory one PR and letting it find what to fix」。
