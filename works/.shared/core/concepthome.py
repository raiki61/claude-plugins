"""判断の 1 軸と考えの住処の観点の文、と考えの地図・柵の表の探し方（計画 docs/plans/2026-10-09-clean-whole.md の 3.2 節・Task 2.1）。

役の指示書の頭に貼る文はここだけが持つ。どの文も頭に 1 軸の文 AXIS を置く（目的を満たし守る仕組みが働いたまま、全体が
より簡潔になるか。簡潔さは考えを知る場所の数で量る）。地図と表は対象のリポジトリの追跡されたファイルから、決まった名
（MAP_NAME・TABLE_NAME。根か、どのフォルダの下でも）で探す（.editorconfig と同じ「決まった名のファイルが在れば読む」形。
対象を名指さない。無ければ役は対象自身の構造から住処を探す）。地図や表を作らない。

- 定数: MAP_NAME・TABLE_NAME・PREFIX（考えの住処の指摘の頭の語）・MAX_MAPS・AXIS・PLAN_RULE・REVIEW_ASK・R1_HEAD・R3_HEAD
  （R1_HEAD・R3_HEAD は {section} を 1 つ持つ。独立の目の支度が直しの後の実測の数の 1 文を入れる）・EYE_ASK（構造の目の問い）
- pick_maps(names) -> (先頭 MAX_MAPS 件, 全件の数): 名の並びから地図を浅い順・名の順に選ぶ
- pick_tables(names) -> list: 名の並びから柵の表を浅い順・名の順に選ぶ（件数で切らない）
- base_of(name) -> str: 地図か表のパスの持ち主のフォルダ（docs/ の親。根なら ""）。表の中のパスはここからの相対
- tracked_names(repo) -> (名の並び, 落ちた訳): `git ls-files` の行（投げない。落ちたら ([], 訳)）
- section(repo) -> str: 役の指示書に貼る地図の節（見つかった・見つからない・木を読めなかったの 3 つの形）

標準ライブラリだけ。works の物を何も import しない。
"""
from __future__ import annotations

import pathlib
import subprocess
import promptsection

MAP_NAME = "docs/concepts.md"
TABLE_NAME = "docs/concepts.json"
PREFIX = "考えの住処: "
MAX_MAPS = 5

AXIS = ("判断の 1 軸: 目的を満たし、守る仕組みが働いたまま、全体がより簡潔になるか。"
        "簡潔さは行数でなく、設計の考えを知る場所の数で量る")

PLAN_RULE = (
    f"{AXIS}。\n\n"
    "考えの住処を使え: 案が触る考え（設計の決まりごと。例: 結末の語・止めの理由・無人の時の方針）ごとに、それを 1 か所で持つ所"
    "（住処）が対象のリポジトリに在るかを先に探せ（『考えの住処の地図』の節——包みが system prompt に足す——に地図が在ればその行、無ければ README・モジュールの"
    "境・同じ語を定数で持つ所を Grep で）。住処が在れば案はそこを変え、ほかの所に同じ語・欄の名・値・判定の式を写さない。それでも"
    f" adds の行が考えを新しい所に知らせるなら、その行の canonical に「{PREFIX}<考え> の住処は <パス>」と、住処を使わない理由を"
    "書け。住処の無い考えに足す時は、既にその考えを知っている所に寄せ、知る所を増やさない形を先に選べ。")

REVIEW_ASK = (
    f"{AXIS}。\n\n"
    "考えの住処を見よ: 案の adds と approach が触る考えごとに、対象のリポジトリにその考えの住処（1 か所で持つ所）が在るかを確かめよ"
    "（『考えの住処の地図』の節——包みが system prompt に足す——に地図が在ればその行、無ければ自分で Grep）。案が住処を使わずに、別の所にその考えを知らせる"
    f"（語・欄の名・値・判定の式を写す）なら kind copy の穴に挙げ、why を「{PREFIX}」で始めて、考えの名・住処のパスと行・新しく"
    "知る所を書け。住処が在るのに使わない案は severity block、住処の無い考えの知る所を増やす案は suggest。住処のパスと行を書けない"
    "物は挙げない。構造の目の行がその単位で「責務を 2 か所に割る」を既に挙げ、案がその避け方（chosen）に従っているなら挙げ直さない。")

R1_HEAD = promptsection.Section(
    "## 最小の意味（works が足した読み替え。下の指示書の「累積差分が最小か」と観点の正本の「処方の最小性」の大きさは、この意味で読め）\n\n"
    f"{AXIS}。\n\n"
    "最小は行数でなく、考え（設計の決まりごと）を知る所の数で量る。累積差分の後、どの考えも、それを知る所（語・欄の名・値・判定の式を"
    "書く所）が差分の前より増えていなければ最小である。考えを住処（1 か所で持つ所）へ移すために行が増えた差分は最小に数え、数行で"
    "済ませたが同じ考えを別の所にもう 1 つ知らせた差分は最小でない。零処方から並べる順は保ち、処方の大きさをこの数で量れ。住処の"
    "パスと行を名指せる考えの知る所が増えていれば status を redesign-needed にし、reason を"
    f"「{PREFIX}」で始めて考えの名と増えた所を書き、増えた所を deletions に 1 行ずつ（where は増えた所、why は住処のパスと行）置け。"
    f"住処の無い考えの知る所が増えただけなら status は変えず、increments に「{PREFIX}」で始まる 1 行を置け。"
    "知る所の数は、下の機械の実測と『考えの住処の地図』の節（包みが system prompt に足す）を手がかりに量れ。\n\n"
    "{section}", source="fn:structmark.after_counts")

