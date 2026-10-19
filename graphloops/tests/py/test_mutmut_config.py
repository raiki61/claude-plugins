"""mutmut の設定（graphloops/setup.cfg の [mutmut]）。mutmut は graphloops/mutants/ に、source_paths と also_copy に並べた物だけを
写して試験を走らせるので、試験が読む置き場を also_copy から落とすと、写しの側で試験を集める所から落ちる（09-28〜10-12 の 3 回、
blocks/ が無くて graph の $ref が解けず、load_graph が None を返した。mutmut は CI でしか撃たないので、手元の試験で先に止める）"""
import configparser
import pathlib
import re

import conftest
import pytest

# 試験が読まないので写さない置き場（名前と訳）。ここに無い置き場は also_copy に並べる
NOT_READ = {"skills": "スキルの本文。mutmut が選ぶ試験（medium でない物）は読まない", "commands": "コマンドの本文。mutmut が選ぶ試験は読まない"}


def _mutmut():
    cfg = configparser.ConfigParser()
    cfg.read(conftest.PLUGIN / "setup.cfg", encoding="utf-8")
    return {k: [v.strip().rstrip("/") for v in cfg["mutmut"][k].splitlines() if v.strip()] for k in ("source_paths", "also_copy")}


@pytest.mark.small
def test_also_copy_lists_every_place_the_tests_read():
    m = _mutmut()
    have = set(m["source_paths"]) | set(m["also_copy"]) | set(NOT_READ)
    # mutants/ の写しの中で走るときは、写した置き場だけが在る（足りない物は、写しの外の graphloops/ で走る回が名指す）。
    # . で始まる置き場は、also_copy に並べた物（.claude-plugin）のほかは手元のキャッシュ（.pytest_cache・.venv など）として見ない
    dirs = {p.name for p in conftest.PLUGIN.iterdir() if p.is_dir() and p.name not in ("mutants", "__pycache__")
            and (not p.name.startswith(".") or p.name in m["also_copy"])}
    assert sorted(dirs - have) == [], "graphloops/setup.cfg の [mutmut] の also_copy に無い置き場（写しの側の試験が読めない）"


@pytest.mark.small
def test_tests_find_the_repo_root_by_walking_up():
    """この置き場（tests/py）の試験はリポジトリのルートを conftest.REPO（上へ辿って探す）で出す。graphloops の親をルートとみなすと、
    mutmut の写し（graphloops/mutants/）の中では graphloops/ を指し、隣の convergence-loops も CONTRIBUTING.md も見つからない。
    台本（graphloops/tests/simulate*.py）は見ない——台本に届くのは medium の印の試験だけで、mutmut は選ばない（setup.cfg）"""
    parent = re.compile(r"PLUGIN\)?\.parent\b")
    hits = [f"{p.name}:{i}" for p in sorted(conftest.HERE.glob("*.py")) if p.name not in ("conftest.py", pathlib.Path(__file__).name)
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if parent.search(line)]
    assert hits == [], "PLUGIN.parent でルートを出している（conftest.REPO を使う）"
