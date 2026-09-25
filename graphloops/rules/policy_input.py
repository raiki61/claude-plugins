"""人の方針の文書（run をまたいで効く、人が決めた決まり）の置き場を決める——review-loop と research-loop の rules が共有する 1 本。

置き場は対象リポジトリの git の共有の置き場（`git rev-parse --git-common-dir`）の下。作業ツリーの外なので、方針の文書は
採点する版にも差分にも作業ツリーの突合にも入らず、同じリポジトリの worktree の全部の run が同じ文書を読む。init の
`--input policy_md=<パス>` を渡せばそれを使う（名指しした文書が無ければ init で止める）。中身はどこにも写さない——役には
節を出す時点の本文が貼られる（graph の prompt_append が指す prompts/policy.md）。

rules は engine を import しない約束なので、engine が rules に差し込む道具（git・Reject）は呼び元から引数で受ける。
"""
import hashlib
import pathlib

DEFAULT = ("graphloops", "policy.md")   # <git の共有の置き場>/graphloops/policy.md


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


def locate(b, git):
    """いま読むべき方針の文書のパス（無ければ None）: init で名指しした物、無ければ既定の置き場に在る物"""
    named = b.state["inputs"].get("policy_md")
    if named:
        return named
    p = default_path(git, b.state["inputs"]["cwd"])
    return str(p) if p and p.is_file() else None


def resolve(b, git, Reject):
    """on_init から呼ぶ: inputs.policy_md を決めて {path, sha256} を返す。名指しした文書が無ければ Reject"""
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
    return {"path": path, "sha256": file_sha(path)}