R3_HEAD = promptsection.Section(
    "## 考えの住処（works が足した観点）\n\n"
    f"{AXIS}。\n\n"
    "差分が触る考えごとに、対象のリポジトリの中での住処（1 か所で持つ所）を確かめよ。『考えの住処の地図』の節（包みが system prompt に足す）に地図が在ればその行を正とし、"
    "無ければリポジトリ自身の構造（README・モジュールの境・同じ語を定数で持つ所）から住処を見つけよ。差分が考えを住処の外に書き"
    "足している、または住処と違う形で同じ考えを持ち直していて、住処のパスと行を名指せるなら、status を redesign-needed にし、"
    f"reason を「{PREFIX}」で始めて考えの名・住処・外の所を書け。名指せない物は pass のまま reason に書け。読んだ地図（地図が"
    "無ければ構造から見つけた住処）を seen に、住処を見つけられなかった考えを unseen に含めよ。下の機械の実測の増えた所も確かめよ。\n\n"
    "{section}", source="fn:structmark.after_counts")

EYE_ASK = (
    f"{AXIS}。\n\n"
    "単位ごとに 1 つの問いで判じよ: この単位を直した後、設計の考え（語・欄の名・値・判定の式）を知る場所が、直す前より増えるか。"
    "下に『考えの地図の行』と『知る場所の数』が在れば、それを正とする（住処の在る考えを住処の外に書き足す直しは汚れる。住処の"
    "無い考えは、既にそれを知る所に寄せる形を chosen に書く）。在らなければ実測（写しの塊・入口の数・名の現れる場所）から判じよ。"
    "知る場所が増えないなら汚れない。形の番号は、増え方がどの形に当たるかを名指すために使え（形 2 は、同じ考えを 2 か所目に"
    "書く時だけ）。")


def pick_maps(names: list[str]) -> tuple[list[str], int]:
    """名が MAP_NAME か "/" + MAP_NAME で終わる物を、/ の数の少ない順・同じなら名の順に並べ、(先頭 MAX_MAPS 件, 全件の数)"""
    got = sorted(_named(names, MAP_NAME), key=lambda n: (n.count("/"), n))
    return got[:MAX_MAPS], len(got)


def pick_tables(names: list[str]) -> list[str]:
    """名が TABLE_NAME か "/" + TABLE_NAME で終わる物を、/ の数の少ない順・同じなら名の順に（件数で切らない）"""
    return sorted(_named(names, TABLE_NAME), key=lambda n: (n.count("/"), n))


def _named(names, tail: str) -> list[str]:
    return [n for n in names if isinstance(n, str) and (n == tail or n.endswith("/" + tail))]


def base_of(name: str) -> str:
    """地図か表のパス（…/docs/concepts.*）の持ち主のフォルダ（docs/ の親。根の docs なら ""）"""
    head = name.rsplit("/", 2)
    return head[0] if len(head) == 3 else ""


def tracked_names(repo) -> tuple[list[str], str]:
    """(追跡されたファイルの名の並び, 落ちた訳)。git が落ちても投げず ([], 訳)"""
    try:
        p = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, text=True, encoding="utf-8",
                           stdin=subprocess.DEVNULL)
    except (OSError, ValueError) as e:
        return [], f"git を起こせない: {e}"
    if p.returncode != 0:
        return [], (p.stderr.strip() or f"git ls-files が終了コード {p.returncode}")[-300:]
    return [n for n in p.stdout.split("\0") if n], ""


MAP_NONE_HEAD = promptsection.Section(f"## 考えの住処の地図\n\n無い（探した形: 追跡されたファイルの {MAP_NAME}。根とどのフォルダの下でも）{{tail}}。"
                                      "住処はリポジトリ自身の構造から探せ", source="fn:concepthome.section")
MAP_FOUND_HEAD = promptsection.Section("## 考えの住処の地図（機械が追跡されたファイルから探した。先に Read で読め）\n\n", source="fn:concepthome.section")


def section(repo) -> str:
    """役の指示書に貼る地図の節。見つかれば見出しとパスを 1 行ずつ（最大 MAX_MAPS、超えた分は「ほか N 件」）。見つからない・
    木を読めない時は、無い旨と探した形（読めなければその訳も）。役を止めない"""
    names, why = tracked_names(pathlib.Path(repo))
    maps, total = pick_maps(names)
    if not maps:
        tail = f"（木を読めなかった: {why}）" if why else ""
        return MAP_NONE_HEAD.format(tail=tail)
    lines = [f"- {m}" for m in maps]
    if total > len(maps):
        lines.append(f"- ほか {total - len(maps)} 件")
    return (MAP_FOUND_HEAD + "\n".join(lines)
            + "\n\n審査するファイルを含むフォルダの地図を正とする")
