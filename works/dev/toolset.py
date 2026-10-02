"""works/dev/toolset.py — AI の役が読む、選んだ物だけの隔離した Claude の設定を組み、柵で確かめる（開発の殻。標準ライブラリだけ）。

  python3 toolset.py install [--no-plugins] [--claude <claude の実行ファイル>] [--user-config <利用者の設定の置き場>] <Claude の設定の置き場>
  python3 toolset.py guard <Claude の設定の置き場>
  python3 toolset.py vendor [--user-config <利用者の設定の置き場>] <superpowers の版>

AI の節は全部 settingSources: [user] で、dev/archon.sh が隔離した CLAUDE_CONFIG_DIR を読む（P1 計画 Task 20・裁定 P1-R8）。
そこに置くのは許す一覧 .shared/borrow/borrow.json の物だけ。借りる物（superpowers・coldwrite・pr-review-toolkit）は、利用者が
Claude Code に入れたプラグインから取る（本線の graphloops と同じ。版は Claude Code が今に保つ。superpowers の写しは下の vendor）:
- 探す所: 利用者の設定の置き場（--user-config。無ければ env の CLAUDE_CONFIG_DIR、無ければ ~/.claude。隔離した設定ではない。
  archon.sh は隔離の前の値を渡す。絶対パスだけを受け、隔離した設定の置き場と同じなら名指しして止まる）の plugins/installed_plugins.json の <名>@<borrow の marketplace> の行。Claude Code と同じく
  local > project > user の scope の行を取る（local・project は projectPath が今の cwd（対象リポジトリ）の行だけ。勝った行の
  installPath が無ければ下の scope へ落ちずに入っていないとする）。enabledPlugins で無効でも借りる（記録に残すだけ）。
  installed_plugins.json が知らない形（version が INSTALLED_VERSIONS の外など）なら、入っていないとは言わずに形を名指しして止まる。
- 確かめるのは、works が名前で頼る物が在ることだけ（中身・版・バイトは見ない。役は読むだけなので、名前が在れば新しい版で動く）:
  superpowers は skills/<スキル>/SKILL.md、pr-review-toolkit は agents/<名>.md（borrow の agents。レンズの名）、coldwrite は
  hooks/hooks.json の hooks.<事象> に matcher が borrow の hooks の物の行。入っていない・名前が無い物は、借りる物ごとに 1 行の
  理由と入れるコマンドを並べ、何も写さずに止まる（AI を起こさない）。
- kind "skills"（superpowers）: 入れた置き場の skills/<スキル>/ の一覧のスキルだけを <置き場>/skills/<スキル>/ へ
  バイトのまま・権限つきで写す。プラグインとしては入れない（有効にすると SessionStart の hook が using-superpowers を差し込み、
  無人の役の約束が崩れる）。中身と実行の権限が同じなら何もしない。違えば一時の置き場に写してから入れ替える。
- kind "plugin"（coldwrite・pr-review-toolkit）: 入れた置き場を <置き場>/works-marketplace/<名>/ に写し、手元の marketplace
  works-local を書いて、Claude Code の CLI（`claude plugin marketplace add`・`claude plugin install <名>@works-local`）で入れる
  （試し plugin-hook-probe と同じ機構）。coldwrite は書く散文の初見検査のフック、pr-review-toolkit は素材集めの局所レビューの
  レンズの agent。中身が同じで入っていれば CLI を呼ばない。変わっていれば marketplace を update し、入れ直す。CLI が 0 で
  終わっても settings.json の enabledPlugins に載らなければ止まる（フックの効かない役を起こさない）。--no-plugins（認証の
  要らない道。validate・テスト）は CLI を呼ばない（探して名前を確かめるのは同じ）。
  Claude Code がキャッシュの版の置き場に置く印（MARKERS）は写さず、比べもしない。
- kind "mcp"（Context7。transport・url・licence）: 使用許諾が LICENCES_OK（MIT・Apache-2.0・BSD）の時だけ、<置き場>/works-mcp.json
  （{"mcpServers": {名: {type, url}}}）に載せる。許諾が外れなら何も写さずに止まる。Archon の役の節は周りの MCP（利用者・
  プラグインの MCP）を読まない（strictMcpConfig）ので、包み（.shared/core/adapter.py の 10）がこのファイルを web を持つ役の
  起動に --mcp-config で渡す（既定は渡さない。env の WORKS_CONTEXT7_MCP=on の時だけ）。
- 柵（guard）: 一覧の外を名前で並べる。CLAUDE.md・rules/・agents/・commands/・output-styles/・settings.json 以外の
  settings*.json・一覧の外のスキル・settings.json の鍵が {enabledPlugins, extraKnownMarketplaces} の外・一覧の外の有効な
  プラグイン・入れたプラグイン（plugins/installed_plugins.json）・marketplace（settings.json と plugins/known_marketplaces.json）・
  works-mcp.json の一覧の外の MCP。
  Claude Code が自分で書く状態（projects/・.claude.json・backups/・remote-settings.json・plugins/cache/ など）は見ない。
  install は組む前と後に柵を当て、当たれば何も写さずに止まる。CLI は 1 行を出して終了コード 2（入っていない物は 1 物 1 行）。
- 記録 <置き場>/.works-toolset.json: {名: {version, source, sha256, loaded[, source_enabled]}}（見えるようにするだけ。run ごとの
  versions.json の borrowed に載る）。version は installed_plugins.json の行の version、source は入れた置き場、source_enabled は
  利用者の側の enabledPlugins の値（CLI の install が載せる。source_enabled を見よ）。
- 写し（vendor）: 利用者のキャッシュの superpowers の 1 つの版（<利用者の設定の置き場>/plugins/cache/<marketplace>/superpowers/<版>。
  網からは取らない。版は人が名指す）から、包むファイル（.shared/core/spseam.py の wrapped_files。借りるスキルの全ファイル・
  部品 parts・LICENSE）だけを .shared/borrow/superpowers/<版>/ へバイトのまま・権限つきで写し、ほかの版の写しを消し、写しの台帳
  .shared/borrow/superpowers/COPIED_FROM と borrow.json の superpowers.pin（版・commit・確かめた日・ファイルごとの sha256）を
  書き直す。commit は installed_plugins.json の行のうち installPath がその版の置き場の行の gitCommitSha（無ければ null）。
  使用許諾のファイルが MIT License で borrow.json の licence と合う時だけ写す（外れなら何も書かずに止まる）。写しは直さない。
  写しを変えるのはこの口だけで、写し・台帳・pin を同じ 1 つの commit に入れる。
"""
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / ".shared" / "core"))
import spseam  # noqa: E402

