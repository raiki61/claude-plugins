"""対象リポジトリが宣言した走らせる語（ルートの .review-checks.json）と、人の承認（loop.py allow-checks）。

**なぜ承認が要るか。** 役（任せ先）がコマンドを走らせていた頃は、Claude Code の許可の仕組み（permission mode・分類器）が
1 本ずつ見ていた。engine が宣言の語を直接走らせると、その関門を通らない。そこで direnv の `direnv allow` と同じ形にする
——人が宣言の中身を見て承認し、承認は中身の sha256 に結ぶ。中身が 1 字でも変われば承認は外れ、engine は走らせない。

**承認が及ぶのは宣言の中身（走らせる語の列）だけ**で、語が呼ぶスクリプトの中身（例えば tests/run.sh の本文）は含まない
——direnv が .envrc だけを承認するのと同じ線。前の経路（任せ先の Bash を分類器が見る）も `bash tests/run.sh` という語だけを
見ていて、スクリプトの中身は見ていなかった。

承認の置き場は git の共通ディレクトリ（`git rev-parse --git-common-dir`）の graphloops/allowed-checks.json ——作業ツリーの外
（レビュー対象の差分に載らない）で、同じリポジトリの worktree の間で共有する。承認は人が打つ。回す側（LLM）が打たないことは
手順書が縛る（answer と同じ信頼の線）——機械では縛れない。
"""
import hashlib
import json
import pathlib

from .util import git, now, write_json

DECL_NAME = ".review-checks.json"
DECL_KEYS = ("suite",)   # 宣言の最上位の鍵。知らない鍵は拒む（効かない鍵を書いても黙って無視しない）
STEP_KEYS = ("name", "argv")


def canonical(steps):
    """承認に結ぶ正規形（鍵の順・空白に依らない）。宣言の書き方の揺れで承認が外れない"""
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


def allow_file(root):
    """承認の置き場（引けなければ None）"""
    common = git("-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common is None or not common.strip():
        return None
    return pathlib.Path(common.strip()) / "graphloops" / "allowed-checks.json"


def _load(path):
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, UnicodeDecodeError):
        return None   # 読めない承認の一覧は『承認なし』と同じに扱う（読めない物を承認と数えない）
    return got if isinstance(got, dict) else None


def allowed(root, sha):
    """この sha の宣言を人が承認しているか"""
    path = allow_file(root)
    got = _load(path) if path else None
    return bool(got) and sha in got


def allow(root, note):
    """今の宣言を承認の一覧に積む ——（承認した宣言, 誤り）"""
    d = read(root)
    if d is None:
        return None, f"{pathlib.Path(root) / DECL_NAME} が無い"
    if "error" in d:
        return None, d["error"]
    path = allow_file(root)
    if path is None:
        return None, "git の共通ディレクトリが引けない（リポジトリの中で呼べ）"
    got = _load(path)
    if got is None:
        return None, f"{path} が読めない——直すか消してから承認し直せ"
    got[d["sha"]] = {"at": now(), "note": note, "steps": d["steps"]}
    write_json(path, got)
    return {**d, "file": str(path)}, None
