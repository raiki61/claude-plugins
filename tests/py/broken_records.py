#!/usr/bin/env python3
"""記録の検証器 review-record.py に渡す「壊した記録」を作る（ルートの検査の新旧が同じ作り方を読む 1 か所）。

読む側は 2 つ: tests/run.sh の write_broken_records（子プロセスで `python3 tests/py/broken_records.py <ROOT> <WORK>`）と、
tests/py/conftest.py の fixture（同じプロセスで write_all を呼ぶ）。作る物の名前（<WORK> の直下のディレクトリ名・
deep.json・unreadable）は、tests/run.sh の research-record.py・doctor-record.py の節も使うので変えない。

**束ねてよいのは素材の生成だけ。** 検査そのものはケースごとに分けたまま——合否が個別に報告されることが要件で、
束ねると失敗の切り分けができなくなる。生成を 1 ケース 1 プロセスにすると Python の起動コストだけで 26 秒かかる
（実測。まとめて 1.2 秒）。
"""
import json
import pathlib
import sys

# 手書きの deep copy を 1 本に寄せる（同じ形が 20 箇所に散っていた）。`copy.deepcopy` でなく
# JSON 往復にするのは、**JSON にできない値をここで落とすためではなく、そこで失敗させるため**
# ——固定具は記録として書き出されるので、JSON 化できない値が混ざったら複製の時点で
# TypeError で止まる方がよい（deepcopy は通してしまい、書き出しの段で初めて落ちる）。
def clone(x):
    return json.loads(json.dumps(x))


