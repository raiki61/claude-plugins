"""役の定義の frontmatter の読み（engine/validator.py の frontmatter）・読み記録のフック（hooks/record-read.py）の相対の gitdir:・
並行 PR の数え（scripts/parallel-pr.py）の切れた変更ファイルの一覧"""
import importlib.util

import pytest

from conftest import PLUGIN, REPO
from engine.validator import frontmatter


@pytest.mark.parametrize("fm, want", [
    ("tools: Read, Grep", "Read, Grep"),       # 文字列のまま（カンマで割るのは agent_def——description もカンマを含む）
    ("tools: [Read, Grep]", ["Read", "Grep"]),
    ("tools: []", []),
    ("tools:\n  - Read\n  - \"Grep\"", ["Read", "Grep"]),
])
def test_frontmatter_reads_every_form_of_the_tools_list(fm, want):
    """YAML のブロックの形のリスト（- Read）も読む——以前は正規表現で 1 行だけ読み、空のツールの一覧になって役が黙ってツール無しで起動した"""
    got, body = frontmatter(f"---\nname: x\n# 注記\n{fm}\nmodel: opus\n---\n本文\n--- の後も本文")
    assert got["tools"] == want and got["model"] == "opus" and body == "本文\n--- の後も本文"


def test_frontmatter_reads_a_block_description():
    got, _ = frontmatter("---\ndescription: >\n  1 行目\n  2 行目\ntools: Read\n---\n")
    assert got == {"description": "1 行目 2 行目", "tools": "Read"}


@pytest.mark.parametrize("fm", ["tools: {a: 1}", "  - Read", "tools: [Read,", "tools ->", "model: a\nmodel: b"])
def test_frontmatter_stops_on_a_form_it_does_not_know(fm):
    with pytest.raises(ValueError):
        frontmatter(f"---\n{fm}\n---\n")


def test_frontmatter_without_closing_line_stops():
    with pytest.raises(ValueError):
        frontmatter("---\ntools: Read\n")


def test_frontmatter_strips_a_bom():
    assert frontmatter("\ufeff---\ntools: Read\n---\n本文") == ({"tools": "Read"}, "本文")


def test_real_agent_definitions_are_found():
    """下の全数の検査が 0 件で何も見ずに通らない（置き場を動かしたら、ここで赤になる）"""
    assert sorted(REPO.glob("*/agents/*.md"))


@pytest.mark.parametrize("path", sorted(REPO.glob("*/agents/*.md")), ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_every_real_agent_definition_reads(path):
    """リポジトリの実物の役の定義は全部読め、frontmatter を持つ（読めない形を足すと、その役の起動の前にここで赤になる）"""
    got, _ = frontmatter(path.read_text(encoding="utf-8"))
    assert got.get("name") or got.get("description"), path


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_record_read_resolves_a_relative_gitdir(tmp_path):
    """linked worktree の .git の相対の gitdir:（worktree.useRelativePaths）は .git のファイルの在る所から解く"""
    hook = _load(PLUGIN / "hooks" / "record-read.py", "record_read")
    gitdir = tmp_path / "main" / ".git" / "worktrees" / "wt"
    (gitdir / "graphloops" / "run1").mkdir(parents=True)
    board = tmp_path / "board"
    board.mkdir()
    (gitdir / "graphloops" / "run1" / "current").write_text(str(board), encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: ../main/.git/worktrees/wt\n", encoding="utf-8")
    assert hook.boards(wt) == [board]


def test_parallel_pr_stops_when_a_pr_file_list_is_short(monkeypatch, capsys):
    """PR の変更ファイルが PR の changedFiles に足りなければ、切れた一覧で交差を数えずに exit 1"""
    pp = _load(PLUGIN / "scripts" / "parallel-pr.py", "parallel_pr")
    monkeypatch.setattr(pp, "gh", lambda *a: "a.py\nb.py\n")
    assert pp.pr_files("o/r", {"number": 7, "changedFiles": 2}) == {"a.py", "b.py"}
    with pytest.raises(SystemExit) as e:
        pp.pr_files("o/r", {"number": 7, "changedFiles": 150})
    assert e.value.code == 1 and "#7" in capsys.readouterr().err