MARKETPLACE = "works-local"                 # 隔離した設定の中の手元の marketplace の名
MP_DIR = "works-marketplace"                # その置き場（<設定の置き場>/works-marketplace）
# Claude Code が起動の時に自分で足す公式の marketplace（名と GitHub の repo が両方合う時だけ）。登録だけで、入れた・有効な
# プラグインは増えない（それは installed_plugins.json・enabledPlugins の検査が見る）ので、選んだ物の外に数えない
OFFICIAL_MARKETPLACE = ("claude-plugins-official", "anthropics/claude-plugins-official")


def _official(name, entry) -> bool:
    src = entry.get("source") if isinstance(entry, dict) else None
    return (name == OFFICIAL_MARKETPLACE[0] and isinstance(src, dict) and src.get("source") == "github"
            and src.get("repo") == OFFICIAL_MARKETPLACE[1])
RECORD = ".works-toolset.json"
MCP_FILE = "works-mcp.json"                 # 借りる MCP の置き場（包みが --mcp-config で役に渡す）
LICENCES_OK = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"})   # MCP を借りてよい使用許諾（SPDX の名）
SETTINGS_KEYS = frozenset({"enabledPlugins", "extraKnownMarketplaces"})
FOREIGN_FILES = ("CLAUDE.md",)
FOREIGN_DIRS = ("rules", "agents", "commands", "output-styles")
IGNORED_IN_SKILLS = frozenset({".DS_Store"})
MARKERS = frozenset({".in_use", ".orphaned_at"})   # Claude Code がプラグインのキャッシュの版の置き場に置く印（使っている pid・捨てた時刻）
USER_CONFIG_DEFAULT = "~/.claude"
TMP_MARK = ".works-tmp."
USAGE = ("toolset.py: 使い方: python3 toolset.py install [--no-plugins] [--claude <claude の実行ファイル>] "
         "[--user-config <利用者の設定の置き場>] <設定の置き場>"
         " | python3 toolset.py guard <設定の置き場>"
         " | python3 toolset.py vendor [--user-config <利用者の設定の置き場>] <superpowers の版>"
         "（install は --no-plugins か --claude のどちらか 1 つ）")
