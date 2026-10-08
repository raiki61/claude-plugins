"""下請けの会話（skill の fork・Agent の子）が、親の節の返答の道具 StructuredOutput に書いた返答を拾う口。

**なぜ要るか（実測 2026-10-08、利用者の run f57a5374 ほか 6 つの works の家の会話の記録）。** 組み込みの skill code-review は
fork（下請けの会話）で走り、節の `--json-schema` が足す道具 StructuredOutput を継ぐ。fork は所見をそこへ書いて終わり
（19 本の全部。schema の検査も親の節と同じで、型に合わなければ fork の中で拒まれて書き直す）、親の Skill の結果は
『Skill execution completed』だけになる。局所レビューの役は /code-review の行を items 空・failed に『本文なし』で返し、
写しの規則（local_review_covers_lenses）は行が在れば通すので、消えた所見は「見たが所見なし」と同じ形で記録に入った
（f57a5374 では 10 件。うち 1 件は 2 run 後に阻害になった）。args に『本文で返せ』と書いた 6 本も同じだった。

**どう拾うか。** 包み（claude-adapter）が足す PostToolUse:StructuredOutput のフック（record-output.py）が、下請けの中の
呼び出し（入力に agent_id が在る。record-read.py の 2026-09-22 の実測と同じ欄）を入力のまま
`<包みの家>/reads/<cwd の hash>/outputs.jsonl` に 1 行残す。PostToolUse は道具が成った時だけ起きるので、残る入力は
節の schema の検査を通った物。局所レビューの受け付け（blk-material の take）が、この周に起こした印より後に包みがこの役を
起こした会話（起動の記録。拒まれて起こし直すと id が替わる）の行を読み（sessions_since・read_outputs）、宣言した skill のレンズのうち fork で走る物（FORK_LENSES）の行が items 空なら fork の所見を戻す（recover）。
戻せない /code-review の空の行は「所見なし」でなく「見ていない」と書く（FORK_LENSES。起こし直しても同じ形で落ちるので
拒まない）。戻した・見ていない、は周の作業ファイル LENS_FILE に残し、機械の報告が「未確認のレンズ」の節に出す（report_lines）。

- log_path(repo, home_dir=None):        記録の置き場（adapter.reads_dir の隣の OUTPUTS_LOG）
- sessions_since(repo, node, since):    その役を since（起こした印）より後に起こした会話の id の全部（起こし直しで id が替わる）
- read_outputs(repo, sessions, since):  その会話の、since より後の下請けの返答の入力の一覧
- recover(reply, skills, payloads):     (戻した返答の写し, 控え {recovered, empty, unseen, unmatched})。受けた返答は書き換えない
- report_lines(board_dir):              報告の行（周ごとの LENS_FILE から）
"""
import copy
import datetime
import json
import pathlib

import adapter
import scopes

OUTPUTS_LOG = "outputs.jsonl"
LENS_FILE = "local-review-lenses.json"     # 周の作業ファイル（board/r<N>/）。受け付けが毎回書き直す
# fork で走り、返答が親に届かないと実測したレンズ。空の行は記録で 0 件を確かめた時だけ「所見なし」に数える
# （/simplify・/security-review は親の会話の中で走る。実測の Skill の所要 14 ミリ秒・256 ミリ秒）
FORK_LENSES = ("/code-review",)
ITEM_KEYS = ("where", "text", "mechanism", "measured", "false_positive_if")   # 写しの schema の findings[].items の鍵
UNSEEN_TAG = "【works: 所見を受け取れていない——このレンズは見ていないのと同じに扱え】"


def log_path(repo, home_dir=None) -> pathlib.Path:
    return adapter.reads_dir(repo, home_dir) / OUTPUTS_LOG


def _when(text):
    try:
        t = datetime.datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return t if t.tzinfo else None


def sessions_since(repo, node: str, since, home_dir=None) -> set:
    """包みが cwd repo で節 node（包みの印の名）を since（ISO の時刻。起こした印）より後に起こした会話の id の全部と、今の会話の
    id の記録（session_path）。受け付けに拒まれて起こし直された回は、Archon の輪が --resume --fork-session で起こし、包みが
    新しい id を割り当てて記録を上書きするので、前の回の会話の id は起動の記録（launches）からしか引けない。since が読めなければ
    起動の記録の全部の回を数える"""
    start = _when(since) if since else None
    out = set()
    for row in adapter.read_launches(repo, home_dir):
        sess = row.get("session") if isinstance(row.get("session"), dict) else {}
        at = _when(row.get("at"))
        if row.get("node") == node and sess.get("id") and (start is None or (at is not None and at >= start)):
            out.add(sess["id"])
    now = adapter.read_session_id(adapter.session_path(repo, node, home_dir))
    if now:
        out.add(now)
    return out


