#!/usr/bin/env python3
"""batch ノード: 束（1 回のゲートでまとめてメインブランチに入れる部署のブランチの組）の、決めるだけの関数。ファイルも git も書かない。

設計は docs/specs/2026-10-26-land-batch-design.md。入口の --land（landing.py）が列の札と部署の場所を読んで事実を集め、ここで決める。
- select（4.2）: 列の先頭を取った --land（束ね役）の後ろに待つ札を前から見て、束に乗せる札と、閉じた札と訳を決める。
- adopt_step（8.2）: 束で入った部署のブランチを、その部署の場所でどう受け取るかを決める。
- adoptable（8.2）: 束の控えから、このブランチの写しがメインブランチに入った行を探す（祖先の判定だけを git に問う）。
- upcoming（10）: --land-order と --dry-run が出す「次の束」の見積もり。
"""


def select(facts, limit):
    """束に乗せる札を決める（束の設計 4.2）。facts は束ね役の後ろに待つ札の事実の並び（入れる順）で、1 件は
    {ticket, who（名乗り〔部署の名前, ブランチ〕か None）, alive（札がまだ列に居るか）, path（部署の場所か None）, landed（もう入っているか）,
    unadopted（前の束で入った写しの上に commit を足し、まだ受け取っていないか）, same（取り込みの決まりが束ね役と同じか）, clean（未コミットの変更が無いか）, suspect（疑いの印が当たるか）}。limit は上限（束ね役を 1 本に数える）。
    (乗せる札の並び, 閉じた札か None, 閉じた訳か None)。もう入っている札は乗せずに先へ見て、ほかの条件に当たった札でそこで閉じる
    （列の順を追い越さない）。"""
    riders = []
    for f in facts:
        if not f.get("who"):
            return riders, f, "名乗らない札（--queue-run など）"
        if not f.get("alive", True):
            return riders, f, "札が列を抜けた"
        if not f.get("path"):
            return riders, f, "部署の場所が見つからない"
        if f.get("landed"):
            continue
        why = ("前の束で入った中身をまだ受け取っていない" if f.get("unadopted") else "取り込みの決まりが束ね役と違う" if not f.get("same") else "未コミットの変更が有る" if not f.get("clean")
               else "疑いの印が有る（前の束が赤だった）" if f.get("suspect") else "束の上限" if 1 + len(riders) >= limit else None)
        if why:
            return riders, f, why
        riders.append(f)
    return riders, None, None


def upcoming(waiting, limit, marks):
    """次の束の見積もり（束の設計 10）。waiting は今先頭で進む札の後ろに待つ札の (札, 名乗り〔部署の名前, ブランチ〕か None) の並び（入れる順）、
    marks は疑いの印（{ブランチ: commit}。見積もりでは commit を比べず、印の有るブランチで閉じる）。次の束に入る札の並び（先頭が束ね役）。
    名乗らない札が次の先頭なら、その札だけ（1 本で走る）。部署の場所・取り込みの決まり・未コミットの変更・ぶつかりは見ないので、外れうる。"""
    if not waiting:
        return []
    lead, rest = waiting[0], waiting[1:]
    if not lead[1] or lead[1][1] in marks:
        return [lead[0]]
    facts = [{"ticket": t, "who": w, "path": "-", "same": True, "clean": True, "suspect": bool(w) and w[1] in marks} for t, w in rest]
    riders, _, _ = select(facts, limit)
    return [lead[0]] + [f["ticket"] for f in riders]


def adopt_step(clean, head, original, ahead):
    """受け取りの手（束の設計 8.2・12.3）。clean は部署の場所が汚れていないか、head は部署の場所の HEAD、original は束に重ねる前の先頭（元）、
    ahead は元が HEAD の祖先か。reset（HEAD が元のまま。写しへ替える）・onto（束の後に commit を足した。足した物を写しの上へ移す）・
    dirty（受け取るはずだが、部署の場所が汚れている）・none（元を含まない。受け取らずに今の道を通る）のどれか。"""
    if head != original and not ahead:
        return "none"
    if not clean:
        return "dirty"
    return "reset" if head == original else "onto"


def adoptable(records, branch, base, head, clean, place, g):
    """束の控えの並び（landqueue.batches）から、このブランチの写しがメインブランチ base に入っている行を探し、受け取りの手を決める。
    (手, 控え, 行) か None。手は adopt_step の値（none の行と、写しが元と同じ束ね役の行は飛ばす）。入ったかの正は、控えでなく写しがメインブランチの祖先か（8.1）。"""
    for _, record in records:
        for row in record.get("members", []):
            if not (isinstance(row, dict) and row.get("branch") == branch and row.get("stacked") and row.get("original")):
                continue
            if row["stacked"] == row["original"]:   # 束ね役の行（重ねずにそのまま入った）。受け取る物が無い
                continue
            if not g.is_ancestor(place, row["stacked"], base):
                continue
            step = adopt_step(clean, head, row["original"], g.is_ancestor(place, row["original"], head))
            if step != "none":
                return step, record, row
    return None


def finished(record, base, tip_of, g, place):
    """束の控えを消してよいか（束の設計 11）: 束の全員のブランチが写しを含む（受け取った・ブランチがもう無い）か、候補がメインブランチ base に
    入っていない（push されなかった）。写しを含まないブランチでも、先頭がメインブランチに入っていれば（部署が書き換えて今の道で入れた）
    受け取る物は無いので数えない。tip_of はブランチの名前から手元のブランチの先頭（無ければ None）を引く関数。"""
    if not record.get("candidate") or not g.is_ancestor(place, record["candidate"], base):
        return True
    for row in record.get("members", []):
        tip = tip_of(row.get("branch") or "") if isinstance(row, dict) else None
        if tip and row.get("stacked") and not g.is_ancestor(place, row["stacked"], tip) and not g.is_ancestor(place, tip, base):
            return False
    return True