VENDORED = "superpowers"                    # 写しを持つ借りる物（.shared/borrow/<この名>/<版>/）
LEDGER = "COPIED_FROM"                      # 写しの台帳の名（.shared/borrow/superpowers/ の下。形は .shared/core/copyledger.py）
LICENCE_HEADS = {"MIT": "MIT License"}      # borrow.json の licence → 使用許諾のファイルの頭の行（写してよい物だけ）
UPSTREAM = "github.com/obra/superpowers"    # 写し元の系統（台帳の 1 行目に書く）
VERSION_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]*")   # 写す版の名（フォルダの名になる。/ や .. で外を指させない）


class ToolsetError(Exception):
    """組めない・柵に当たった。文は 1 行"""


def load_borrow(pack: pathlib.Path) -> dict:
    return json.loads((pathlib.Path(pack) / ".shared" / "borrow" / "borrow.json").read_text(encoding="utf-8"))


SCOPES = ("local", "project", "user")      # 勝つ順（Claude Code の discover-plugins の Which scope wins。managed は読まない）
INSTALLED_VERSIONS = frozenset({2})        # 読める installed_plugins.json の version（形は公式に文書化されていない）


def _read_installed(user_config: pathlib.Path) -> dict:
    """利用者の plugins/installed_plugins.json の plugins（{<名>@<marketplace>: [行]}）。無ければ空。知らない形（version が
    INSTALLED_VERSIONS の外・plugins が表でない・行の並びが表の一覧でない・JSON として読めない）は『入っていない』に潰さず、
    形を知らないと名指しして ToolsetError"""
    p = pathlib.Path(user_config) / "plugins" / "installed_plugins.json"
    ip = _read_json(p)
    if ip is None:
        return {}
    plugins = ip.get("plugins") if isinstance(ip, dict) else None
    if (isinstance(ip, dict) and ip.get("version") in INSTALLED_VERSIONS and isinstance(plugins, dict)
            and all(isinstance(rows, list) and all(isinstance(r, dict) for r in rows) for rows in plugins.values())):
        return plugins
    version = ip.get("version") if isinstance(ip, dict) else None
    raise ToolsetError(f"{p} の形（version {version}）を知らない（読めるのは version "
                       f"{'・'.join(map(str, sorted(INSTALLED_VERSIONS)))}）。Claude Code の版を確かめ、合う works に更新する")


def _installed_row(plugins: dict, key: str, cwd) -> "dict | None":
    """installed_plugins.json の plugins の key の行のうち、Claude Code が cwd で使う物（SCOPES の順で最初に在る scope の行。
    local・project は projectPath が cwd の行だけ）。勝った行の installPath が無ければ、下の scope へ落ちずに None"""
    rows = [r for r in plugins.get(key, []) if isinstance(r.get("installPath"), str)]
    here = os.path.realpath(cwd) if cwd else None
    rows = [r for r in rows if r.get("scope") == "user" or (
        r.get("scope") in ("project", "local") and here and isinstance(r.get("projectPath"), str)
        and os.path.realpath(r["projectPath"]) == here)]
    row = min(rows, key=lambda r: SCOPES.index(r["scope"]), default=None)
    return row if row is not None and pathlib.Path(row["installPath"]).is_dir() else None


