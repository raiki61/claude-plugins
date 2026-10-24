"""中心 decide の約束: fixed は後から見た最適の 2 倍未満、問い合わせ口は 2 回に分けて呼べる。"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import rent_or_buy  # noqa: E402


def run(rent, buy, end, **kw):
    """借り賃が一定で、借りる機会が end 回で終わる待ちに fixed を当てた総額と、後から見た最適の額。"""
    spent = 0
    for _ in range(end):
        if rent_or_buy.decide({"rent": rent, "buy": buy, "spent": spent, "certain": True, **kw})["action"] == "buy":
            return spent + buy, min(end * rent, buy)
        spent += rent
    return spent, min(end * rent, buy)


class FixedTest(unittest.TestCase):
    def test_worst_case_is_under_twice(self):
        # 買う費用が借り賃の整数倍でも、そうでなくても、どんな終わりでも 2 倍未満
        for rent, buy in [(1, 10), (1, 24), (2, 7), (3, 100), (5, 5), (7, 3), (1, 1)]:
            for end in range(1, 200):
                cost, best = run(rent, buy, end)
                self.assertLess(cost, 2 * best, (rent, buy, end))

    def test_stops_after_k_rents(self):
        # K = ceil(ρ) − 1 回借りて止まる（ρ = 買う / 借り）
        for rent, buy, k in [(1, 10, 9), (2, 7, 3), (1, 1, 0)]:
            spent = n = 0
            while rent_or_buy.decide({"rent": rent, "buy": buy, "spent": spent, "certain": True})["action"] == "rent":
                spent, n = spent + rent, n + 1
            self.assertEqual(n, k)

    def test_uncertain_needs_hazard_above_cost_ratio(self):
        base = {"rent": 1, "buy": 25, "spent": 0, "certain": False}
        self.assertEqual(rent_or_buy.decide(base)["action"], "buy")
        self.assertEqual(rent_or_buy.decide({**base, "hazard": 0.03})["action"], "buy")
        self.assertEqual(rent_or_buy.decide({**base, "hazard": 0.05})["action"], "rent")
        # 来る見込みがあっても、累計が届けば借りない
        self.assertEqual(rent_or_buy.decide({**base, "hazard": 0.5, "spent": 24})["action"], "buy")

    def test_bad_input_stops_with_reason(self):
        for bad in ({"rent": -1, "buy": 1, "spent": 0, "certain": True},
                    {"rent": 1, "buy": 1, "spent": 0, "certain": "yes"},
                    {"rent": 1, "buy": 1, "spent": 0, "certain": True, "nope": 1},
                    {"rent": 1, "buy": 1, "certain": True},
                    # null を受けるのは hazard だけ
                    {"rent": 1, "buy": 1, "spent": 0, "certain": True, "miss": None},
                    {"rent": None, "buy": 1, "spent": 0, "certain": True},
                    # 形の違う answer は黙って買いにせず止める（関数の返事だけが買いになる）
                    {"rent": 1, "buy": 1, "spent": 0, "certain": True, "ask": True, "defer_limit": 1, "answer": {"go": "yes"}}):
            with self.assertRaises(rent_or_buy.InputError):
                rent_or_buy.decide(bad)
        out = rent_or_buy.decide({"rent": 1, "buy": 9, "spent": 0, "certain": False, "hazard": None})
        self.assertEqual((out["action"], out["reason"]), ("buy", "no_hazard"))

    def test_every_output_has_reason_and_english_why(self):
        base = {"rent": 1, "buy": 5, "spent": 0, "certain": True}
        cases = [({}, "within_buy_cost"), ({"spent": 4}, "reached_buy_cost"),
                 ({"policy": "nope"}, "unknown_policy_fallback"), ({"ask": True, "defer_limit": 1, "spent": 4}, "reached_buy_cost"),
                 ({"ask": True, "defer_limit": 1, "deferred": 1, "spent": 4}, "defer_limit_reached")]
        for extra, reason in cases:
            out = rent_or_buy.decide({**base, **extra})
            self.assertEqual(out["reason"], reason, extra)
            self.assertTrue(out["why"].isascii(), out["why"])


class ConsultTest(unittest.TestCase):
    BUY = {"rent": 1, "buy": 5, "spent": 4, "certain": True, "ask": True, "defer_limit": 2}

    def test_two_step_call(self):
        first = rent_or_buy.decide(self.BUY)
        self.assertEqual((first["action"], first["consult"]), ("buy", True))
        self.assertEqual(rent_or_buy.decide({**self.BUY, "answer": {"go": True}})["reason"], "consult_go")
        go = rent_or_buy.decide({**self.BUY, "answer": {"go": True, "prep": {"focus": "テスト"}}})
        self.assertEqual((go["action"], go["consult"], go["prep"]), ("buy", False, {"focus": "テスト"}))
        wait = rent_or_buy.decide({**self.BUY, "answer": {"go": False, "why": "作業中"}})
        self.assertEqual((wait["action"], wait["consult"], wait["reason"]), ("rent", False, "consult_deferred"))

    def test_limits_skip_asking(self):
        self.assertFalse(rent_or_buy.decide({**self.BUY, "deferred": 2})["consult"])
        self.assertEqual(rent_or_buy.decide({**self.BUY, "deferred": 2})["action"], "buy")
        forced = rent_or_buy.decide({**self.BUY, "forced": True})
        self.assertEqual((forced["action"], forced["consult"]), ("buy", False))
        # 強制は、決め方が借りると言っても買う
        out = rent_or_buy.decide({**self.BUY, "spent": 0, "forced": True})
        self.assertEqual((out["action"], out["reason"], out["consult"]), ("buy", "forced", False))

    def test_function_form(self):
        calls = []

        def ask(x):
            calls.append(x)
            return {"go": False, "why": "あとで"}

        self.assertEqual(rent_or_buy.decide(self.BUY, consult=ask)["action"], "rent")
        self.assertEqual(len(calls), 1)
        # 例外・形の違う返事は、聞かなかったのと同じに買う
        for reply in (lambda x: 1 / 0, lambda x: {"go": "はい"}):
            out = rent_or_buy.decide(self.BUY, consult=reply)
            self.assertEqual((out["action"], out["consult"], out["reason"]), ("buy", False, "consult_unreadable"))


if __name__ == "__main__":
    unittest.main()
