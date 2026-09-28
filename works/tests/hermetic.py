"""試験を走らせた場に左右されない子の環境と一時フォルダ（test_* でないので unittest の発見に拾われない）。

試験の子へ親の環境を丸ごと渡すと、dogfood の run の中（Archon・Claude Code・engine の子）で親が立てた名が漏れて、
その場でだけ赤くなる（実測: test_dev の版の '(unset)' に本物の claude の版・test_adapter の子の出力に WORKS_DEV_ADAPTER）。
tox の pass_env と同じ向きで、外す名はここの 1 か所に置き、試験が意図して渡す名は child_env の overrides で名指しする
（test_tiers.HermeticCase は、tests/*.py の直下で dict(os.environ・{**os.environ・os.environ.copy() の 3 つの字面だけを拒む。
os.environ.items() から組む内包・env を渡さない subprocess の継ぎ・tests の下のフォルダは見ないので、そこからは今も漏れうる）。
macOS の一時フォルダは /var→/private/var の symlink の下にあり、pathlib の relative_to は字面で比べるので、比べる試験は
tmpdir の実体のパスを使う（test_adapter の Env）。
"""
import os
import pathlib
import shutil
import tempfile

# dogfood の run が立てる名（works の開発の殻 dev/archon.sh・Archon・Claude Code・graphloops の engine の子の目印）。
# WORKS_ADAPTER_HOME は試験が mock.patch.dict で os.environ に立てて子へ継がせるので外さない
DROPPED_PREFIXES = ("WORKS_DEV_", "CLAUDE_", "ARCHON_")
DROPPED = frozenset({"CLAUDECODE", "GRAPHLOOPS_ENGINE_CHILD", "WORKS_CLAUDE_VERSION", "WORKS_ARCHON_VERSION",
                     "WORKS_REAL_CLAUDE", "WORKS_ANSWER_CMD", "WORKS_KEYCHAIN_ITEM"})


def dropped(name: str) -> bool:
    return name in DROPPED or name.startswith(DROPPED_PREFIXES)


def child_env(**overrides) -> dict:
    """os.environ から dropped の名を外し、overrides を上に置いた子の環境"""
    env = {k: v for k, v in os.environ.items() if not dropped(k)}
    env.update(overrides)
    return env


def alias(case, path) -> str:
    """/private の下の実体のパスの、/ の直下の symlink を通した別名の綴り（macOS の /var・/tmp・/etc）。別名はファイルの仕組み
    から引く（/<頂> が /private/<頂> を指す symlink か）——包みの綴りの表（adapter._ALIASES）を写さないので、表の抜けを試験が
    捕まえる。別名が無い場（一時フォルダが /private の外・macOS でない機械）では skip する。呼ぶのは case.subTest の中だけ
    （skip はその subTest に留まり、同じ試験の元の綴りの主張は検査され続ける。外で呼ぶと試験を丸ごと黙らせるので拒む）"""
    if getattr(case, "_subtest", None) is None:
        raise AssertionError("hermetic.alias は case.subTest の中で呼ぶ（別名が無い場の skip が試験の残りを黙らせないように）")
    p = str(path)
    top = "/" + p.split("/")[2] if p.startswith("/private/") else ""
    if top and os.path.islink(top) and os.path.realpath(top) == "/private" + top:
        return p[len("/private"):]
    case.skipTest(f"{p} に /private の別名の綴りが無い")


def tmpdir(case, **kw) -> pathlib.Path:
    """実体のパス（realpath）の一時フォルダ。case（unittest.TestCase）の後始末で消す"""
    d = pathlib.Path(os.path.realpath(tempfile.mkdtemp(**kw)))
    case.addCleanup(shutil.rmtree, d, ignore_errors=True)
    return d