def source_enabled(user_config: pathlib.Path, key: str, cwd) -> "bool | None":
    """key が利用者の側で有効か（enabledPlugins。対象の .claude/settings.local.json → .claude/settings.json → 利用者の
    settings.json の順（SCOPES の順）で最初に鍵を持つ物。Claude Code の Settings precedence。どこにも無ければ None）。無効でも借りる
    （利用者は借りる物のフックを普段効かせないために無効にしておく）ので、記録に残すだけ"""
    where = {"local": pathlib.Path(cwd or "") / ".claude" / "settings.local.json",
             "project": pathlib.Path(cwd or "") / ".claude" / "settings.json",
             "user": pathlib.Path(user_config) / "settings.json"}
    for f in [where[s] for s in SCOPES if cwd or s == "user"]:     # _installed_row と同じ SCOPES の順
        st = _read_json(f)
        enabled = st.get("enabledPlugins") if isinstance(st, dict) else None
        if isinstance(enabled, dict) and isinstance(enabled.get(key), bool):
            return enabled[key]
    return None


def _missing_names(name: str, item: dict, src: pathlib.Path) -> list:
    """works が名前で頼る物のうち、入れた置き場 src に無い物（中身・版は見ない）"""
    out = []
    if item["kind"] == "skills":
        out += [f"スキル {s}（skills/{s}/SKILL.md）" for s in item["skills"] if not (src / "skills" / s / "SKILL.md").is_file()]
    if item["kind"] == "plugin" and not (src / ".claude-plugin" / "plugin.json").is_file():
        out.append("プラグインの定義（.claude-plugin/plugin.json）")
    out += [f"agent {a}（agents/{a}.md）" for a in item.get("agents", []) if not (src / "agents" / f"{a}.md").is_file()]
    if item.get("hooks"):
        hooks = _read_json(src / "hooks" / "hooks.json")
        table = hooks.get("hooks") if isinstance(hooks, dict) else None
        for event, matchers in sorted(item["hooks"].items()):
            rows = table.get(event) if isinstance(table, dict) else None
            have = {r.get("matcher") for r in rows if isinstance(r, dict)} if isinstance(rows, list) else set()
            out += [f"hook {event}:{m}（hooks/hooks.json）" for m in matchers if m not in have]
    return out


def _how_to_install(name: str, item: dict) -> str:
    key = f"{name}@{item['marketplace']}"
    return (f"入れる: claude plugin marketplace add {item['marketplace_repo']}（登録済みなら要らない）→ "
            f"claude plugin install {key}")


def user_config_dir(env=None) -> pathlib.Path:
    """利用者の Claude の設定の置き場（env の CLAUDE_CONFIG_DIR、無ければ ~/.claude）"""
    env = os.environ if env is None else env
    return pathlib.Path(env.get("CLAUDE_CONFIG_DIR") or os.path.expanduser(USER_CONFIG_DEFAULT))


