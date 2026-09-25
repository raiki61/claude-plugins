"""対象リポジトリが宣言した走らせる語（ルートの .review-checks.json）。

**人の承認は要らない。** engine は宣言の語を、走らせる直前に作業ツリーのルートの宣言を読み直して一致を確かめてから、shell を
通さずに走らせる（engine/commands.py の engine_run_refusal）。以前は direnv の `direnv allow` の形で、人が宣言の中身の sha256 を
`loop.py allow-checks` で承認するまで走らせなかった。人が寝ている間の run がそこで人を待って止まり、人はその手間を不要と
決めた（2026-09-25）ので外した。git の共通ディレクトリに残った graphloops/allowed-checks.json はもう読まない（消してよい）。

**外したことで守られなくなった物**: 初見のリポジトリ・レビューしている差分・修正役が書き換えた宣言の語を、人が見る前に
engine が Claude Code の許可の仕組み（permission mode・分類器）の外で走らせる。回す側が打つ `loop.py launch` は分類器から見て
1 語で、engine が起こす宣言の語は分類器を通らない。**他人のリポジトリ・他人の PR を回すときは、宣言とそれが呼ぶスクリプトを
先に読め。**
**残る物**: shell を通さない argv と宣言の書式の検査（parse）／同梱の語の免除は argv の頭で決める（ENGINE_HELPERS）／盤面
（loop.py patch）で instance の語を書き換えても、ルートの宣言に無い語は走らない（宣言を読む場所は盤面の欄でなく、run の
inputs.cwd から引いたリポジトリのルート——inputs.cwd を patch で差し替えるのは run 全体の対象を差し替える操作で、この柵の外）
／宣言の無いリポジトリは任せ先の節（Claude Code の許可の仕組みを通る）。
**もともと守っていなかった物**: 語が呼ぶスクリプトの本文（例えば tests/run.sh）。承認が在った頃も及ぶのは宣言の中身だけで、
差分がスクリプトの本文を書き換えれば承認済みの宣言のままで走った。前の経路（任せ先の Bash を分類器が見る）も語しか見ていない。
**OS の境界（sandbox）を足さない理由**: 役の sandbox では `uv run --with` が ~/.cache/uv に書けず止まる（engine/role_run.py の
tooled_permission の注記の実測）。このリポジトリの宣言の pytest の段がその形で、包むと今の能力が減る。
"""
import hashlib
import json
import pathlib


DECL_NAME = ".review-checks.json"
DECL_KEYS = ("suite",)   # 宣言の最上位の鍵。知らない鍵は拒む（効かない鍵を書いても黙って無視しない）
STEP_KEYS = ("name", "argv")


def canonical(steps):
    """sha に結ぶ正規形（鍵の順・空白に依らない）。宣言の書き方の揺れで突き合わせが外れない"""
    return json.dumps(steps, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def steps_sha(steps):
    return hashlib.sha256(canonical(steps)).hexdigest()


def parse(text):
    """宣言の本文を読む ——（steps, 誤り）。steps は [{name, argv}]。誤りがあれば steps は None"""
    try:
        d = json.loads(text)
    except ValueError as e:
        return None, f"JSON として読めない（{e}）"
    if not isinstance(d, dict) or set(d) != set(DECL_KEYS):
        return None, f"最上位は {{{', '.join(DECL_KEYS)}}} だけ（在る鍵: {sorted(d) if isinstance(d, dict) else type(d).__name__}）"
    suite = d["suite"]
    if not isinstance(suite, list) or not suite:
        return None, "suite は 1 段以上の配列"
    seen = set()
    for i, s in enumerate(suite):
        if not isinstance(s, dict) or set(s) != set(STEP_KEYS):
            return None, f"suite[{i}] は {{{', '.join(STEP_KEYS)}}} だけ"
        if not isinstance(s["name"], str) or not s["name"].strip() or s["name"] in seen:
            return None, f"suite[{i}].name は空でない・重ならない文字列"
        seen.add(s["name"])
        if (not isinstance(s["argv"], list) or not s["argv"]
                or not all(isinstance(a, str) for a in s["argv"]) or not s["argv"][0]):
            return None, f"suite[{i}].argv は 1 語以上の文字列の配列（shell を通さずにそのまま起こす）"
    return [{"name": s["name"], "argv": list(s["argv"])} for s in suite], None


def read(root):
    """ルートの宣言を読む。無ければ None、在れば {steps, sha} か {error}"""
    p = pathlib.Path(root) / DECL_NAME
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {"error": f"{DECL_NAME} が読めない（{e}）"}
    steps, err = parse(text)
    if err:
        return {"error": f"{DECL_NAME}: {err}"}
    return {"steps": steps, "sha": steps_sha(steps)}