def write_all(root, work):
    """<root>/templates の雛形から壊した記録を <work> の下に書く（<work> は在る空のディレクトリ）。"""
    root, work = pathlib.Path(root), pathlib.Path(work)
    templates = {
        n: json.loads((root / f"templates/{n}.example.json").read_text(encoding="utf-8"))
        for n in ("round-1", "round-2", "round-3")
    }


    def defer_unit(rec):
        return next(u for u in rec["units"] if u.get("disposition") == "defer")


    # 値を書き換えるだけの mutation（round-2 を壊し、round-1 と突合する）。個別の欄の検査を発火させる。
    VALUE = {
        "drop-material": lambda r: r["materials"].pop("hygiene"),
        "drop-defer-reason": lambda r: defer_unit(r).pop("reason"),
        "drop-base": lambda r: r.pop("base"),
        "drop-round": lambda r: r.pop("round"),
        "bad-base": lambda r: r.update(base="1" * 40),
        "bad-round": lambda r: r.update(round=9),
        "bad-status": lambda r: r["materials"]["hygiene"].update(status="probably-fine"),
        "clean-without-checked": lambda r: r["materials"]["hygiene"].pop("checked"),
        # ラベルと key の検査は、消えても記録が「阻害要因なし（exit 0）」で通ってしまう
        # ——[block] が黙って数えられなくなる、この道具の存在理由そのものの穴。
        "bad-label": lambda r: r["units"][0].update(label="blocker"),
        "drop-key": lambda r: r["units"][0].pop("key"),
        # R1〜R4 の verdict。欄ごと無い・1 つ欠ける・語彙外・役に許されない値。
        "drop-reviews": lambda r: r.pop("reviews"),
        "drop-review-R3": lambda r: r["reviews"].pop("R3"),
        "bad-review-status": lambda r: r["reviews"]["R1"].update(status="looks-fine"),
        "review-only-R2": lambda r: r["reviews"]["R1"].update(status="premise-invalid"),
        "review-only-R34": lambda r: r["reviews"]["R1"].update(status="not_applicable"),
        "pass-without-reason": lambda r: r["reviews"]["R3"].pop("reason"),
        # 持ち越し。from_round が無い・今ラウンド以降を指す・前ラウンドに判定が無い素材から持ち越す。
        "carry-without-from": lambda r: r["materials"]["prior_decisions"].pop("from_round"),
        "carry-from-future": lambda r: r["materials"]["prior_decisions"].update(from_round=2),
        "carry-from-not-applicable": lambda r: r["materials"]["procedure_trace"].update(
            status="carried_over", from_round=1, reason="前と同じ"
        ),
    }
    # 「型が違う」系。値の書き換えだけでは個別の型検査が一度も発火しない。
    TYPE = {
        "bad-round-type": lambda r: r.update(round="2"),
        "bad-round-bool": lambda r: r.update(round=True),
        "round-below-one": lambda r: r.update(round=-100),
        "bad-materials-type": lambda r: r.update(materials=[]),
        "bad-units-type": lambda r: r.update(units={}),
        "bad-unit-type": lambda r: r["units"].__setitem__(0, "not-an-object"),
        "bad-reviews-type": lambda r: r.update(reviews=[]),
        "bad-from-round-type": lambda r: r["materials"]["prior_decisions"].update(from_round="1"),
    }
    # 個別の検査を通り抜け、末尾の例外境界だけが受け止めるもの。
    BOUNDARY = {
        "bad-scalars-type": lambda r: r.update(scalars=["oops"]),
        # `"scalars": null` は JSON として正当なので、falsy 正規化をやめた後は境界の
        # 「想定外の例外」に倒れていた。書き手に何を直せばよいかを伝える診断が要る。
        "null-scalars": lambda r: r.update(scalars=None),
        "unhashable-status": lambda r: r["materials"]["hygiene"].update(status=["found"]),
    }


    def write(name, rec, num=2, prevs=None):
        """壊した記録を、記録のディレクトリ 1 つとして書き出す（入口はディレクトリだけ）。

        前のラウンドを無傷のテンプレートで埋めるのは、突合（base の一致・持ち越しの連鎖・
        defer 台帳・残存）を発火させる mutation があるため。`prevs` を渡すとその番号だけ差し替える。
        round 欄そのものを壊した mutation も、ファイル名は round-<num> に置く——load_dir が
        「ファイル名の番号と中身の round が違う」で落とす前に validate が走るので、狙った検査は
        変わらず発火する。
        """
        d = work / name
        d.mkdir(exist_ok=True)
        for i in range(1, num):
            r = (prevs or {}).get(i, templates[f"round-{i}"])
            (d / f"round-{i}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        (d / f"round-{num}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


    for name, mutate in {**VALUE, **TYPE, **BOUNDARY}.items():
        rec = clone((templates["round-2"]))
        mutate(rec)
        write(name, rec)

    # 最上位が object でない記録は mutate 関数の形（rec を書き換える）に乗らないので別に書く。
    write("not-object", ["not", "an", "object"], num=1)

    # 突合（集合演算）は prev だけを走査するので、前ラウンド側の記録を壊す必要がある。
    prev = clone((templates["round-1"]))
    prev["units"][0]["key"] = ["not", "a", "string"]
    write("unhashable-key", templates["round-2"], prevs={1: prev})

    # round-1 単独。初回に持ち越しは書けない（from_round が指せるラウンドが無い）。
    r1 = clone((templates["round-1"]))
    r1["reviews"]["R1"].update(status="carried_over", from_round=1, reason="前と同じ")
    write("r1-carry", r1, num=1)

    # round-3 を壊し、round-2 と突合する——連鎖・defer 台帳・P-R の飛ばし・停止条件は
    # 2 ラウンド目以降の記録でしか発火しない。
    def r3(mutate):
        rec = clone((templates["round-3"]))
        mutate(rec)
        return rec

    deferred_key = defer_unit(templates["round-2"])["key"]
    for name, mutate in {
        # 前ラウンドが round 1 から持ち越しているのに、今ラウンドが round 2 からと書く。
        "carry-chain-broken": lambda r: r["materials"]["prior_decisions"].update(from_round=2),
        # R1 は「台帳に問いが載った周」なので round-3 の実例では pass。持ち越しの連鎖は R2 で見る。
        "review-carry-chain-broken": lambda r: r["reviews"]["R2"].update(from_round=1),
        # 前ラウンドで defer と確定したキーが、新証拠なしに [block] へ上がる。
        "reopen-without-evidence": lambda r: defer_unit(r).update(label="block"),
        # 新証拠つきの再審は記録として正しく、阻害要因（exit 1）として出る。
        "reopen-with-evidence": lambda r: defer_unit(r).update(
            label="block", reopen_evidence="本番ログで上限超過のクエリを 3 件観測"
        ),
        # 阻害要因ゼロなのに R3 が未実施——P-R を飛ばした形。
        "skip-PR": lambda r: r["reviews"]["R3"].update(status="not_applicable", reason="到達せず"),
        "redesign": lambda r: r["reviews"]["R2"].update(status="redesign-needed", reason="機構の規模が実態に対して大きい"),
        # 人に諮る verdict は台帳に問いとして載っていること（載っていない形は q-review-unlisted）。
        "premise-invalid": lambda r: (r["reviews"]["R2"].update(status="premise-invalid", reason="1 デプロイ 1 リポジトリなので記録する問いが無い"),
            r["questions"].append({"key": "解くべき問いが立っているか", "kind": "premise", "origin": "R2",
                                   "status": "held", "reason": "judge が仮定を検算中"})),
        "unverifiable": lambda r: (r["reviews"]["R2"].update(status="unverifiable", reason="目的テキストの出典が無い"),
            r["questions"].append({"key": "元の目的をどこから取るか", "kind": "unverifiable", "origin": "R2",
                                   "status": "held", "reason": "出典が無い"})),
        "review-not-run": lambda r: r["reviews"]["R4"].update(status="not_run", reason="時間切れ"),
        # 前ラウンドの [block] キーがそのまま残る（stuck）。3 周続くので台帳への記載も要る（無い形は q-stuck-unlisted）。
        "stuck": lambda r: (r["units"].append({"key": templates["round-1"]["units"][0]["key"], "label": "block"}),
            r["questions"].append({"key": "分岐の統合が 2 周直しても残る——処方の誤りか設計か", "kind": "stuck",
                                   "origin": templates["round-1"]["units"][0]["key"], "status": "held",
                                   "reason": "2 周連続で残った"})),
        # defer のキーが今ラウンドの記録から消えた——台帳には残ることを出力で知らせる。
        "defer-dropped": lambda r: r["units"].remove(defer_unit(r)),
        # 素材の「人の起動待ち」「やるべきだったが飛ばした」。このループが塞いだと主張する穴
        # （無言の省略を「なし」と誤認する）の当の腕で、記録の実例が 1 件も無かった。
        "material-awaiting": lambda r: (r["materials"]["consistency"].update(
            status="awaiting_human", reason="grader が権限エラーで起動できなかった"),
            r["questions"].append({"key": "整合性の grader を誰が起動するか", "kind": "awaiting",
                                   "origin": "consistency", "status": "held", "reason": "権限エラー"})),
        "material-not-run": lambda r: r["materials"]["hygiene"].update(
            status="not_run", reason="時間切れで飛ばした"),
        # 同じ key が 1 ラウンドに 2 つ在ると、履歴も台帳も後勝ちで潰れる。
        "dup-key": lambda r: r["units"].append(clone((r["units"][0]))),
        # 「見つけた」と書いた素材が在るのに units が空。
        "found-no-units": lambda r: (
            r["materials"]["local_review"].update(
                status="found", count=3, detail="欠陥レビューが 3 件返した"),
            r["units"].clear(),
            # units を空にすると、今ラウンドに初出の defer（split の origin）は台帳にも無くなる。
            # 見たいのは「found なのに units が空」なので、その問いだけ外す（前ラウンドから
            # 続く fork は defer 台帳に origin が在るので残せる）。
            r["questions"].__setitem__(slice(None), [q for q in r["questions"] if q["kind"] != "split"])),
    }.items():
        # stuck は round-2 側にも同じ [block] が在ることが前提なので、そこだけ差し替える。
        r2 = clone((templates["round-2"]))
        r2["units"].append({"key": templates["round-1"]["units"][0]["key"], "label": "block"})
        write(name, r3(mutate), num=3, prevs={2: r2} if name == "stuck" else None)

    # 問いの台帳（1 ラウンド内）。何が不正かは下の CASES 表と review-record.py の診断文が持つ。
    def add_q(r, **q):
        r["questions"].append(q)
    # この節と、下の周またぎの節の両方で使う（同じ値を 2 度定義しない）。
    BK = "src/api/limit.py:apply — 上限が効かない"
    NIT_KEY = next(u["key"] for u in templates["round-2"]["units"] if u["label"] == "nit")
    for name, mutate in {
        "q-split-on-do-now": lambda r: (add_q(r, key="別 PR に積むか", kind="split", origin=defer_unit(r)["key"],
                                              status="held", reason="目的の外"),
                                        defer_unit(r).update(disposition="do-now")),
        # do-now でなく **label が block** の腕。上の q-split-on-do-now は suggest/do-now しか通さない。
        "q-split-on-block": lambda r: (r["units"].append({"key": BK, "label": "block"}),
            add_q(r, key="別 PR に積むか", kind="split", origin=BK, status="held", reason="目的の外")),
        "q-bad-kind": lambda r: add_q(r, key="x", kind="skip", origin=NIT_KEY, status="held", reason="r"),
        "q-bad-status": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="pending", reason="r"),
        "q-without-reason": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held"),
        "q-fork-one-option": lambda r: add_q(r, key="x", kind="fork", origin=defer_unit(r)["key"],
                                             status="held", reason="r", options=["(A) だけ"]),
        "q-resolved-without-resolution": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY,
                                                         status="resolved", reason="r"),
        "q-origin-missing": lambda r: add_q(r, key="x", kind="fork", origin="src/none.py — 無い",
                                            status="held", reason="r", options=["(A) a", "(B) b"]),
        "q-awaiting-unlisted": lambda r: (r["questions"].clear(),
            r["materials"]["main_path_observation"].update(status="awaiting_human", reason="実機が要る")),
        "q-awaiting-origin-clean": lambda r: add_q(r, key="x", kind="awaiting", origin="hygiene", status="held", reason="r"),
        "q-review-unlisted": lambda r: r["reviews"]["R1"].update(status="unverifiable", reason="出典が無い"),
        "q-premise-origin-mismatch": lambda r: add_q(r, key="x", kind="premise", origin="R2", status="held", reason="r"),
        "q-dup-key": lambda r: (add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held", reason="r"),
                                add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held", reason="r")),
        "q-legacy-ask-human": lambda r: next(u for u in r["units"] if u["label"] == "nit").update(ask_human="rule", reason="r"),
        "q-not-list": lambda r: r.update(questions={}),
        "q-drop": lambda r: r.pop("questions"),
        # 以下は 0.28 で足した検査のうち、腕が無かったもの。腕が無いと、検査を消しても全件緑になる
        # （実測で 6 本がそうだった）。どれも「記録を静かに間違わせる」向きなので、1 本ずつ赤を見る。
        "q-not-object": lambda r: r["questions"].append("問い"),
        "q-no-key": lambda r: add_q(r, kind="rule", origin=NIT_KEY, status="held", reason="r"),
        "q-empty-reason": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held", reason=""),
        "q-depends-type": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held",
                                          reason="r", depends="まとめて 1 本の文字列"),
        "q-fork-options-type": lambda r: add_q(r, key="x", kind="fork", origin=defer_unit(r)["key"],
                                               status="held", reason="r", options="(A) と (B)"),
        "q-origin-field-missing": lambda r: add_q(r, key="x", kind="stuck", status="held", reason="r"),
        "q-awaiting-origin-not-material": lambda r: add_q(r, key="x", kind="awaiting",
                                                          origin="main_path", status="held", reason="r"),
        "q-review-origin-not-r": lambda r: add_q(r, key="x", kind="premise", origin="R9",
                                                 status="held", reason="r"),
        # thrash は出どころを持たない種類。origin を許すと、帰属と stuck の縛りをそこから外せる。
        # **depends も同じ入口**——origin だけ塞いでいたとき、ここから開いた [block] 全件に帰属が付いた。
        "q-thrash-with-origin": lambda r: add_q(r, key="x", kind="thrash", origin=NIT_KEY,
                                                status="held", reason="r"),
        "q-thrash-with-depends": lambda r: (r["units"].append({"key": BK, "label": "block"}),
            add_q(r, key="x", kind="thrash", status="held", reason="r", depends=[BK])),
        # 非 unit 域の depends も実在検査に掛かる（綴り違いが黙って無効にならない）。
        # options / depends の「要素の型・空文字」（len < 2 と「配列でない」には腕が在った）。
        "q-fork-options-empty-item": lambda r: add_q(r, key="x", kind="fork", origin=defer_unit(r)["key"],
                                                     status="held", reason="r", options=["(A) a", ""]),
        "q-depends-item-type": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held",
                                               reason="r", depends=[1]),
        # 逆向きの掲載要求の premise 側（unverifiable 側だけ腕が在った。表 1 つに畳んだのは
        # 「逆向きだけ直し忘れたときに落ちない穴」を塞ぐためなのに、順方向の片腕が空いていた）。
        "q-premise-unlisted": lambda r: r["reviews"]["R2"].update(
            status="premise-invalid", reason="解くべき問いが立っていない"),
        "q-awaiting-depends-missing": lambda r: (
            r["materials"]["main_path_observation"].update(status="awaiting_human", reason="実機が要る"),
            add_q(r, key="主経路を誰がどこで動かすか", kind="awaiting", origin="main_path_observation",
                  status="held", reason="動かせない", depends=["src/typo.py — 存在しないキー"])),
        # 逆向きの対応表のうち unverifiable 側（premise 側は q-premise-origin-mismatch が見ている）。
        "q-review-origin-status-unverifiable": lambda r: add_q(r, key="x", kind="unverifiable",
                                                               origin="R2", status="held", reason="r"),
        # 問いの key が unhashable。契約（2）を担保するのは末尾の境界だけなので、units 側と同じ
        # 形が questions 側にも要る（非対称のまま放置すると、どちらかだけが守られていると読める）。
        "q-unhashable-key": lambda r: add_q(r, key=["x"], kind="thrash", status="held", reason="r"),
        # 開いたユニットへの帰属禁止は origin だけでなく depends にも当たる。origin を許される先
        # （nit）にしておいて depends から開いた [block] を掴むのが、塞ぎ残しの当の形。
        "q-no-open-via-depends": lambda r: (r["units"].append({"key": BK, "label": "block"}),
            add_q(r, key="どの観点を見直すか", kind="rule", origin=NIT_KEY, status="held",
                  reason="同じ指摘が新証拠なく再燃", depends=[BK])),
        # 逆向きの掲載要求も未決で数える。閉じた問いを置いても、素材が人の起動待ちなら満たされない。
        "q-awaiting-listed-resolved": lambda r: (
            r["materials"]["main_path_observation"].update(status="awaiting_human", reason="実機が要る"),
            add_q(r, key="主経路を誰がどこで動かすか", kind="awaiting", origin="main_path_observation",
                  status="resolved", reason="起動できなかった", resolution="テスト用設定で起動できる")),
    }.items():
        rec = clone((templates["round-2"]))
        mutate(rec)
        write(name, rec)

    # ディレクトリ渡し（履歴）。何を見る組かは各 expect_output の説明文が持つ。
    def hist(name, recs):
        d = work / name
        d.mkdir()
        for rec in recs:
            (d / f"round-{rec['round']}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

    hist("tmpl-1", [templates["round-1"]])
    hist("tmpl-12", [templates["round-1"], templates["round-2"]])
    full = [templates["round-1"], templates["round-2"], templates["round-3"]]
    hist("hist", full)
    hist("hist-gap", [templates["round-1"], templates["round-3"]])
    back = clone((templates["round-3"]))
    back["units"].append({"key": templates["round-1"]["units"][0]["key"], "label": "nit"})
    hist("hist-return", [templates["round-1"], templates["round-2"], back])

    def r1_at(n, units):
        r = clone((templates["round-1"]))
        r["round"] = n
        r["units"] = units
        # 中立な土台にする。round-1 の実例が持つ「人の起動待ちの素材と、その問い」を外し、
        # **found の素材も落とす**——found が残ると、units を空にした fixture に「素材が found なのに
        # units が空」という 2 つ目の阻害が常に立ち、帰属を狙った検査が狙いの分岐に決して入らない
        # （実測: その形で、当の欠陥を注入しても全件緑のままだった）。
        for name, m in r["materials"].items():
            if m["status"] in ("found", "awaiting_human"):
                r["materials"][name] = {"status": "clean", "checked": "見たが無かった"}
        r["questions"] = []
        return r

    LK = "src/db/pool.py — 接続プールの上限を設定に出す"
    # 別のレビュー（基準点が違う）の記録が同じディレクトリに残っている。
    mixed = clone((templates["round-2"]))
    mixed["base"] = "f" * 40
    hist("mixed-base", [templates["round-1"], mixed])

    hist("block-dropped", [r1_at(1, [{"key": BK, "label": "block"}]), r1_at(2, [])])

    # `human-repeat` と、下の問いの節の `q-review-attribution` は同一内容だった（定数 QU / RUQ も
    # 全欄一致）。実体が 1 つなので、1 つのディレクトリに腕を 2 本掛ける形に畳んである。
    QU = {"key": "元の目的をどこから取るか", "kind": "unverifiable", "origin": "R1",
          "status": "held", "reason": "出典①②③のどれも無い"}
    ch = r1_at(1, [])
    ch["reviews"]["R1"] = {"status": "unverifiable", "reason": "目的テキストの出典が取れない"}
    ch["questions"] = [QU]
    ch2 = r1_at(2, [])
    ch2["reviews"]["R1"] = {"status": "carried_over", "from_round": 1,
                            "reason": "再発火条件に当たらないので round 1 の判定を流用"}
    hist("carry-from-human", [ch, ch2])
    # 正直な書き方＝同じ値をもう一度書く。諮る義務が続いていることが毎ラウンド数えられる。
    ch3 = r1_at(2, [])
    ch3["reviews"]["R1"] = {"status": "unverifiable", "reason": "出典は今ラウンドも取れていない"}
    ch3["questions"] = [QU]
    hist("human-repeat", [ch, ch3])

    # 問いの台帳の周またぎと帰属。
    def with_q(rec, *qs):
        rec["questions"] = list(qs)
        return rec
    FQ = {"key": "上限をどこで掛けるか", "kind": "fork", "origin": BK, "status": "held",
          "reason": "共有面に及ぶ", "options": ["(A) 入口 → 全経路に効く", "(B) 各経路 → 漏れる"]}
    BK2 = "src/api/sort.py:order — 並び順が指定を無視する"
    TWO = [{"key": BK, "label": "block"}, {"key": BK2, "label": "block"}]
    STUCK3 = [{"key": BK, "label": "block"}]
    hist("q-dropped", [with_q(r1_at(1, [{"key": BK, "label": "block"}]), FQ),
                       r1_at(2, [{"key": BK, "label": "block"}])])
    hist("q-dropped-escalate", [
        with_q(r1_at(1, [{"key": BK, "label": "block"}]), dict(FQ, status="escalate")),
        r1_at(2, [{"key": BK, "label": "block"}])])
    hist("q-depends-missing", [
        with_q(r1_at(1, TWO), dict(FQ, depends=["src/api/typo.py — 存在しないキー"])),
        with_q(r1_at(2, TWO), dict(FQ, depends=["src/api/typo.py — 存在しないキー"]))])
    # 決着しても出どころが開いているうちは `decided`。**これは台帳から降りていないので要求を満たす**
    # （判断の付いた問いを「未決」と書かされる形が、2 軸に割ったことで消えた）。
    hist("q-stuck-decided", [
        r1_at(1, STUCK3), r1_at(2, STUCK3),
        with_q(r1_at(3, STUCK3), dict(FQ, status="decided", resolution="入口に寄せると決めた"))])
    # 出どころが開いたまま `resolved` と書くのは記録の不正（2 軸目は記録から判定する）。
    hist("q-resolved-while-open", [
        r1_at(1, STUCK3), r1_at(2, STUCK3),
        with_q(r1_at(3, STUCK3), dict(FQ, status="resolved", resolution="入口に寄せると決めた"))])
    hist("q-stuck-other-kind", [
        r1_at(1, STUCK3), r1_at(2, STUCK3),
        with_q(r1_at(3, STUCK3), {"key": "新規が出続ける", "kind": "thrash",
                                  "status": "held", "reason": "件数が落ちない"})])
    # ここだけ検査がゼロだと、unverifiable だけが残る周が永久に聞かれない形を誰も止められない。
    # `human-repeat` と同じ内容の固定具がここにもう 1 つ在った（定数まで全欄一致）。実体が
    # 1 つなので、1 つのディレクトリに腕を 2 本掛ける形に畳んである（片方だけ直しても検査が
    # 変わらない形を残さない）。
    # awaiting は雛形に実在する最も普通の問いなのに、ここだけ腕が無かった。
    am1 = r1_at(1, [])
    am1["materials"]["main_path_observation"] = {"status": "awaiting_human", "reason": "実機が要る"}
    am2 = r1_at(2, [])
    am2["materials"]["main_path_observation"] = {"status": "awaiting_human", "reason": "今も実機が要る"}
    AMQ = {"key": "主経路を誰がどこで動かすか", "kind": "awaiting", "origin": "main_path_observation",
           "status": "held", "reason": "この環境では動かせない"}
    hist("q-material-attribution", [with_q(am1, AMQ), with_q(am2, AMQ)])
    # 2 周目以降だけに掛けると初回が素通りする。
    hist("q-origin-missing-round1", [with_q(r1_at(1, [{"key": BK, "label": "block"}]),
                                            dict(FQ, origin="src/none.py — 無い"))])
    PMQ = {"key": "解くべき問いが立っているか", "kind": "premise", "origin": "R2",
           "status": "held", "reason": "judge が仮定を検算中"}
    def premise_round(n):
        r = r1_at(n, [{"key": BK, "label": "block"}])
        r["reviews"]["R2"] = {"status": "premise-invalid", "reason": "問いが立っていない"}
        return with_q(r, PMQ)
    # 短絡すると文言が「前提不成立が確定（escalate）」に変わるので、この期待で status 条件を縛れる。
    hist("q-premise-not-escalate", [premise_round(1), premise_round(2)])
    def esc_round(n):
        return with_q(r1_at(n, [{"key": BK, "label": "block"}]), dict(FQ, status="escalate"))
    hist("q-escalate-not-premise", [esc_round(1), esc_round(2)])
    hist("q-stuck-unlisted", [r1_at(n, [{"key": BK, "label": "block"}]) for n in (1, 2, 3)])
    # 帰属は前の周から持ち越した保留にだけ付くので、聞く時を見る fixture は 2 周以上にする。
    hist("q-stuck-listed", [r1_at(1, [{"key": BK, "label": "block"}]),
                            with_q(r1_at(2, [{"key": BK, "label": "block"}]), FQ),
                            with_q(r1_at(3, [{"key": BK, "label": "block"}]), FQ)])
    hist("q-mixed", [with_q(r1_at(n, TWO), FQ) for n in (1, 2)])
    hist("q-depends", [with_q(r1_at(n, TWO), dict(FQ, depends=[BK2])) for n in (1, 2)])
    # 立った周には聞かない。同じ形を 1 周だけにすると、帰属でなく「今ラウンドに立った問い」の印が付く。
    hist("q-fresh", [with_q(r1_at(1, TWO), dict(FQ, depends=[BK2]))])
    pe = r1_at(1, [{"key": BK2, "label": "block"}])
    pe["reviews"]["R2"] = {"status": "premise-invalid", "reason": "1 デプロイ＝1 リポジトリなら識別子は要らない"}
    hist("q-premise-escalate", [with_q(pe, {"key": "解くべき問いが立っているか", "kind": "premise", "origin": "R2",
                                            "status": "escalate", "reason": "judge が仮定を実態で確かめた——真"})])
    # ループが決めた問い（resolved）は帰属しない＝その阻害は「仕事」。**肯定の文言で確かめる**——
    # 「出ないこと」を見る形にすると、対象が消えても異常終了しても緑になる（実測でそうなった）。
    # 2 周とも held の Q1 は帰属するので、resolved の Q2 が帰属したら「帰属しない 0 件」になって
    # 文言が変わる。つまりこの 1 本で、resolved を数えたら赤くなる。
    RQ = {"key": "並び順をどう直すか", "kind": "fork", "origin": BK2,
          "reason": "候補が 2 つ", "options": ["(A) 入口", "(B) 各経路"]}
    hist("q-resolved-is-work", [
        with_q(r1_at(1, TWO), FQ, dict(RQ, status="held")),
        with_q(r1_at(2, TWO), FQ, dict(RQ, status="decided", resolution="入口に寄せると決めた")),
    ])

    # 出どころの域が違えば、値が文字列として同じでも別物である。unit の key をリテラル "R2" に
    # しても、別の域の問い（premise の origin="R2"）はそのユニットを指したことにならない。
    # 平坦な文字列で突き合わせていたとき、これが 3 周続いた [block] の振り分け要求を黙らせる
    # 逃げ道だった（実測で再現）。名前を禁じる柵でなく、域を持ち回る構造で保証している。
    kc = [r1_at(n, [{"key": "R2", "label": "block"}]) for n in (1, 2, 3)]
    kc[2]["reviews"]["R2"] = {"status": "premise-invalid", "reason": "解くべき問いが立っていない"}
    kc[2]["questions"] = [{"key": "前提が立っているか", "kind": "premise", "origin": "R2",
                           "status": "held", "reason": "judge が検算中"}]
    hist("domain-separation", kc)

    nq1 = r1_at(1, [{"key": BK, "label": "block"}])
    nq2 = r1_at(2, [{"key": BK, "label": "block"}])
    nq2["questions"] = [FQ]
    nq2["reviews"]["R1"] = {"status": "carried_over", "from_round": 1, "reason": "機構の追加なし"}
    hist("q-new-r1-carried", [nq1, nq2])
    nq2b = clone((nq2))
    nq2b["reviews"]["R1"] = {"status": "pass", "reason": "台帳に問いが載ったので再発火。監査した"}
    hist("q-new-r1-ran", [nq1, nq2b])
    nq1c = clone((nq1)); nq1c["questions"] = [FQ]
    hist("q-carried-r1-carried", [nq1c, nq2])
    # 同じ key のまま kind / origin / options を総取り替えする（key の新規性では捕まらない形）。
    sw2 = clone((nq2))
    sw2["questions"] = [dict(FQ, kind="stuck", origin=BK)]
    sw2["questions"][0].pop("options")
    hist("q-swap-r1-carried", [nq1c, sw2])
    # ループが決めた問いが次の周に未決へ戻る（再燃。key は既出なので「新規」では捕まらない）。
    rp1 = clone((nq1))
    rp1["questions"] = [dict(FQ, status="decided", resolution="入口に寄せると決めた")]
    hist("q-reopen-r1-carried", [rp1, nq2])

    nc = work / "name-case"; nc.mkdir()
    (nc / "round-1.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
    (nc / "round-2.JSON").write_text(json.dumps(r1_at(2, []), ensure_ascii=False), encoding="utf-8")
    # 同じ欠陥の鏡像。受理側を ASCII に狭めただけだと、桁の異体字は「そもそも記録でない」として
    # 黙って捨てられる側へ移るだけで、欠陥が入口を移動して残る。
    nu = work / "name-unidigit"; nu.mkdir()
    (nu / "round-\u0661.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
    # 正規表現の軸（桁・英字の大小）では拾えない綴り。区切り・語・拡張子の軸から通る形で、
    # **最新ラウンドがこの形だと、記録が 1 つ短いまま「連続 2 ラウンド」の判定に乗る。**
    # from_round の下限。**外すと「素材を一度も見ずに連続 2 ラウンド成立」が exit 0 で通る**
    # （実測: 全素材と R1/R2 を from_round: 0 にした記録が「round 0 の判定を流用」で収束した）。
    # この道具が存在する理由そのものの穴なのに、塞いでいる 1 行に腕が無かった。
    fz = work / "from-round-zero"; fz.mkdir()
    fz1 = r1_at(1, []); fz2 = r1_at(2, [])
    fz2["materials"]["consistency"] = {"status": "carried_over", "from_round": 0, "reason": "流用"}
    (fz / "round-1.json").write_text(json.dumps(fz1, ensure_ascii=False), encoding="utf-8")
    (fz / "round-2.json").write_text(json.dumps(fz2, ensure_ascii=False), encoding="utf-8")
    # 3 周の窓の**幅**。連鎖が r2・r3 だけなので、窓が 3 周なら要求は立たない（exit 1）。
    # 窓を 2 周に狭めると要求が立って exit 2 になる＝この 1 本が幅を測る。「対照」と名乗っていた
    # stuck-two-rounds は記録が 2 件しか無く、range(2, len(rounds)) に一度も入らなかった。
    ww = [r1_at(1, []), r1_at(2, [{"key": BK, "label": "block"}]),
          r1_at(3, [{"key": BK, "label": "block"}])]
    hist("stuck-window-width", ww)
    # 窓は滑る。同じ連鎖を 1 周のばすと、4 周目の組で初めて要求が立つ。
    hist("stuck-window-slide", ww + [r1_at(4, [{"key": BK, "label": "block"}])])
    # UTF-8 として読めない記録（「開けない」「JSON でない」と別の診断になることを縛る）。
    (work / "badenc").mkdir()
    (work / "badenc" / "round-1.json").write_bytes(b'{"base": "\xff\xfe"}')
    nt = work / "name-tail"; nt.mkdir()
    (nt / "round-1.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
    (nt / "round_2.json").write_text(json.dumps(r1_at(2, []), ensure_ascii=False), encoding="utf-8")
    # 退避先のディレクトリとドットファイルは鳴らさない（下位は読まない規約・OS の成果物）。
    nok = work / "name-ok"; nok.mkdir()
    (nok / "round-1.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
    (nok / "archive-deadbeef").mkdir()
    (nok / ".DS_Store").write_text("x", encoding="utf-8")

    th2 = r1_at(2, [{"key": BK, "label": "block"}])
    th2["questions"] = [{"key": "新規が出続ける", "kind": "thrash", "status": "held", "reason": "件数が落ちない"}]
    hist("q-thrash-silent", [r1_at(1, [{"key": BK, "label": "block"}]), th2])

    sd = [r1_at(n, TWO) for n in (1, 2, 3)]
    sd[2]["questions"] = [dict(FQ, origin=BK2, depends=[BK])]
    hist("q-stuck-via-depends", sd)

    hist("stuck-two-rounds", [r1_at(1, [{"key": BK, "label": "block"}]),
                              r1_at(2, [{"key": BK, "label": "block"}])])

    # 縛るのは「まだ聞く気がある問い」だけで、resolved には何も要求しない（緩める向きの 2 本）。
    rog = r1_at(1, [{"key": BK, "label": "block"}])
    rog["questions"] = [dict(FQ, origin="src/gone.py — 直って消えたキー", status="resolved",
                             resolution="修正で形が変わり岐路が消えた")]
    hist("q-resolved-origin-gone", [rog])
    rso = r1_at(1, [{"key": BK, "label": "block"}])
    rso["questions"] = [{"key": "別 PR に積むか", "kind": "split", "origin": BK, "status": "decided",
                         "reason": "目的の外に見えた", "resolution": "目的の内側と分かったので本 PR で直す"}]
    hist("q-resolved-split-open", [rso])

    mid = [r1_at(n, TWO) for n in (1, 2, 3)]
    mid[1]["questions"] = [dict(FQ, origin="src/none.py — 無い")]
    mid[2]["questions"] = [dict(FQ, origin="src/none.py — 無い")]
    hist("q-origin-missing-mid", mid)

    hist("round-zero", [r1_at(1, [])])
    hist("round-dup", [r1_at(1, []), r1_at(2, [])])
    (work / "round-dup" / "round-01.json").write_text(
        json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
    (work / "round-zero" / "round-0.json").write_text(
        json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")

    cz = clone((templates["round-1"]))
    cz["materials"]["local_review"] = {"status": "found", "count": 0, "detail": "0 件だった"}
    write("count-zero", cz, num=1)
    ce = clone((templates["round-1"]))
    ce["materials"]["consistency"] = {"status": "clean", "checked": ""}
    write("checked-empty", ce, num=1)
    cf = clone((templates["round-1"]))
    # **整数は別**——`count: 0` は「見たが 0 件」で正当（その腕は count-zero）。
    cf["materials"]["consistency"] = {"status": "clean", "checked": False}
    cn = clone((templates["round-1"]))
    cn["materials"]["consistency"] = {"status": "clean", "checked": 0}
    write("checked-number", cn, num=1)
    write("checked-false", cf, num=1)

    # defer が 1 ラウンド記録から消えてから [block] で戻る。台帳が隣の 1 ラウンドしか見ないと
    # 新証拠なしで素通りし、しかも「（新規）」と事実に反する注記が付いていた。
    hist("ledger-gap", [
        r1_at(1, [{"key": LK, "label": "suggest", "disposition": "defer",
                   "reason": "共有面を触るので別の変更で扱う"}]),
        r1_at(2, []),
        r1_at(3, [{"key": LK, "label": "block"}]),
    ])

    # JSON として読めない記録と、深いネスト（json モジュールが JSONDecodeError 以外を投げる例）。
    for nm, body in (("truncated", '{ "base": '), ("deep", "[" * 100000 + "]" * 100000)):
        (work / nm).mkdir(exist_ok=True)
        (work / nm / "round-1.json").write_text(body, encoding="utf-8")
    # 研究記録・診断記録はファイル渡しなので、同じ深いネストを**単体のファイルとしても**置く。
    # `$WORK/deep.json` はどこでも作られておらず、それを渡す 2 本の腕は「開けない」で exit 2 に
    # なって緑だった——名乗った性質（深いネストでも 1 と区別して落ちる）を一度も測っていない。
    (work / "deep.json").write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
    # 「開けない」の腕。round-1.json がディレクトリだと open が OSError を投げる。
    (work / "unreadable" / "round-1.json").mkdir(parents=True)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    if len(sys.argv) != 3:
        sys.exit("使い方: broken_records.py <リポジトリの根> <書き出す置き場>")
    write_all(sys.argv[1], sys.argv[2])
