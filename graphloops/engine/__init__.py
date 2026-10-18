"""graphloops の実行基盤（engine）。ループの中身を知らない。

3 層に分かれている:
  engine（この package）—— 盤面（board）・穴埋め（render）・型検査（schema）・記録への汎用の書き込み（record）・
    進行（advance）・検証器の呼び方と仕上げ（validator）・回す側が呼ぶコマンド（commands）・rules の読み込み（rules）・
    ユーティリティ（util）。ループのノード名も記録のフィールド名も持たない
  graph（graphs/<loop>.json）—— ノード・依存・役・プロンプト・型・書き込み規則・条件。ループの形はここが正本
  rules（rules/<loop>.py）—— JSON に書けない算術だけ: 記録の初期形、扇の項目の選び方、機械のノード、
    ノードごとの整合の後検査、記録の仕上げ。graph が名前で指し、engine が名前で呼ぶ

入口は scripts/loop.py。
"""
