# ほかのプラグインから tiers を使う形

プラグインを作る人向け。使い方は [README](../README.md)。

works-dispatch が最初につないだ（`--check`）。ほかのプラグインは、次の形でつなぐ。

1. 自分の要る段を決め、README に「要る段: N」と書く。段は、使う外の道具のうち最も上の物で決める（gh だけなら 1、herdr を操るなら 2、Archon を起こすなら 3）。
2. `plugin.json` の `dependencies` に `{"name": "tiers", "marketplace": "raiki61"}` を足す（`version` は書かない。[design.md](design.md) の「置き場」）。
3. 使い始めの確かめ（`--check` のような入口か、スキルの最初の手順）で `tiers --tier N --json` を呼ぶ。Python から呼ぶなら、PATH の上の拡張子の無い `tiers` を探して `sys.executable` で起こす（Windows の `shutil.which` は拡張子で探すので見つけない）。リポジトリの checkout から走らせる試験と開発のために、隣の `tiers/bin/tiers` も探す。works-dispatch の [`dispatch/tierx.py`](../../works-dispatch/dispatch/tierx.py) がその形。
4. `ok` が false なら、`checks[]` の `ok: false` の項目の `problem` と `fix` を出して止まる。`tiers` が見つからない・形が違うときは、止めずに注記にし、そのプラグインの今までの確かめを続ける（依存が入っていない古い入れ方でも、今ある確かめを減らさない）。
5. スキルだけのプラグイン（スクリプトを持たない）は、スキルの最初の手順に「`tiers --tier N` を走らせ、足りなければ出力の入れ方を見せて止まる」と書く。

まだつないでいないプラグインと、つなぐときの注意:

- works（darkfactory）: 要る段は 3 に見えるが、works は Archon を自分で取ってきて隔離した家に置く（`works/dev/archon.sh`）ので、PATH の `archon` を要らない。つなぐときは段 1（gh。Archon を gh release で取るため）と works の自前の確かめ（uv と claude）にするか、tiers に「Archon を自分で取る」場合の点検を足すかを、works の側で決める。
- attention（whose-turn・catchup）: gh を使うので段 1。
- convergence-loops・graphloops・gates: gh で PR を読む・投稿する所が有る。段 0 か 1 かは、gh が無いときに何が止まるかを各プラグインで見て決める。
