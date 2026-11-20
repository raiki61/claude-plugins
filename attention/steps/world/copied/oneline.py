"""字を 1 行に畳む口。前は lib の多くのモジュールが同じ中身の写し（" ".join(str(x).split())）を持っていた。振る舞いが同じ写しだけを
ここに寄せ、振る舞いの違う畳み（色の制御文字を除く cite.flat・NFKC に揃える cite.fold・None を空にする gatemarks._squeeze など）は
持ち主のモジュールに名で残す。

- one_line(text): str(text) の空白（改行・タブを含む）の並びを 1 つの空白に詰め、両端を落とした字

標準ライブラリだけ（lib のほかの物を import しない）。
"""


def one_line(text) -> str:
    return " ".join(str(text).split())