def installed_sources(user_config: pathlib.Path, borrow: dict, cwd=None) -> tuple:
    """(名 → 使う置き場（mcp は url）, 名 → 版)。借りる物は利用者が入れたプラグインからだけ取る。入っていない・works が名前で
    頼る物が無い借りる物は、借りる物ごとに 1 行の理由と入れるコマンドを並べて ToolsetError（何も写す前に呼ぶ）"""
    user_config = pathlib.Path(user_config)
    chosen, versions, bad = {}, {}, []
    plugins = _read_installed(user_config) if any(i["kind"] != "mcp" for i in borrow.values()) else {}
    for name, item in borrow.items():
        if item["kind"] == "mcp":
            chosen[name] = item["url"]
            versions[name] = item.get("version")
            continue
        if item["kind"] not in ("skills", "plugin"):
            raise ToolsetError(f"borrow.json の {name} の kind {item['kind']!r} を知らない（skills・plugin・mcp）")
        key = f"{name}@{item['marketplace']}"
        row = _installed_row(plugins, key, cwd)
        if row is None:
            bad.append(f"{name} が入っていない（{user_config / 'plugins' / 'installed_plugins.json'} に {key} の使える行が無い）。"
                       + _how_to_install(name, item))
            continue
        src = pathlib.Path(row["installPath"])
        missing = _missing_names(name, item, src)
        if missing:
            bad.append(f"{name}（{src}）に works が使う {'・'.join(missing)} が無い。"
                       f"版を確かめる（claude plugin update {key}）か入れ直す。" + _how_to_install(name, item))
            continue
        chosen[name] = src
        versions[name] = row.get("version") if isinstance(row.get("version"), str) else src.name
    if bad:
        raise ToolsetError("借りる物が足りない。AI を起こさずに止める:\n" + "\n".join(f"- {b}" for b in bad))
    return chosen, versions


def _tree(base: pathlib.Path) -> dict:
    """{相対パス: (sha256, 実行できるか)}。diff -r と違い権限も見る"""
    out = {}
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base)
        if p.is_file() and not MARKERS & set(rel.parts):
            out[rel.as_posix()] = (hashlib.sha256(p.read_bytes()).hexdigest(), os.access(p, os.X_OK))
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
    shutil.copytree(src, tmp, symlinks=False, copy_function=shutil.copy2, ignore=shutil.ignore_patterns(*MARKERS))
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
        out += [f"marketplace {k}（plugins/known_marketplaces.json）" for k in sorted(set(km) - {MARKETPLACE})
                if not _official(k, km[k])]
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
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8")
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


