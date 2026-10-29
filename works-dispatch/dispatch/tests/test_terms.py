"""IT の定着語でない言い方の検査と直し（terms.py）。"""

import io
import json
import unittest
from unittest import mock

import terms


class Find(unittest.TestCase):
    def test_words_are_found_outside_quotes_code_and_quoted_lines(self):
        self.assertEqual(terms.line_problems("ブランチを本流に入れる命令"), [("本流", terms.MAIN), ("命令", "コマンド")])
        self.assertEqual(terms.line_problems("「本流に入れる」と `枝` を書く"), [])   # 人の言葉の引用とコード
        self.assertEqual(terms.line_problems("> 本流の枝"), [])                        # 引用の行
        self.assertEqual(terms.line_problems("[^a]: 本流の枝"), [])                    # 脚注の定義
        self.assertEqual(terms.text_problems("一\n手番"), [(2, "手番", "ターン")])

    def test_ordinary_words_that_share_a_letter_are_not_found(self):
        for ok in ("節約する", "受付番号", "一番目", "順番待ち", "根拠", "屋根", "引き起こす", "網羅する", "自分の番の PR",
                   "思い起こす", "障害を起こした", "定番", "出番", "二番", "網掛け", "空欄", "欄外", "根づく", "溜める", "溜め込む",
                   "門番", "連番", "欠番", "何番", "私の番"):
            self.assertEqual(terms.line_problems(ok), [], ok)


class Fix(unittest.TestCase):
    def test_verbs_are_fixed_by_their_form(self):
        cases = {"部署を起こす": "部署を起動する", "起こさない": "起動しない", "起こせる": "起動できる", "起こし方": "起動方法",
                 "起こし直す": "起動し直す", "照らし合わせた": "照合した", "照らしの結果": "照合の結果", "載せ直してから": "リベースしてから",
                 "載せ直せれば": "リベースできれば", "設計書 4 節の決まり": "設計書のセクション 4 の決まり", "タブ欄": "タブバー",
                 "設計の 8 節": "設計のセクション 8", "載せ直し、push する": "リベースし、push する",
                 "載せ直し・赤の直し": "リベース・赤の直し", "載せ直しに巻き込まない": "リベースに巻き込まない",
                 "載せ直し（rebase）、": "リベースし（rebase）、", "溜めの中": "キャッシュの中"}
        for before, after in cases.items():
            self.assertEqual(terms.fix_line(before), after, before)

    def test_former_names_of_department_lifetimes_are_fixed_but_ordinary_words_are_not(self):
        cases = {"常設の部署": "keep の部署", "都度の部署": "tmp の部署", "常設・毎回空": "keep・clear",
                 "担当は常設で 1 人": "担当は keep で 1 人", "常設か都度か": "keep か tmp か", "その都度の部署": "その都度の部署",
                 "その都度確かめる": "その都度確かめる", "常設の展示": "常設の展示",
                 "チェックが毎回空振りする": "チェックが毎回空振りする", "常設の会話": "keep の会話",
                 "常設でない部署": "keep でない部署", "都度とみなす": "tmp とみなす", "常設の役員": "常設の役員",
                 "席が毎回空く": "席が毎回空く", "タンクが毎回空になる": "タンクが毎回空になる", "常設・仮設": "常設・仮設",
                 "常設の席": "常設の席", "エフェメラルの部署": "tmp の部署", "永続かエフェメラルか": "keep か tmp か",
                 "`--ephemeral` でエフェメラルにする": "`--ephemeral` で tmp にする",
                 # 2026-10-29 に残りの寿命の語も英単語にそろえた（永続 → keep・毎回クリア → clear・引き継ぎ → continue・オンデマンド → on-demand）
                 "永続の部署": "keep の部署", "永続・毎回クリア": "keep・clear", "永続・引き継ぎ": "keep・continue",
                 "常設・持ち越し": "keep・continue", "毎回クリアする部署": "clear の部署", "毎回クリアする担当": "clear の担当",
                 "毎回空にする部署": "clear の部署", "オンデマンドの受け持ち": "on-demand の受け持ち", "永続に上げる": "keep に上げる",
                 "状態の永続化": "状態の永続化", "ディスク永続の checkpointer": "ディスク永続の checkpointer",
                 "永続の checkpointer": "永続の checkpointer", "会話の引き継ぎ": "会話の引き継ぎ", "引き継ぎの文": "引き継ぎの文"}
        for before, after in cases.items():
            self.assertEqual(terms.fix_line(before), after, before)
        self.assertEqual(terms.line_problems("毎回空にする部署"), [("毎回空", "clear")])

    def test_a_plan_written_as_a_step_is_fixed_but_steps_and_layers_are_not(self):
        # サブスクのプランの意味の 段 だけを当てる（my_notes の tools/checks/terms.py の項を元にした形）
        cases = {"アカウントごとの契約の段（Max 20x など）": "アカウントごとのプラン（Max 20x など）",
                 "契約の段が引けない": "プランが引けない", "Max 20x の段で動く": "Max 20x のプランで動く",
                 "Max 5X/20X の段": "Max 5X/20X のプラン", "段（Pro・Max）を返す": "プラン（Pro・Max）を返す",
                 "段 (Proの値)": "プラン (Proの値)", "サブスクの段": "サブスクのプラン",
                 "Free の段": "Free のプラン"}
        for before, after in cases.items():
            self.assertEqual(terms.line_problems(before)[0][1], "プラン", before)
            self.assertEqual(terms.fix_line(before), after, before)
        for ok in ("3 段で書く", "段ごとに回す", "tiers の段 2", "段 0〜3 に分けて点検する", "段取り", "契約の段落",
                   "Pro の段階", "料金の段差", "値段と手段", "段（tier）", "段 (Production)",
                   "サブスクを替えて 3 段で書く", "GoPro の段", "アカウントの段ごとに"):
            self.assertEqual(terms.line_problems(ok), [], ok)
            self.assertEqual(terms.fix_line(ok), ok, ok)

    def test_a_word_whose_meaning_splits_is_found_but_not_fixed(self):
        # 網 は通信ならネットワーク、検出の範囲（網に掛かる）ならゲートかテストで、機械では決められない
        self.assertEqual(terms.line_problems("回帰の網に掛かる"), [("網", "ネットワーク（検出の範囲の意味ならゲートかテスト）")])
        self.assertEqual(terms.fix_line("回帰の網に掛かる"), "回帰の網に掛かる")

    def test_ascii_words_get_spaces_only_next_to_japanese_letters(self):
        self.assertEqual(terms.fix_line("本流へ早送りする"), "メインブランチへ fast-forward する")
        self.assertEqual(terms.fix_line("窓口・本流", main="main"), "窓口・main")
        self.assertEqual(terms.fix_line("（本流）", main="main"), "（main）")

    def test_quotes_and_code_are_kept_unless_asked(self):
        self.assertEqual(terms.fix_line("「自分の枝」の枝と `枝`"), "「自分の枝」のブランチと `枝`")
        self.assertEqual(terms.fix_line("```toml"), "```toml")   # 囲みの頭の ``` を崩さない
        self.assertEqual(terms.fix_line("「自分の枝」", quoted=True), "「自分のブランチ」")
        self.assertEqual(terms.fix_line("> 本流の枝"), "> 本流の枝")

    def test_fenced_code_is_neither_found_nor_fixed(self):
        text = '```toml\ndeliver = ["結論", "枝"]\n```\n枝\n'
        self.assertEqual(terms.fix_text(text), '```toml\ndeliver = ["結論", "枝"]\n```\nブランチ\n')
        self.assertEqual(terms.text_problems(text), [(4, "枝", "ブランチ")])


