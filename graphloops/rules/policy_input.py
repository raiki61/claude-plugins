"""人の方針の文書（run をまたいで効く、人が決めた決まり）の置き場を決め、比べる元の写しを取る——review-loop と research-loop の rules が共有する 1 本。

置き場は対象リポジトリの git の共有の置き場（`git rev-parse --git-common-dir`）の下。作業ツリーの外なので、方針の文書は
採点する版にも差分にも作業ツリーの突合にも入らず、同じリポジトリの worktree の全部の run が同じ文書を読む。init の
`--input policy_md=<パス>` を渡せばそれを使う（名指しした文書が無ければ init で止める）。役の節には節を出す時点の本文が
貼られ（prompts/policy-paste.md）、回す側の節には置き場が渡る（prompts/policy-path.md）。

engine も graph も方針の中身を持たない。比べる元（init と、関所で人が通した時点で固定した版）の写しは盤面の policy/ に
sha256 の名前で置く——文書は版管理の外に在るので、写しが無いと、関所で何が変わったかを人に見せられず、run が
どの版に固定していたかも後から引けない。関所や仕上げで変化を見つけたら、前後の写しと差分のファイルを同じ置き場に
置き、記録と関所の行には置き場だけを載せる（本文を載せると、人の答えの台帳を通って回す側の節に貼られる）。

rules は engine を import しない約束なので、engine が rules に差し込む道具（git・Reject）は呼び元から引数で受ける。
"""
import difflib
import hashlib
import pathlib

DEFAULT = ("graphloops", "policy.md")


def default_path(git, cwd):
    """既定の置き場（在るかは問わない）。git の置き場が引けなければ None"""
    common = git("rev-parse", "--git-common-dir")
    if not common or not common.strip():
        return None
    root = pathlib.Path(common.strip())
    if not root.is_absolute():
        root = pathlib.Path(cwd) / root
    return root.resolve().joinpath(*DEFAULT)


def file_sha(path):
    p = pathlib.Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest() if p and p.is_file() else None


def snapshot(b, path):
    """文書を 1 回だけ読み、(sha256, 写しの置き場) を返す——sha と写しが別の版を指さないように、読みは 1 回。無ければ (None, None)"""
    p = pathlib.Path(path) if path else None
    if not (p and p.is_file()):
        return None, None
    data = p.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    copy = pathlib.Path(b.dir) / "policy" / f"{sha}.md"
    if not copy.is_file():
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(data)
    return sha, str(copy)


def locate(b, git):
    """いま読むべき方針の文書のパス（無ければ None）: init で名指しした物、無ければ既定の置き場に在る物"""
    named = b.state["inputs"].get("policy_md")
    if named:
        return named
    p = default_path(git, b.state["inputs"]["cwd"])
    return str(p) if p and p.is_file() else None


def resolve(b, git, Reject):
    """on_init から呼ぶ: inputs.policy_md を決めて {path, sha256, copy} を返す。名指しした文書が無ければ Reject"""
    named = b.state["inputs"].get("policy_md")
    if named:
        p = pathlib.Path(named)
        if not p.is_absolute():
            p = pathlib.Path(b.state["inputs"]["cwd"]) / p
        if not p.is_file():
            raise Reject(f"--input policy_md={named} の文書が無い（人の方針の文書を名指ししたなら、先に置け）")
        b.state["inputs"]["policy_md"] = str(p.resolve())
    else:
        b.state["inputs"]["policy_md"] = locate(b, git)
    path = b.state["inputs"]["policy_md"]
    sha, copy = snapshot(b, path)
    return {"path": path, "sha256": sha, "copy": copy}


def _lines(copy):
    return pathlib.Path(copy).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if copy else []


def change(b, git, pol):
    """固定した版（pol の path・sha256・copy）から今の文書が変わったか。変わっていなければ None。
    変わっていれば {path, from, to, from_copy, to_copy, diff_file}（今の版の写しと差分のファイルを盤面に置く）。
    固定した版の写しが引けない（init の時点で文書が無かった、でなく写しが消えた・写しを取らない版で init した盤面）なら、
    空から比べた差分で中身を偽らず、diff_file を None にして diff_missing に理由を書く"""
    path = locate(b, git)
    to, to_copy = snapshot(b, path)
    frm = pol.get("sha256")
    if to == frm:
        return None
    ch = {"path": path, "from": frm, "to": to, "from_copy": pol.get("copy"), "to_copy": to_copy, "diff_file": None}
    if frm and not (ch["from_copy"] and pathlib.Path(ch["from_copy"]).is_file()):
        ch["diff_missing"] = "固定した版の写しが盤面に無い（消えたか、写しを取らない版で init した盤面）——差分を作れない"
        return ch
    diff = pathlib.Path(b.dir) / "policy" / f"{(frm or 'none')[:12]}-{(to or 'none')[:12]}.diff"
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_text("".join(difflib.unified_diff(_lines(ch["from_copy"]), _lines(to_copy),
                                                 ch["from_copy"] or "（固定した時点で文書が無い）", to_copy or "（今は文書が無い）")),
                    encoding="utf-8")
    ch["diff_file"] = str(diff)
    return ch


def change_row(ch):
    """関所の行と報告に載せる 1 行——置き場だけで、本文を載せない"""
    where = (f"差分 {ch['diff_file']}" if ch.get("diff_file") else ch.get("diff_missing", "")) + \
            f"・前の版の写し {ch.get('from_copy') or '（無い）'}・今の版の写し {ch.get('to_copy') or '（無い）'}"
    return (f"人の方針の文書 {ch['path'] or '（無い）'} が固定した版から変わった: sha256 "
            f"{str(ch['from'])[:12]} → {str(ch['to'])[:12] if ch['to'] else '消えた'}（{where}）")