def read_outputs(repo, sessions, since, home_dir=None) -> list:
    """会話 sessions（id の集まり）の下請けが StructuredOutput に書いた入力（dict）を記録の順に。since（ISO の時刻。起こした印）が
    読めればそれより前の行を除く（同じ会話を継いだ前の周の行）。会話の id が無い・記録が無い・読めない行は拾わない"""
    sessions = {sessions} if isinstance(sessions, str) else set(sessions or ())
    if not sessions:
        return []
    try:
        text = log_path(repo, home_dir).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    start = _when(since) if since else None
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not (isinstance(row, dict) and row.get("session_id") in sessions and row.get("agent_id")
                and isinstance(row.get("input"), dict)):
            continue
        at = _when(row.get("ts"))
        if start is not None and (at is None or at < start):
            continue
        out.append(row["input"])
    return out


def _items(raw) -> list:
    """型に合う項目だけ（where と text が文字列）。鍵は ITEM_KEYS の文字列だけを残す"""
    return [{k: i[k] for k in ITEM_KEYS if isinstance(i.get(k), str)} for i in raw or []
            if isinstance(i, dict) and isinstance(i.get("where"), str) and isinstance(i.get("text"), str)]


def recover(reply: dict, skills: list, payloads: list) -> tuple:
    """返答の写しに、下請けの返答（payloads）の所見を戻す。宣言の skill のレンズ（/ で始まる名）ごとに、fork が書いた行の
    skill の名（/ の有無は問わない）で当てる。返答の行が items 空の FORK_LENSES のレンズだけを埋め（役が受け取った本文は差し替え
    ない。親の会話で走ったレンズの行は fork が書いても触らない）、
    material を数え直す。戻せない FORK_LENSES の空の行は failed の頭に UNSEEN_TAG を置く"""
    out = copy.deepcopy(reply)
    notes = {"recovered": [], "empty": [], "unseen": [], "unmatched": []}
    lenses = {e["skill"][1:]: e["skill"] for e in skills if isinstance(e.get("skill"), str) and e["skill"].startswith("/")}
    got = {}
    for p in payloads:
        for row in p.get("findings") or []:
            if not isinstance(row, dict):
                continue
            label = str(row.get("skill") or "")
            lens = lenses.get(label.strip().lstrip("/"))
            if lens is None:
                notes["unmatched"].append(label)
                continue
            have = got.setdefault(lens, [])
            have += [i for i in _items(row.get("items")) if i not in have]
    mat = out.get("material") if isinstance(out.get("material"), dict) else None
    for row in out.get("findings") or []:
        lens = row.get("skill") if isinstance(row, dict) else None
        if lens not in lenses.values() or lens not in FORK_LENSES or row.get("items"):   # 親の会話で走ったレンズは役の申告のまま
            continue
        said = str(row.get("failed") or "")
        if got.get(lens):
            n = len(got[lens])
            row.update(items=got[lens], invoked=True,
                       failed=f"（works の受け付け: fork が親の返答の道具に書いた所見 {n} 件を包みの記録から戻した。役の文: {said}）")
            notes["recovered"].append({"lens": lens, "count": n})
            if mat is not None:
                _count(mat, lens, n)
        elif lens in got:
            row["failed"] = f"{said}（works の受け付け: fork の記録で所見 0 件を確かめた）"
            notes["empty"].append(lens)
        elif row.get("invoked") is True:
            row["failed"] = f"{UNSEEN_TAG} {said}"
            notes["unseen"].append(lens)
            if mat is not None:
                for k in ("checked", "detail", "reason"):
                    if isinstance(mat.get(k), str):
                        mat[k] = f"{mat[k]}（{lens}: {UNSEEN_TAG}）"
    return out, notes


def _count(mat: dict, lens: str, n: int):
    """戻した n 件を素材に数える: clean は found に（今の周に見つけた物が在る）、found は count に足す。ほかの状態は替えない"""
    note = f"{lens} の所見 {n} 件は、fork が親の返答の道具に書いた物を works の受け付けが戻した"
    if mat.get("status") == "clean":
        checked = mat.get("checked") or ""
        mat.clear()
        mat.update(status="found", count=n, detail=f"{note}（役の判定は clean: {checked}）")
    elif mat.get("status") == "found":
        mat["count"] = (mat["count"] if isinstance(mat.get("count"), int) else 0) + n
        mat["detail"] = f"{mat.get('detail') or ''}（{note}）"


def report_lines(board_dir) -> list:
    """機械の報告の「未確認のレンズ」の節に足す行（周の順）。控えが無い・読めない周は飛ばす"""
    out = []
    for p in scopes.all_rounds(pathlib.Path(board_dir), LENS_FILE):
        try:
            doc = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        head = f"局所レビュー（周 {doc.get('round', '?')}）の"
        out += [f"{head} {r['lens']}: fork が親の返答の道具（StructuredOutput）に書いた所見 {r['count']} 件を、包みの記録から戻した"
                for r in doc.get("recovered") or [] if isinstance(r, dict)]
        out += [f"{head} {lens}: 所見を受け取れていない（fork の返答が届かず、包みの記録からも戻せなかった）——見ていないのと同じ"
                for lens in doc.get("unseen") or []]
        if doc.get("unmatched"):
            out.append(f"{head} fork の返答の行のうち宣言のレンズに当たらない名 {sorted(set(doc['unmatched']))} は戻していない")
    return out