class English(unittest.TestCase):
    """英語の区画（terms: english-begin〜english-end の行の間。AI だけが読む文）。"""

    def test_the_word_list_is_not_applied_inside_and_japanese_outside_quotes_is_found(self):
        text = ("枝\n# terms: english-begin\nAsk the 「窓口」 with `--ask 作業`. 命令\nsend it 本流\n"
                "# terms: english-end\n枝\n")
        self.assertEqual(terms.text_problems(text), [(1, "枝", "ブランチ"), (3, "命令", terms.ENGLISH),
                                                     (4, "本流", terms.ENGLISH), (6, "枝", "ブランチ")])
        self.assertIn("英語の区画に日本語の「命令」がある", terms.describe("命令", terms.ENGLISH))

    def test_an_unclosed_region_is_found_and_the_rest_is_checked_as_japanese(self):
        text = "# terms: english-begin\nok\n枝\n"
        self.assertEqual(terms.text_problems(text), [(1, "terms: english-begin", terms.UNCLOSED), (3, "枝", "ブランチ")])
        # 閉じる前の 2 つ目の始まりは、1 つ目を閉じの無い始まりとして当てる
        text = "# terms: english-begin\n# terms: english-begin\nok\n# terms: english-end\n"
        self.assertEqual(terms.text_problems(text), [(1, "terms: english-begin", terms.UNCLOSED)])

    def test_fix_leaves_the_region_alone(self):
        text = "枝\n# terms: english-begin\n枝\n# terms: english-end\n"
        self.assertEqual(terms.text_problems("印は `# terms: english-begin` の行\n枝\n"), [(2, "枝", "ブランチ")])
        self.assertEqual(terms.fix_text(text), "ブランチ\n# terms: english-begin\n枝\n# terms: english-end\n")

    def test_the_summary_of_a_delivery_does_not_honor_regions(self):
        summary = "## 結論\nterms: english-begin\n枝\nterms: english-end"
        self.assertEqual(terms.deliver_problems({"summary": summary}), ["3 行目: 「枝」は IT の定着語でない。「ブランチ」と書く"])


class Deliver(unittest.TestCase):
    def test_the_summary_of_a_delivery_is_checked(self):
        for summary, code in (("## 結論\n枝を本流に入れた", 1), ("## 結論\n「枝」をブランチに替えた", 0)):
            with mock.patch("sys.stdin", io.StringIO(json.dumps({"summary": summary}))), \
                    mock.patch("sys.stdout", io.StringIO()) as out:
                self.assertEqual(terms.main(["--deliver"]), code, summary)
            if code:
                self.assertIn("「枝」は IT の定着語でない。「ブランチ」と書く", out.getvalue())

    def test_a_payload_that_is_not_an_object_has_no_summary(self):
        for raw in ("[]", '{"summary": 1}'):
            with mock.patch("sys.stdin", io.StringIO(raw)), mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(terms.main(["--deliver"]), 0, raw)

    def test_main_without_a_word_is_refused(self):
        with mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(terms.main(["--fix", "--main"]), 2)
        self.assertIn("--main の後に", out.getvalue())
