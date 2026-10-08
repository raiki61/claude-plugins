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
import re
import shutil
import tempfile

# dogfood の run が立てる名（works の開発の殻 dev/archon.sh・Archon・Claude Code・graphloops の engine の子の目印）。
# WORKS_ADAPTER_HOME は試験が mock.patch.dict で os.environ に立てて子へ継がせるので外さない。
# ANTHROPIC_ は起こし役（.shared/core/auth_launch.py）が受け継いだ認証として先に拾い、keychain の段の試験を素通りさせる。
# HERDR_ は herdr の枠の中で試験を回すと、殻が控えに本物の枠とサーバを残して本物の herdr へ送る（枠の試験は名指しで渡す）
DROPPED_PREFIXES = ("WORKS_DEV_", "CLAUDE_", "ARCHON_", "ANTHROPIC_", "HERDR_")
DROPPED = frozenset({"CLAUDECODE", "GRAPHLOOPS_ENGINE_CHILD", "WORKS_CLAUDE_VERSION", "WORKS_ARCHON_VERSION",
                     "WORKS_REAL_CLAUDE", "WORKS_ANSWER_CMD", "WORKS_KEYCHAIN_ITEM"})


def dropped(name: str) -> bool:
    return name in DROPPED or name.startswith(DROPPED_PREFIXES)


def child_env(**overrides) -> dict:
    """os.environ から dropped の名を外し、overrides を上に置いた子の環境"""
    env = {k: v for k, v in os.environ.items() if not dropped(k)}
    env.update(overrides)
    return env


def dev_model_default() -> str:
    """dev/guard.sh の全体の模型の既定（WORKS_DEV_MODEL_DEFAULT）。試験に値を写さない——写すと既定を替えた時に、
    既定と違うはずの探りの値が既定と重なって試験が空振りする"""
    guard = pathlib.Path(__file__).resolve().parents[1] / "dev" / "guard.sh"
    m = re.search(r"^WORKS_DEV_MODEL_DEFAULT=(\S+)$", guard.read_text(encoding="utf-8"), re.M)
    if not m:
        raise AssertionError(f"{guard} に WORKS_DEV_MODEL_DEFAULT= の行が無い")
    return m.group(1)


def other_model(*avoid) -> str:
    """探りの値: 既定とも avoid とも違う模型名（既定を替えても探りが既定と重ならない）"""
    return next(m for m in ("opus", "haiku", "sonnet") if m != dev_model_default() and m not in avoid)


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
    case.skipTest(f"SKIP private-symlink: {p} に /private の別名の綴りが無い")


def fake_herdr(tmp, fail=False):
    """偽の herdr を置く。(PATH の頭に足すフォルダ, 控えのファイル)。偽の herdr を作る所はここだけ。
    実物の CLI の形（pane の下の report-agent・release-agent）だけを受けて引数を控えに 1 行ずつ書き、ほかは実物と同じ文言で
    rc=2。形は lib.sh の呼び方でなく実物の --help と公式文書から写す（lib.sh を写すと呼び方の誤りを緑で通す）。
    fail=True なら受ける形を控えた後、サーバの居ない時の実物と同じく server_not_running を標準エラーに出して rc=1。
    受けた形ごとに、送り先のサーバ（HERDR_SOCKET_PATH。無ければ (unset)）と引数を herdr_sockets が読む別の控えにも書く"""
    bin_dir = pathlib.Path(tmp) / "herdr-bin"
    bin_dir.mkdir()
    log = pathlib.Path(tmp) / "herdr.txt"
    accepted = 'echo "error: server_not_running" >&2\n    exit 1' if fail else "exit 0"
    (bin_dir / "herdr").write_text(f'#!/bin/sh\ncase "$1 $2" in\n  "pane report-agent"|"pane release-agent")\n'
                                   f'    echo "$*" >> "{log}"\n'
                                   f'    printf \'%s\\t%s\\n\' "${{HERDR_SOCKET_PATH-(unset)}}" "$*" >> "{log}.socket"\n'
                                   f'    {accepted} ;;\nesac\n'
                                   'echo "unknown command: $1" >&2\nexit 2\n')
    (bin_dir / "herdr").chmod(0o755)
    return bin_dir, log


def herdr_sockets(log):
    """fake_herdr の控えに対応する (送り先のサーバ, 引数) の並び（呼ばれていなければ空）"""
    p = pathlib.Path(f"{log}.socket")
    return [tuple(l.split("\t", 1)) for l in p.read_text().splitlines()] if p.exists() else []


def tmpdir(case, **kw) -> pathlib.Path:
    """実体のパス（realpath）の一時フォルダ。case（unittest.TestCase）の後始末で消す"""
    d = pathlib.Path(os.path.realpath(tempfile.mkdtemp(**kw)))
    case.addCleanup(shutil.rmtree, d, ignore_errors=True)
    return d