def install(config_dir: pathlib.Path, chosen: dict, borrow: dict, *, claude_bin, plugins: bool = True,
            versions: "dict | None" = None, enabled: "dict | None" = None) -> dict:
    """隔離した設定を組む。chosen・versions は installed_sources の返り（versions に無い名は置き場の名・plugin.json の version）。
    enabled は 名 → source_enabled の値（渡された名だけ記録に source_enabled として載せる）。
    返りと <置き場>/.works-toolset.json は {名: {version, source, sha256, loaded[, source_enabled]}}"""
    versions = versions or {}
    enabled_src = enabled or {}
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
        rec[name] = {"version": versions.get(name) or src.name, "source": str(src), "sha256": _digest(trees), "loaded": True}
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
        # 版は installed_plugins.json の行の物。plugin.json に version を持たないプラグイン（pr-review-toolkit）もあるので、
        # 無ければ plugin.json、それも無ければキャッシュの版の置き場の名
        version = versions.get(name) or (meta.get("version") if isinstance(meta, dict) else None) or src.name
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
    for name in rec.keys() & enabled_src.keys():
        rec[name]["source_enabled"] = enabled_src[name]
    _write_if_changed(cfg / RECORD, json.dumps(rec, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return rec


def _licence_notice(src: pathlib.Path, item: dict) -> str:
    """使用許諾のファイル（borrow.json の licence_file）の Copyright の行。ファイルが無い・頭が MIT License でない・borrow.json の
    licence と合わない・Copyright の行が無い、のどれかなら ToolsetError（何も書く前に呼ぶ）"""
    rel, lic = item.get("licence_file"), item.get("licence")
    if not rel or not (src / rel).is_file() or (src / rel).is_symlink():
        raise ToolsetError(f"{src} に使用許諾のファイル（borrow.json の licence_file {rel!r}）が無い。写さない")
    text = (src / rel).read_text(encoding="utf-8", errors="replace")
    head = LICENCE_HEADS.get(lic)
    if head is None or not text.startswith(head):
        raise ToolsetError(f"{src / rel} の頭が borrow.json の licence {lic!r} と合わない（写してよいのは "
                           f"{'・'.join(LICENCE_HEADS.values())}）。写さない")
    notice = next((ln.strip() for ln in text.splitlines() if ln.strip().startswith("Copyright")), None)
    if notice is None:
        raise ToolsetError(f"{src / rel} に Copyright の行が無い（著作権の表示を写しに残せない）。写さない")
    return notice


def vendor(pack: pathlib.Path, src: pathlib.Path, version: str, commit: "str | None", checked: str) -> dict:
    """利用者のキャッシュの superpowers の版のフォルダ src の包むファイル（spseam.wrapped_files）を
    pack/.shared/borrow/superpowers/<version>/ へバイトのまま・権限つきで写し、ほかの版のフォルダを消し、台帳 COPIED_FROM と
    borrow.json の superpowers.pin を書き直して、新しい pin を返す。使用許諾が合わない・借りるスキルの SKILL.md か部品が無い・
    symlink か外を指すパスが在る・パスに空白か # が在る（台帳に書けない）、のどれかなら何も書かずに ToolsetError"""
    pack, src = pathlib.Path(pack), pathlib.Path(src)
    _check_version_name(version)
    bj = pack / ".shared" / "borrow" / "borrow.json"
    borrow = json.loads(bj.read_text(encoding="utf-8"))
    item = borrow[VENDORED]
    if not src.is_dir():
        raise ToolsetError(f"{VENDORED} の版のフォルダ {src} が無い")
    notice = _licence_notice(src, item)
    lack = [f"skills/{s}/SKILL.md" for s in item["skills"] if not (src / "skills" / s / "SKILL.md").is_file()]
    lack += [r for r in item.get("parts", []) if not (src / r).is_file()]
    if lack:
        raise ToolsetError(f"{src} に借りる物が無い: {'・'.join(lack)}。写さない")
    files = spseam.wrapped_files(src, item)
    bad = spseam.pin_problems(src, dict(item, pin={"files": files}))   # 読まなかった物（symlink・外を指すパス）だけが残る
    bad += [f"{r}: パスに空白か # が在る（台帳に書けない）" for r in files if any(c.isspace() or c == "#" for c in r)]
    if bad:
        raise ToolsetError(f"{src} を写せない: " + " / ".join(bad))
    base = pack / ".shared" / "borrow" / VENDORED
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / f".{version}{TMP_MARK}{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        for rel in files:
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, tmp / rel)
        pin = spseam.pin_of(tmp, item, version, commit, checked)
        if pin["files"] != files:
            raise ToolsetError(f"写しの sha256 が元と違う（写している間に {src} が変わった？）。写さない")
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    head = (f"{commit or 'unknown'}  {VENDORED} {version}（{UPSTREAM}。{LICENCE_HEADS[item['licence']]}・{notice}。"
            f"直さない写し。取り直しは dev/toolset.py vendor）")
    ledger = "\n".join([head, *(f"{version}/{rel}  {rel}" for rel in files)]) + "\n"
    item["pin"] = pin
    for old in base.iterdir():
        if old == tmp or old.name == LEDGER:
            continue
        if old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
        else:
            old.unlink()
    tmp.rename(base / version)
    (base / LEDGER).write_text(ledger, encoding="utf-8")
    bj.write_text(json.dumps(borrow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return pin


def _check_version_name(version: str) -> None:
    if not VERSION_NAME.fullmatch(version or ""):
        raise ToolsetError(f"版の名 {version!r} はフォルダの名にできない（英数字で始まり、英数字と . _ + - だけ）")


def _commit_of(user_cfg: pathlib.Path, src: pathlib.Path) -> "str | None":
    """installed_plugins.json の行のうち installPath が src の行の gitCommitSha（無ければ None）"""
    for rows in _read_installed(user_cfg).values():
        for r in rows:
            sha = r.get("gitCommitSha")
            if (isinstance(r.get("installPath"), str) and isinstance(sha, str) and sha
                    and os.path.realpath(r["installPath"]) == os.path.realpath(src)):
                return sha
    return None


def _vendor_cli(pack: pathlib.Path, user_cfg: "pathlib.Path | None", version: str) -> int:
    _check_version_name(version)
    user_cfg = user_cfg or user_config_dir()
    item = load_borrow(pack)[VENDORED]
    src = user_cfg / "plugins" / "cache" / item["marketplace"] / VENDORED / version
    if not src.is_dir():
        print(f"toolset.py: {VENDORED} {version} の版のフォルダ {src} が無い（claude plugin install で入れた版だけを写せる）",
              file=sys.stderr)
        return 2
    pin = vendor(pack, src, version, _commit_of(user_cfg, src), datetime.date.today().isoformat())
    print(f"toolset.py: {VENDORED} {pin['version']} の {len(pin['files'])} 本を .shared/borrow/{VENDORED}/{pin['version']}/ に写した"
          f"（commit {pin['commit'] or 'unknown'}）")
    return 0


def _check_user_config(user_cfg: pathlib.Path, cfg: pathlib.Path, src: str) -> None:
    """利用者の設定の置き場は絶対パスで、隔離した設定の置き場と別であること（どちらも何も写す前に名指しで止める）"""
    if not user_cfg.is_absolute():
        raise ToolsetError(f"利用者の設定の置き場（{src}）が相対パス（{user_cfg}）。絶対パスで渡す"
                           "（殻は guard.sh の works_dev_abs_claude_config で cd の前に直す）")
    if os.path.realpath(user_cfg) == os.path.realpath(cfg):
        raise ToolsetError(f"利用者の設定の置き場（{src}: {user_cfg}）が隔離した設定の置き場そのもの（殻の中から入れ子で"
                           "打った？）。CLAUDE_CONFIG_DIR を利用者の物にして回す")


def main(argv: list) -> int:
    args = argv[1:]
    if not args or args[0] not in ("install", "guard", "vendor"):
        print(USAGE, file=sys.stderr)
        return 2
    cmd, rest = args[0], args[1:]
    no_plugins, claude_bin, user_cfg, pos = False, None, None, []
    while rest:
        a = rest.pop(0)
        if cmd == "install" and a == "--no-plugins":
            no_plugins = True
        elif cmd == "install" and a == "--claude" and rest:
            claude_bin = rest.pop(0)
        elif cmd in ("install", "vendor") and a == "--user-config" and rest:
            user_cfg = pathlib.Path(rest.pop(0))
        elif a.startswith("--"):
            print(USAGE, file=sys.stderr)
            return 2
        else:
            pos.append(a)
    if len(pos) != 1 or (cmd == "install" and no_plugins == bool(claude_bin)):
        print(USAGE, file=sys.stderr)
        return 2
    pack = pathlib.Path(__file__).resolve().parents[1]
    if cmd == "vendor":
        try:
            return _vendor_cli(pack, user_cfg, pos[0])
        except ToolsetError as e:
            print(f"toolset.py: {e}", file=sys.stderr)
            return 2
    cfg = pathlib.Path(pos[0])
    try:
        borrow = load_borrow(pack)
        if cmd == "guard":
            bad = guard(cfg, borrow)
            if bad:
                raise ToolsetError(_refusal(cfg, bad))
        else:
            src = "--user-config" if user_cfg else "env の CLAUDE_CONFIG_DIR"
            user_cfg, here = user_cfg or user_config_dir(), os.getcwd()
            _check_user_config(user_cfg, cfg, src)
            chosen, versions = installed_sources(user_cfg, borrow, cwd=here)
            enabled = {n: source_enabled(user_cfg, f"{n}@{i['marketplace']}", here)
                       for n, i in borrow.items() if i["kind"] in ("skills", "plugin")}
            install(cfg, chosen, borrow, claude_bin=claude_bin, plugins=not no_plugins, versions=versions, enabled=enabled)
    except ToolsetError as e:
        print(f"toolset.py: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv))
