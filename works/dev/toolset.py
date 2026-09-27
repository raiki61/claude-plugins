"""works/dev/toolset.py — AI の役が読む、選んだ物だけの隔離した Claude の設定を組み、柵で確かめる（開発の殻。標準ライブラリだけ）。

  python3 toolset.py install [--no-plugins] [--claude <claude の実行ファイル>] <Claude の設定の置き場>
  python3 toolset.py guard <Claude の設定の置き場>

AI の節は全部 settingSources: [user] で、dev/archon.sh が隔離した CLAUDE_CONFIG_DIR を読む（P1 計画 Task 20・裁定 P1-R8）。
そこに置くのは許す一覧 .shared/borrow/borrow.json の物だけ:
- kind "skills"（superpowers）: 版を固めた写し .shared/<名>/<版>/skills/<スキル>/ の一覧のスキルだけを <置き場>/skills/<スキル>/ へ
  バイトのまま・権限つきで写す。プラグインとしては入れない（有効にすると SessionStart の hook が using-superpowers を差し込み、
  無人の役の約束が崩れる）。中身と実行の権限が同じなら何もしない。違えば一時の置き場に写してから入れ替える。
- kind "plugin" で pinned（pr-review-toolkit。Anthropic・Apache-2.0）: 版を固めた写し .shared/<名>/<版>/（ちょうど 1 つ）を、下の
  coldwrite と同じ手元の marketplace から入れる（素材集めの局所レビューのレンズの agent）。
- kind "plugin"（coldwrite）: このリポジトリの marketplace（.claude-plugin/marketplace.json。名は borrow の marketplace）が
  指す置き場を <置き場>/works-marketplace/<名>/ に写し、手元の marketplace works-local を書いて、Claude Code の CLI
  （`claude plugin marketplace add`・`claude plugin install <名>@works-local`）で入れる（試し plugin-hook-probe と同じ機構）。
  中身が同じで入っていれば CLI を呼ばない。変わっていれば marketplace を update し、入れ直す。CLI が 0 で終わっても
  settings.json の enabledPlugins に載らなければ止まる（フックの効かない役を起こさない）。--no-plugins（認証の要らない道。
  validate・テスト）は CLI を呼ばない。
- kind "mcp"（Context7。transport・url・licence）: 使用許諾が LICENCES_OK（MIT・Apache-2.0・BSD）の時だけ、<置き場>/works-mcp.json
  （{"mcpServers": {名: {type, url}}}）に載せる。許諾が外れなら何も写さずに止まる。Archon の役の節は周りの MCP（利用者・
  プラグインの MCP）を読まない（strictMcpConfig）ので、包み（.shared/core/adapter.py の 10）がこのファイルを web を持つ役の
  起動に --mcp-config で渡す（既定は渡さない。env の WORKS_CONTEXT7_MCP=on の時だけ）。
- 柵（guard）: 一覧の外を名前で並べる。CLAUDE.md・rules/・agents/・commands/・output-styles/・settings.json 以外の
  settings*.json・一覧の外のスキル・settings.json の鍵が {enabledPlugins, extraKnownMarketplaces} の外・一覧の外の有効な
  プラグイン・入れたプラグイン（plugins/installed_plugins.json）・marketplace（settings.json と plugins/known_marketplaces.json）・
  works-mcp.json の一覧の外の MCP。
  Claude Code が自分で書く状態（projects/・.claude.json・backups/・remote-settings.json・plugins/cache/ など）は見ない。
  install は組む前と後に柵を当て、当たれば何も写さずに止まる。CLI は 1 行を出して終了コード 2。
- 記録 <置き場>/.works-toolset.json: {名: {version, source, sha256, loaded}}（Task 21 の版上げ・書き出しが読む）。
自動の版上げ（利用者のキャッシュから選ぶ・関門）は Task 21。この版では fixed_sources（リポジトリの固定の置き場）から入れる。
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

MARKETPLACE = "works-local"                 # 隔離した設定の中の手元の marketplace の名
MP_DIR = "works-marketplace"                # その置き場（<設定の置き場>/works-marketplace）
RECORD = ".works-toolset.json"
MCP_FILE = "works-mcp.json"                 # 借りる MCP の置き場（包みが --mcp-config で役に渡す）
LICENCES_OK = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"})   # MCP を借りてよい使用許諾（SPDX の名）
SETTINGS_KEYS = frozenset({"enabledPlugins", "extraKnownMarketplaces"})
FOREIGN_FILES = ("CLAUDE.md",)
FOREIGN_DIRS = ("rules", "agents", "commands", "output-styles")
IGNORED_IN_SKILLS = frozenset({".DS_Store"})
TMP_MARK = ".works-tmp."
USAGE = ("toolset.py: 使い方: python3 toolset.py install [--no-plugins] [--claude <claude の実行ファイル>] <設定の置き場>"
         " | python3 toolset.py guard <設定の置き場>（install は --no-plugins か --claude のどちらか 1 つ）")


class ToolsetError(Exception):
    """組めない・柵に当たった。文は 1 行"""


def load_borrow(pack: pathlib.Path) -> dict:
    return json.loads((pathlib.Path(pack) / ".shared" / "borrow" / "borrow.json").read_text(encoding="utf-8"))


def fixed_sources(pack: pathlib.Path, borrow: dict) -> dict:
    """名 → 使う版の置き場（この版の固定: skills は .shared/<名>/<版>/、plugin はリポジトリの marketplace が指す置き場）"""
    pack = pathlib.Path(pack)
    out = {}
    for name, item in borrow.items():
        if item["kind"] == "skills":
            dirs = sorted(p.parent for p in (pack / ".shared" / name).glob("*/skills") if p.is_dir())
            if len(dirs) != 1:
                raise ToolsetError(f"{name} の版の置き場がちょうど 1 つでない（{pack / '.shared' / name}/<版>/skills: "
                                   f"{[d.name for d in dirs]}）")
            out[name] = dirs[0]
        elif item["kind"] == "plugin" and item.get("pinned"):
            dirs = sorted(p for p in (pack / ".shared" / name).iterdir() if p.is_dir()) if (pack / ".shared" / name).is_dir() else []
            if len(dirs) != 1:
                raise ToolsetError(f"{name} の版を固めた写しがちょうど 1 つでない（{pack / '.shared' / name}/<版>/: "
                                   f"{[d.name for d in dirs]}）")
            out[name] = dirs[0]
        elif item["kind"] == "plugin":
            repo = pack.parent
            mp_file = repo / ".claude-plugin" / "marketplace.json"
            try:
                mp = json.loads(mp_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise ToolsetError(f"{name} の元の marketplace を読めない（{mp_file}: {e}）") from None
            if mp.get("name") != item["marketplace"]:
                raise ToolsetError(f"{mp_file} の名が {mp.get('name')!r} で、borrow の {item['marketplace']!r} でない")
            entry = next((p for p in mp.get("plugins") or [] if p.get("name") == name), None)
            if entry is None or not isinstance(entry.get("source"), str):
                raise ToolsetError(f"{mp_file} に {name} の置き場（source）が無い")
            out[name] = (repo / entry["source"]).resolve()
        elif item["kind"] == "mcp":
            out[name] = item["url"]
        else:
            raise ToolsetError(f"borrow.json の {name} の kind {item['kind']!r} を知らない（skills・plugin・mcp）")
    return out


def _tree(base: pathlib.Path) -> dict:
    """{相対パス: (sha256, 実行できるか)}。diff -r と違い権限も見る"""
    out = {}
    for p in sorted(base.rglob("*")):
        if p.is_file():
            out[p.relative_to(base).as_posix()] = (hashlib.sha256(p.read_bytes()).hexdigest(), os.access(p, os.X_OK))
    return out


def _digest(trees: list) -> str:
    return hashlib.sha256(json.dumps(trees, sort_keys=True).encode()).hexdigest()


def _same(a: pathlib.Path, b: pathlib.Path) -> bool:
    return a.is_dir() and b.is_dir() and not b.is_symlink() and _tree(a) == _tree(b)


def _sync(src: pathlib.Path, dest: pathlib.Path) -> bool:
    """src を dest へ写す（同じなら何もしない）。一時の置き場に写してから入れ替え、読む側に消えた置き場を見せる時間を短くする。
    変えたら真"""
    if _same(src, dest):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}{TMP_MARK}{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp, symlinks=False, copy_function=shutil.copy2)
    if dest.is_dir() and not dest.is_symlink():
        shutil.rmtree(dest)
    elif dest.exists() or dest.is_symlink():
        dest.unlink()
    tmp.rename(dest)
    return True


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _clean_tmp(cfg: pathlib.Path) -> None:
    """落ちた install が残した一時の置き場（持ち主の pid がもう居ない物）だけを消す"""
    for parent in (cfg / "skills", cfg / MP_DIR):
        if not parent.is_dir():
            continue
        for p in parent.iterdir():
            if not (p.name.startswith(".") and TMP_MARK in p.name):
                continue
            pid = p.name.rsplit(".", 1)[-1]
            if pid.isdigit() and _alive(int(pid)):
                continue
            shutil.rmtree(p, ignore_errors=True)


_BAD = object()


def _read_json(p: pathlib.Path):
    """無ければ None、JSON の表として読めなければ _BAD"""
    if not p.exists():
        return None
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _BAD
    return v if isinstance(v, dict) else _BAD


def _keys(v) -> set:
    return set(v) if isinstance(v, dict) else set()


def guard(config_dir: pathlib.Path, borrow: dict) -> list:
    """一覧の外の物の名前の一覧（空なら通る）"""
    cfg = pathlib.Path(config_dir)
    skills = {s for i in borrow.values() if i["kind"] == "skills" for s in i["skills"]}
    plugins = {f"{n}@{MARKETPLACE}" for n, i in borrow.items() if i["kind"] == "plugin"}
    out = [n for n in FOREIGN_FILES if (cfg / n).exists()]
    out += sorted(p.name for p in cfg.glob("settings*.json") if p.name != "settings.json")
    out += [f"{d}/" for d in FOREIGN_DIRS if (cfg / d).exists()]
    sk = cfg / "skills"
    if sk.is_dir():
        for p in sorted(sk.iterdir()):
            if p.name not in IGNORED_IN_SKILLS and p.name not in skills:
                out.append(f"skills/{p.name}/" if p.is_dir() else f"skills/{p.name}")
    elif sk.exists():
        out.append("skills（フォルダでない）")
    st = _read_json(cfg / "settings.json")
    if st is _BAD:
        out.append("settings.json（JSON の表として読めない）")
    elif st is not None:
        out += [f"settings.json の鍵 {k}" for k in sorted(set(st) - SETTINGS_KEYS)]
        out += [f"有効なプラグイン {k}" for k in sorted(_keys(st.get("enabledPlugins")) - plugins)]
        out += [f"marketplace {k}（settings.json）" for k in sorted(_keys(st.get("extraKnownMarketplaces")) - {MARKETPLACE})]
    ip = _read_json(cfg / "plugins" / "installed_plugins.json")
    if ip is _BAD:
        out.append("plugins/installed_plugins.json（JSON の表として読めない）")
    elif ip is not None:
        out += [f"入れたプラグイン {k}" for k in sorted(_keys(ip.get("plugins")) - plugins)]
    km = _read_json(cfg / "plugins" / "known_marketplaces.json")
    if km is _BAD:
        out.append("plugins/known_marketplaces.json（JSON の表として読めない）")
    elif km is not None:
        out += [f"marketplace {k}（plugins/known_marketplaces.json）" for k in sorted(set(km) - {MARKETPLACE})]
    mf = _read_json(cfg / MCP_FILE)
    if mf is _BAD or (mf is not None and not isinstance(mf.get("mcpServers"), dict)):
        out.append(f"{MCP_FILE}（JSON の表として読めない）")
    elif mf is not None:
        mcps = {n for n, i in borrow.items() if i["kind"] == "mcp"}
        out += [f"{MCP_FILE} の MCP {k}" for k in sorted(set(mf["mcpServers"]) - mcps)]
    return out


def _mcp_servers(chosen: dict, borrow: dict) -> dict:
    """借りる MCP の {名: {type, url}}。使用許諾が LICENCES_OK の外なら ToolsetError（何も書く前に呼ぶ）"""
    out = {}
    for name, item in sorted(borrow.items()):
        if item["kind"] != "mcp":
            continue
        lic = item.get("licence")
        if lic not in LICENCES_OK:
            raise ToolsetError(f"{name} の使用許諾 {lic!r} は借りてよい物（{'・'.join(sorted(LICENCES_OK))}）でない。"
                               "隔離した設定に入れない")
        if item.get("transport") != "http" or not str(chosen.get(name) or "").startswith("https://"):
            raise ToolsetError(f"{name} は https の http の MCP でない（transport {item.get('transport')!r}・url {chosen.get(name)!r}）")
        out[name] = {"type": "http", "url": chosen[name]}
    return out


def _refusal(cfg: pathlib.Path, bad: list) -> str:
    return (f"Claude の設定の置き場（{cfg}）に、選んだ物（.shared/borrow/borrow.json）の外が在る: {', '.join(bad)}。"
            "settingSources: [user] の役に読ませないため止める。消すか、別の WORKS_DEV_HOME を使う")


def _claude(claude_bin: str, cfg: pathlib.Path, *args: str) -> None:
    r = subprocess.run([claude_bin, *args], env=dict(os.environ, CLAUDE_CONFIG_DIR=str(cfg)),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if r.returncode != 0:
        said = " / ".join((r.stderr or r.stdout).strip().splitlines())[-400:]
        raise ToolsetError(f"claude {' '.join(args)} が終了コード {r.returncode} で終わった: {said}")


def _write_if_changed(p: pathlib.Path, body: str) -> bool:
    if p.is_file() and p.read_text(encoding="utf-8") == body:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return True


def _install_plugins(cfg: pathlib.Path, srcs: dict, claude_bin: str) -> None:
    mp = cfg / MP_DIR
    changed = False
    for name, src in sorted(srcs.items()):
        if not (src / ".claude-plugin" / "plugin.json").is_file():
            raise ToolsetError(f"{name} の置き場（{src}）に .claude-plugin/plugin.json が無い")
        changed |= _sync(src, mp / name)
    manifest = {"name": MARKETPLACE, "owner": {"name": "works"},
                "plugins": [{"name": n, "source": f"./{n}", "strict": False} for n in sorted(srcs)]}
    changed |= _write_if_changed(mp / ".claude-plugin" / "marketplace.json",
                                 json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    known = _read_json(cfg / "plugins" / "known_marketplaces.json") or {}
    if MARKETPLACE not in known:
        _claude(claude_bin, cfg, "plugin", "marketplace", "add", str(mp))
    elif changed:
        _claude(claude_bin, cfg, "plugin", "marketplace", "update", MARKETPLACE)
    installed = (_read_json(cfg / "plugins" / "installed_plugins.json") or {}).get("plugins") or {}
    enabled = (_read_json(cfg / "settings.json") or {}).get("enabledPlugins") or {}
    for name, src in sorted(srcs.items()):
        key = f"{name}@{MARKETPLACE}"
        rows = installed.get(key) or []
        fresh = (bool(rows) and enabled.get(key) is True
                 and all(_same(pathlib.Path(r.get("installPath") or "/nonexistent"), src) for r in rows))
        if fresh:
            continue
        if rows:
            _claude(claude_bin, cfg, "plugin", "uninstall", key)
        _claude(claude_bin, cfg, "plugin", "install", key)


def install(config_dir: pathlib.Path, chosen: dict, borrow: dict, *, claude_bin, plugins: bool = True) -> dict:
    """隔離した設定を組む。返りと <置き場>/.works-toolset.json は {名: {version, source, sha256, loaded}}"""
    cfg = pathlib.Path(config_dir)
    _clean_tmp(cfg)
    bad = guard(cfg, borrow)
    if bad:
        raise ToolsetError(_refusal(cfg, bad))
    mcp = _mcp_servers(chosen, borrow)
    rec = {}
    for name, item in borrow.items():
        if item["kind"] != "skills":
            continue
        src = pathlib.Path(chosen[name])
        trees = []
        for s in item["skills"]:
            d = src / "skills" / s
            if not (d / "SKILL.md").is_file():
                raise ToolsetError(f"{name} のスキル {s} が {d} に無い")
            _sync(d, cfg / "skills" / s)
            trees.append([s, _tree(d)])
        rec[name] = {"version": src.name, "source": str(src), "sha256": _digest(trees), "loaded": True}
    srcs = {n: pathlib.Path(chosen[n]) for n, i in borrow.items() if i["kind"] == "plugin"}
    if plugins and srcs:
        if not claude_bin:
            raise ToolsetError("プラグインを入れる claude の実行ファイルが渡されていない（--claude）")
        _install_plugins(cfg, srcs, claude_bin)
    enabled = (_read_json(cfg / "settings.json") or {}).get("enabledPlugins") or {}
    for name, src in sorted(srcs.items()):
        key = f"{name}@{MARKETPLACE}"
        loaded = enabled.get(key) is True
        if plugins and not loaded:
            raise ToolsetError(f"{name} が隔離した設定で有効になっていない（claude plugin install の後の settings.json の "
                               f"enabledPlugins に {key}: true が無い）。フックの効かない役を起こさないため止める")
        meta = _read_json(src / ".claude-plugin" / "plugin.json")
        version = meta.get("version") if isinstance(meta, dict) else None
        if not version and borrow[name].get("pinned"):
            version = src.name   # 版を固めた写しの置き場の名（plugin.json に version を持たないプラグイン。pr-review-toolkit）
        rec[name] = {"version": version, "source": str(src),
                     "sha256": _digest([name, _tree(src)]), "loaded": loaded}
    if mcp:
        _write_if_changed(cfg / MCP_FILE, json.dumps({"mcpServers": mcp}, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    elif (cfg / MCP_FILE).exists():
        (cfg / MCP_FILE).unlink()
    for name, server in mcp.items():
        rec[name] = {"version": borrow[name].get("version"), "source": server["url"],
                     "sha256": _digest([name, server]), "loaded": True}
    bad = guard(cfg, borrow)
    if bad:
        raise ToolsetError(_refusal(cfg, bad))
    _write_if_changed(cfg / RECORD, json.dumps(rec, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return rec


def main(argv: list) -> int:
    args = argv[1:]
    if not args or args[0] not in ("install", "guard"):
        print(USAGE, file=sys.stderr)
        return 2
    cmd, rest = args[0], args[1:]
    no_plugins, claude_bin, pos = False, None, []
    while rest:
        a = rest.pop(0)
        if cmd == "install" and a == "--no-plugins":
            no_plugins = True
        elif cmd == "install" and a == "--claude" and rest:
            claude_bin = rest.pop(0)
        elif a.startswith("--"):
            print(USAGE, file=sys.stderr)
            return 2
        else:
            pos.append(a)
    if len(pos) != 1 or (cmd == "install" and no_plugins == bool(claude_bin)):
        print(USAGE, file=sys.stderr)
        return 2
    cfg = pathlib.Path(pos[0])
    pack = pathlib.Path(__file__).resolve().parents[1]
    try:
        borrow = load_borrow(pack)
        if cmd == "guard":
            bad = guard(cfg, borrow)
            if bad:
                raise ToolsetError(_refusal(cfg, bad))
        else:
            install(cfg, fixed_sources(pack, borrow), borrow, claude_bin=claude_bin, plugins=not no_plugins)
    except ToolsetError as e:
        print(f"toolset.py: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
