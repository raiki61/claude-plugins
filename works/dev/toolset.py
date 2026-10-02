"""works/dev/toolset.py — AI の役が読む、選んだ物だけの隔離した Claude の設定を組み、柵で確かめる（開発の殻。標準ライブラリだけ）。

  python3 toolset.py install [--no-plugins] [--claude <claude の実行ファイル>] [--user-config <利用者の設定の置き場>] <Claude の設定の置き場>
  python3 toolset.py guard <Claude の設定の置き場>
  python3 toolset.py vendor [--user-config <利用者の設定の置き場>] <superpowers の版>
  python3 toolset.py contract [--user-config <利用者の設定の置き場>] [<superpowers の版>]

AI の節は全部 settingSources: [user] で、dev/archon.sh が隔離した CLAUDE_CONFIG_DIR を読む（P1 計画 Task 20・裁定 P1-R8）。
そこに置くのは許す一覧 .shared/borrow/borrow.json の物だけ。借りる物の取り元は 2 つに分かれる:
- superpowers（kind "skills"）: works に写した固定の版（.shared/borrow/superpowers/<版>/。下の vendor が作る）から入れる。
  利用者の installed_plugins.json の superpowers の行は読まない（入れた版は run に使わず、開発の再開の確かめが比べるだけ）。
  写しの包むファイルが borrow.json の superpowers.pin の sha256 と合わなければ（spseam.pin_problems）、違うファイルを 1 行ずつ
  名指して、何も写さずに止まる。
- coldwrite・pr-review-toolkit（kind "plugin"）: 利用者が Claude Code に入れたプラグインから取る（本線の graphloops と同じ。版は
  Claude Code が今に保ち、入れた版をそのまま使う）。
- 探す所（kind "plugin"）: 利用者の設定の置き場（--user-config。無ければ env の CLAUDE_CONFIG_DIR、無ければ ~/.claude。隔離した設定ではない。
  archon.sh は隔離の前の値を渡す。絶対パスだけを受け、隔離した設定の置き場と同じなら名指しして止まる）の plugins/installed_plugins.json の <名>@<borrow の marketplace> の行。Claude Code と同じく
  local > project > user の scope の行を取る（local・project は projectPath が今の cwd（対象リポジトリ）の行だけ。勝った行の
  installPath が無ければ下の scope へ落ちずに入っていないとする）。enabledPlugins で無効でも借りる（記録に残すだけ）。
  installed_plugins.json が知らない形（version が INSTALLED_VERSIONS の外など）なら、入っていないとは言わずに形を名指しして止まる。
- kind "plugin" で確かめるのは、works が名前で頼る物が在ることだけ（中身・版・バイトは見ない。役は読むだけなので、名前が在れば
  新しい版で動く）: pr-review-toolkit は agents/<名>.md（borrow の agents。レンズの名）、coldwrite は hooks/hooks.json の
  hooks.<事象> に matcher が borrow の hooks の物の行。入っていない・名前が無い物は、借りる物ごとに 1 行の理由と入れるコマンドを
  並べ、何も写さずに止まる（AI を起こさない）。写しが pin と合わない superpowers の行も同じ 1 つの止まりにまとめる。
- kind "skills"（superpowers）: 写しの skills/<スキル>/ の一覧のスキルだけを <置き場>/skills/<スキル>/ へ、部品（parts。スキル
  としては使わず、中の文を役の指示書に使うファイル）を <置き場>/works-parts/superpowers/<相対パス> へ、バイトのまま・権限つきで
  写す。プラグインとしては入れない（有効にすると SessionStart の hook が using-superpowers を差し込み、無人の役の約束が崩れる）。
  中身と実行の権限が同じなら何もしない。違えば一時の置き場に写してから入れ替える。
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
  settings*.json・一覧の外のスキル・works-parts/ の下の部品の外のファイル・settings.json の鍵が {enabledPlugins,
  extraKnownMarketplaces} の外・一覧の外の有効な
  プラグイン・入れたプラグイン（plugins/installed_plugins.json）・marketplace（settings.json と plugins/known_marketplaces.json）・
  works-mcp.json の一覧の外の MCP。
  Claude Code が自分で書く状態（projects/・.claude.json・backups/・remote-settings.json・plugins/cache/ など）は見ない。
  install は組む前と後に柵を当て、当たれば何も写さずに止まる。CLI は 1 行を出して終了コード 2（入っていない物は 1 物 1 行）。
- 記録 <置き場>/.works-toolset.json: {名: {version, source, sha256, loaded[, commit][, source_enabled]}}（見えるようにするだけ。
  run ごとの versions.json の borrowed に載る）。kind "plugin" の version は installed_plugins.json の行の version、source は
  入れた置き場、source_enabled は利用者の側の enabledPlugins の値（CLI の install が載せる。source_enabled を見よ）。superpowers
  の version・commit は pin の物、source は写しのフォルダで、source_enabled は載せない（利用者の側の有効・無効に依らない）。
- 写し（vendor）: 利用者のキャッシュの superpowers の 1 つの版（<利用者の設定の置き場>/plugins/cache/<marketplace>/superpowers/<版>。
  網からは取らない。版は人が名指す）から、包むファイル（.shared/core/spseam.py の wrapped_files。借りるスキルの全ファイル・
  部品 parts・LICENSE）だけを .shared/borrow/superpowers/<版>/ へバイトのまま・権限つきで写し、ほかの版の写しを消し、写しの台帳
  .shared/borrow/superpowers/COPIED_FROM と borrow.json の superpowers.pin（版・commit・確かめた日・ファイルごとの sha256）を
  書き直す。commit は installed_plugins.json の行のうち installPath がその版の置き場の行の gitCommitSha（無ければ写さずに止まる）。
  使用許諾のファイルが MIT License で borrow.json の licence と合う時だけ写す（外れなら何も書かずに止まる）。写しは直さない。
  写しを変えるのはこの口だけで、写し・台帳・pin を同じ 1 つの commit に入れる。
- 契約の確かめ（contract）: 版のフォルダに、固定との食い違い（spseam.pin_problems）と、包む節の表 .shared/borrow/seams.json の
  契約の破れ（spseam.contract_problems。錨・読み替えの決まり・穴・出口の語）を当てて 1 行ずつ出す。版を名指さなければ写しに、
  名指せば利用者のキャッシュのその版の置き場（vendor と同じ所。版を上げる前に、新しい版で何が崩れるかを見る）に当てる。
  破れが無ければ 1 行で終了コード 0、在れば 1、版のフォルダが無い・borrow.json に pin が無ければ 2。何も書かない。
- 開発の再開の確かめ（newer。dev/dogfood.sh が起動の時に 1 回呼ぶ）: 利用者のキャッシュの superpowers の版のフォルダ・
  installed_plugins.json の行の版・marketplace の一覧（plugins/known_marketplaces.json の installLocation の
  .claude-plugin/marketplace.json）の版を、写した固定の版と数の組（6.10.0 → (6, 10, 0)）で比べる。決まりは 1 つで、数で読めて
  固定より古い版だけを飛ばし、ほかの版のフォルダ（数で読めない版の名も）には固定との食い違い・節の契約の破れ・包むファイルに
  増えた人に聞く文（human partner を含む行）を出す（固定と同じ版で違いが無ければ黙る）。フォルダの無い版（一覧にだけ在る物
  など）は同じ決まりで 1 行を出す。入っていない・読めない JSON は 1 行で名指して続ける。版を上げるかは人が決める（上げるのは vendor）。網には出ず、何も書かず、終了コードは 0（使い方の誤りだけ 2）。
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
IGNORED_IN_SKILLS = spseam.IGNORED
MARKERS = spseam.MARKERS                    # Claude Code がプラグインのキャッシュの版の置き場に置く印（使っている pid・捨てた時刻）
PARTS_DIR = "works-parts"                   # 部品の置き場（<設定の置き場>/works-parts/<借りる物の名>/<相対パス>）
USER_CONFIG_DEFAULT = "~/.claude"
TMP_MARK = ".works-tmp."
USAGE = ("toolset.py: 使い方: python3 toolset.py install [--no-plugins] [--claude <claude の実行ファイル>] "
         "[--user-config <利用者の設定の置き場>] <設定の置き場>"
         " | python3 toolset.py guard <設定の置き場>"
         " | python3 toolset.py vendor [--user-config <利用者の設定の置き場>] <superpowers の版>"
         " | python3 toolset.py contract [--user-config <利用者の設定の置き場>] [<superpowers の版>]"
         " | python3 toolset.py newer [--user-config <利用者の設定の置き場>]"
         "（install は --no-plugins か --claude のどちらか 1 つ）")
VENDORED = "superpowers"                    # 写しを持つ借りる物（.shared/borrow/<この名>/<版>/）
LEDGER = "COPIED_FROM"                      # 写しの台帳の名（.shared/borrow/superpowers/ の下。形は .shared/core/copyledger.py）
LICENCE_HEADS = {"MIT": "MIT License"}      # borrow.json の licence → 使用許諾のファイルの頭の行（写してよい物だけ）
UPSTREAM = "github.com/obra/superpowers"    # 写し元の系統（台帳の 1 行目に書く）
OLD_MARK = ".works-old."                    # 入れ替えの間、前の版の写しと台帳を脇へ退ける名の印
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")    # 固定に書く写し元の commit（installed_plugins.json の gitCommitSha）
# 写しが pin と合わない時の直し方（写しは works の置き場の一部なので、works の置き場が壊れている）
VENDORED_FIX = ("  直す: works を入れ直す（claude plugin install works@raiki61）か、開発中なら git で写しを戻す"
                "（git checkout -- :/works/.shared/borrow）")
VERSION_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]*")   # 写す版の名（フォルダの名になる。/ や .. で外を指させない）
VERSION_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)*")   # newer が数の組で比べられる版の名（6.10.0 → (6, 10, 0)）
HUMAN_ASK = "human partner"                 # 原文の役が人に聞く文の印（小文字で比べる。newer が増えた行を名指す。読み替えで覆うかは人が決める）
NEWER_LAST = "版を上げるかは人が決める（上げる時は toolset.py vendor <版> で写しと pin を取り直し、同じ commit で試験を通す）"


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
    """(名 → 使う置き場（mcp は url）, 名 → 版)。kind "skills"（superpowers）は works の写し（spseam.vendored_dir）と pin の版で、
    利用者の入れた物は読まない。kind "plugin" は利用者が入れたプラグインからだけ取る。写しが pin と合わない・入っていない・works が
    名前で頼る物が無い借りる物は、借りる物ごとに理由と入れるコマンドを並べて 1 つの ToolsetError（何も写す前に呼ぶ）"""
    user_config = pathlib.Path(user_config)
    chosen, versions, bad = {}, {}, []
    plugins = _read_installed(user_config) if any(i["kind"] == "plugin" for i in borrow.values()) else {}
    for name, item in borrow.items():
        if item["kind"] == "mcp":
            chosen[name] = item["url"]
            versions[name] = item.get("version")
            continue
        if item["kind"] not in ("skills", "plugin"):
            raise ToolsetError(f"borrow.json の {name} の kind {item['kind']!r} を知らない（skills・plugin・mcp）")
        if item["kind"] == "skills":
            pinned = isinstance(item.get("pin"), dict) and bool(item["pin"].get("version"))
            if not pinned:
                src = spseam.BORROW_DIR / name
                problems = [f"borrow.json の {name} に pin が無い（写しを作るのは dev/toolset.py vendor <版>）"]
            else:
                src = spseam.vendored_dir(item)
                # 借りる一覧と部品が固定に在り、固定のファイルが手元に同じバイトで在ること（spseam.pin_problems の 1 つの決まり）
                problems = spseam.pin_problems(src, item) if src.is_dir() else [f"{src}: 写しのフォルダが無い"]
            if problems:
                bad.append(f"{name} の写し（{src}）が borrow.json の pin と合わない:\n"
                           + "\n".join(f"  - {ln}" for ln in problems) + "\n" + VENDORED_FIX)
                continue
            chosen[name] = src
            versions[name] = item["pin"]["version"]
            continue
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


def _sync_file(src: pathlib.Path, dest: pathlib.Path) -> bool:
    """1 本のファイル src を dest へ _sync と同じくバイトのまま・権限つきで写す（中身と実行の権限が同じなら何もしない）。一時の
    ファイルに写してから入れ替える。変えたら真"""
    if (dest.is_file() and not dest.is_symlink() and dest.read_bytes() == src.read_bytes()
            and os.access(dest, os.X_OK) == os.access(src, os.X_OK)):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}{TMP_MARK}{os.getpid()}"
    shutil.copy2(src, tmp)
    if dest.is_dir() and not dest.is_symlink():   # 同じ名のフォルダは os.replace で置き換えられない
        shutil.rmtree(dest)
    os.replace(tmp, dest)
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
    parents = [cfg / "skills", cfg / MP_DIR]
    if (cfg / PARTS_DIR).is_dir() and not (cfg / PARTS_DIR).is_symlink():   # 部品の一時のファイルは写す先の隣に在る
        parents += [pathlib.Path(here) for here, _, _ in os.walk(cfg / PARTS_DIR, followlinks=False)]
    for parent in parents:
        if not parent.is_dir():
            continue
        for p in parent.iterdir():
            if not (p.name.startswith(".") and TMP_MARK in p.name):
                continue
            pid = p.name.rsplit(".", 1)[-1]
            if pid.isdigit() and _alive(int(pid)):
                continue
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)


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
    out += _foreign_parts(cfg, borrow)
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


def _prune_parts(cfg: pathlib.Path, borrow: dict) -> None:
    """works-parts/<kind "skills" の名>/ の下の、parts の外の普通のファイルを消し、それで空になったフォルダも消す（版上げで部品が
    一覧から外れても柵に止まらない。works-parts/ は works だけが書き、Claude Code は読まない）。symlink・フォルダでない物・
    works-parts/ 直下の知らない名・一時のファイル（_clean_tmp が消す）は触らず、柵に任せる"""
    root = cfg / PARTS_DIR
    if root.is_symlink() or not root.is_dir():
        return
    for name, item in borrow.items():
        base = root / name
        if item["kind"] != "skills" or base.is_symlink() or not base.is_dir():
            continue
        keep = set(item.get("parts", []))
        for here, dirs, names in os.walk(base, topdown=False, followlinks=False):
            at = pathlib.Path(here)
            for n in names:
                p = at / n
                if (p.is_symlink() or not p.is_file() or TMP_MARK in n
                        or p.relative_to(base).as_posix() in keep):
                    continue
                p.unlink()
            for d in dirs:
                p = at / d
                if not p.is_symlink() and p.is_dir() and not any(p.iterdir()):
                    p.rmdir()
        if not any(base.iterdir()):
            base.rmdir()


def _foreign_parts(cfg: pathlib.Path, borrow: dict) -> list:
    """works-parts/ の下の、borrow.json の parts の外のファイル（と symlink）を works-parts/<相対パス> で（パスの順）。
    .DS_Store（IGNORED_IN_SKILLS）は数えない"""
    root = cfg / PARTS_DIR
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        return [f"{PARTS_DIR}（フォルダでない）"]
    if not root.is_dir():
        return []
    allowed = {f"{n}/{rel}" for n, i in borrow.items() if i["kind"] == "skills" for rel in i.get("parts", [])}
    out = []
    for here, dirs, names in os.walk(root, followlinks=False):
        for n in [*names, *(d for d in dirs if (pathlib.Path(here) / d).is_symlink())]:
            p = pathlib.Path(here) / n
            rel = p.relative_to(root).as_posix()
            if n in IGNORED_IN_SKILLS or (rel in allowed and not p.is_symlink()):
                continue
            out.append(f"{PARTS_DIR}/{rel}")
    return sorted(out)


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
    chosen は installed_sources を通った物だけを渡す（superpowers の写しを pin と照らし直さずに写す）。
    enabled は 名 → source_enabled の値（渡された kind "plugin" の名だけ記録に source_enabled として載せる）。
    返りと <置き場>/.works-toolset.json は {名: {version, source, sha256, loaded[, commit][, source_enabled]}}"""
    versions = versions or {}
    enabled_src = enabled or {}
    cfg = pathlib.Path(config_dir)
    _clean_tmp(cfg)
    _prune_parts(cfg, borrow)
    bad = guard(cfg, borrow)
    if bad:
        raise ToolsetError(_refusal(cfg, bad))
    mcp = _mcp_servers(chosen, borrow)
    rec = {}
    for name, item in borrow.items():
        if item["kind"] != "skills":
            continue
        src = pathlib.Path(chosen[name])
        # 写しが固定と合わなければ（借りる一覧・部品の欠けも）何も写す前に名指す（installed_sources と同じ spseam.pin_problems）
        lack = spseam.pin_problems(src, item)
        if lack:
            raise ToolsetError(f"{name} の写し（{src}）が borrow.json の pin と合わない: " + " / ".join(lack))
        trees = []
        for s in item["skills"]:
            d = src / "skills" / s
            _sync(d, cfg / "skills" / s)
            trees.append([s, _tree(d)])
        parts = {}
        for rel in item.get("parts", []):
            f = src / rel
            _sync_file(f, cfg / PARTS_DIR / name / rel)
            parts[rel] = (hashlib.sha256(f.read_bytes()).hexdigest(), os.access(f, os.X_OK))
        if parts:
            trees.append([PARTS_DIR, parts])
        pin = item.get("pin") or {}
        rec[name] = {"version": versions.get(name) or pin.get("version") or src.name, "source": str(src),
                     "sha256": _digest(trees), "loaded": True}
        if "commit" in pin:
            rec[name]["commit"] = pin["commit"]
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
        if borrow[name]["kind"] == "plugin":   # superpowers は写しから入れるので、利用者の側の有効・無効を載せない
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


def vendor(pack: pathlib.Path, src: pathlib.Path, version: str, commit: str, checked: str) -> dict:
    """利用者のキャッシュの superpowers の版のフォルダ src の包むファイル（spseam.wrapped_files）を
    pack/.shared/borrow/superpowers/<version>/ へバイトのまま・権限つきで写し、ほかの版のフォルダを消し、台帳 COPIED_FROM と
    borrow.json の superpowers.pin を書き直して、新しい pin を返す。commit が分からない（40 桁の 16 進でない。固定は写し元を
    名指す）・使用許諾が合わない・借りるスキルの SKILL.md か部品が無い・symlink か外を指すパスが在る・パスに空白か # が在る
    （台帳に書けない）、のどれかなら何も書かずに ToolsetError。

    入れ替えは、新しい版を一時の置き場に写し、台帳と borrow.json も一時のファイルに書いてから、前の版と台帳を脇へ退け、
    新しい物を置き、最後に borrow.json を os.replace で置く。途中で落ちたら脇へ退けた物を戻し、初めての写しなら
    superpowers/ も残さない。前の版を消すのは borrow.json を置いた後だけ"""
    pack, src = pathlib.Path(pack), pathlib.Path(src)
    _check_version_name(version)
    if not isinstance(commit, str) or not COMMIT_SHA.fullmatch(commit):
        raise ToolsetError(f"写し元の commit が分からない（{commit!r}。40 桁の 16 進が要る）。固定は写し元を名指すので写さない"
                           "（installed_plugins.json の行に gitCommitSha が在る版を入れ直す）")
    bj = pack / ".shared" / "borrow" / "borrow.json"
    borrow = json.loads(bj.read_text(encoding="utf-8"))
    item = borrow[VENDORED]
    if not src.is_dir():
        raise ToolsetError(f"{VENDORED} の版のフォルダ {src} が無い")
    notice = _licence_notice(src, item)
    files = spseam.wrapped_files(src, item)
    # 読まなかった物（symlink・外を指すパス）と、版のフォルダに無い借りる一覧・部品（pin.files に入らない）だけが残る
    bad = spseam.pin_problems(src, dict(item, pin={"files": files}))
    bad += [f"{r}: パスに空白か # が在る（台帳に書けない）" for r in files if any(c.isspace() or c == "#" for c in r)]
    if bad:
        raise ToolsetError(f"{src} を写せない: " + " / ".join(bad))
    head = (f"{commit}  {VENDORED} {version}（{UPSTREAM}。{LICENCE_HEADS[item['licence']]}・{notice}。"
            f"直さない写し。取り直しは dev/toolset.py vendor）")
    ledger = "\n".join([head, *(f"{version}/{rel}  {rel}" for rel in files)]) + "\n"
    base = pack / ".shared" / "borrow" / VENDORED
    pid = os.getpid()
    tmp = base / f".{version}{TMP_MARK}{pid}"
    led_tmp = base / f".{LEDGER}{TMP_MARK}{pid}"
    bj_tmp = bj.parent / f".{bj.name}{TMP_MARK}{pid}"
    created = not base.exists()
    moved, placed, led_placed = [], False, False   # 脇へ退けた (元の場所, 脇)・新しい版を置いたか・新しい台帳を置いたか
    try:
        base.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
        for rel in files:
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, tmp / rel)
        pin = spseam.pin_of(tmp, item, version, commit, checked)
        if pin["files"] != files:
            raise ToolsetError(f"写しの sha256 が元と違う（写している間に {src} が変わった？）。写さない")
        item["pin"] = pin
        led_tmp.write_text(ledger, encoding="utf-8")
        bj_tmp.write_text(json.dumps(borrow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for old in sorted(base.iterdir()):
            if old in (tmp, led_tmp):
                continue
            aside = base / f".{old.name}{OLD_MARK}{pid}"
            old.rename(aside)
            moved.append((old, aside))
        tmp.rename(base / version)
        placed = True
        os.replace(led_tmp, base / LEDGER)
        led_placed = True
        os.replace(bj_tmp, bj)       # ここで入れ替わる（この後は前の版を消すだけ）
    except BaseException:
        for t in (tmp, led_tmp, bj_tmp):
            if t.is_dir():
                shutil.rmtree(t, ignore_errors=True)
            elif t.exists():
                t.unlink()
        if placed:
            shutil.rmtree(base / version, ignore_errors=True)
        if led_placed:
            (base / LEDGER).unlink(missing_ok=True)
        for old, aside in moved:
            aside.rename(old)
        if created:
            shutil.rmtree(base, ignore_errors=True)
        raise
    for _, aside in moved:
        if aside.is_dir() and not aside.is_symlink():
            shutil.rmtree(aside, ignore_errors=True)
        else:
            aside.unlink(missing_ok=True)
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
          f"（commit {pin['commit']}）")
    return 0


def _contract_cli(pack: pathlib.Path, user_cfg: "pathlib.Path | None", version: "str | None") -> int:
    """版のフォルダ（version が無ければ写し、在れば利用者のキャッシュのその版）に固定と節の契約を当てて行を出す。
    破れが無ければ 0、在れば 1、版のフォルダが無い・borrow.json に pin が無ければ 2"""
    borrow_dir = pack / ".shared" / "borrow"
    item = load_borrow(pack)[VENDORED]
    pin = item.get("pin")
    if not pin:
        raise ToolsetError(f"borrow.json の {VENDORED} に pin が無い（写しの版が決まらない。dev/toolset.py vendor で写す）")
    if version is None:
        src, version = spseam.vendored_dir(item, borrow_dir), pin["version"]
    else:
        _check_version_name(version)
        src = (user_cfg or user_config_dir()) / "plugins" / "cache" / item["marketplace"] / VENDORED / version
    if not src.is_dir():
        print(f"toolset.py: {VENDORED} {version} の版のフォルダ {src} が無い", file=sys.stderr)
        return 2
    seams = spseam.load_seams(borrow_dir)
    overlay = (borrow_dir / spseam.OVERLAY_FILE).read_text(encoding="utf-8")
    bad = spseam.contract_problems(src, item, seams, overlay)   # 固定との食い違い（pin_problems）が先に並ぶ
    if not bad:
        print(f"契約: {VENDORED} {version}（{src}）の錨・穴・語・sha256 は全部そろう")
        return 0
    print(f"契約: {VENDORED} {version}（{src}）の破れ {len(bad)} 件（固定 {pin['version']} と "
          f"{spseam.SEAMS_FILE} に照らして）:")
    for line in bad:
        print(f"- {line}")
    return 1


def _version_key(version) -> "tuple | None":
    """版の名の数の組（"6.10.0" → (6, 10, 0)）。数で読めなければ None"""
    if not isinstance(version, str) or not VERSION_NUMBER.fullmatch(version):
        return None
    return tuple(int(x) for x in version.split("."))


def _local_versions(user_cfg: pathlib.Path, mp: str) -> tuple:
    """利用者の手元の superpowers の ({版の名: 版のフォルダ}, [フォルダの無い installed_plugins.json の行の版], [名指す行])。
    版のフォルダは <user_cfg>/plugins/cache/<mp>/superpowers/ の下のフォルダ（Claude Code の印と . で始まる名を除く）と、
    installed_plugins.json の superpowers の行（scope を問わない）の installPath"""
    folders, homeless, notes = {}, [], []
    base = user_cfg / "plugins" / "cache" / mp / VENDORED
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and d.name not in MARKERS:
                folders[d.name] = d
    try:
        plugins = _read_installed(user_cfg)
    except ToolsetError as e:   # 読めない installed_plugins.json は名指して、版のフォルダだけで続ける
        notes.append(f"installed_plugins.json を読めない（{e}）")
        plugins = {}
    for r in plugins.get(f"{VENDORED}@{mp}", []):
        v, at = r.get("version"), r.get("installPath")
        if not isinstance(v, str) or v in folders:
            continue
        if isinstance(at, str) and pathlib.Path(at).is_dir():
            folders[v] = pathlib.Path(at)
        elif v not in homeless:
            homeless.append(v)
    return folders, homeless, notes


def _marketplace_versions(user_cfg: pathlib.Path, mp: str) -> tuple:
    """marketplace の一覧に載る superpowers の ([版の名], [名指す行])。一覧は known_marketplaces.json の <mp>.installLocation の
    .claude-plugin/marketplace.json の plugins[] の name が superpowers の行の version"""
    km = user_cfg / "plugins" / "known_marketplaces.json"
    known = _read_json(km)
    if known is None:
        return [], [f"marketplace {mp} が登録されていない（{km} が無い）"]
    entry = known.get(mp) if known is not _BAD else None
    loc = entry.get("installLocation") if isinstance(entry, dict) else None
    if known is _BAD or (entry is not None and not isinstance(loc, str)):
        return [], [f"marketplace の一覧を読めない（{km}）"]
    if entry is None:
        return [], [f"marketplace {mp} が登録されていない（{km} に行が無い）"]
    p = pathlib.Path(loc) / ".claude-plugin" / "marketplace.json"
    doc = _read_json(p)
    rows = doc.get("plugins") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return [], [f"marketplace の一覧を読めない（{p}）"]
    return [r["version"] for r in rows if isinstance(r, dict) and r.get("name") == VENDORED
            and isinstance(r.get("version"), str)], []


def _new_asks(src: pathlib.Path, copy: pathlib.Path, item: dict) -> list:
    """版のフォルダ src の包むファイルの中の人に聞く文（HUMAN_ASK を含む行）のうち、写し copy の同じファイルに無い行
    （前後の空白を除いて比べる）の [(相対パス, 行)]"""
    out = []
    for rel in spseam.wrapped_files(src, item):
        new = (src / rel).read_text(encoding="utf-8", errors="replace").split("\n")
        old_p = copy / rel
        old = old_p.read_text(encoding="utf-8", errors="replace").split("\n") if old_p.is_file() else []
        have = {ln.strip() for ln in old}
        out += [(rel, ln.strip()) for ln in new if HUMAN_ASK in ln.lower() and ln.strip() not in have]   # 行頭の Human も拾う
    return out


def _newer_cli(pack: pathlib.Path, user_cfg: "pathlib.Path | None") -> int:
    """開発の再開の確かめ。手元と marketplace の一覧の superpowers の版を写した固定の版と比べて行を出す。何も書かず、網に
    出ず、読めない物は 1 行で名指して続け、いつも 0"""
    user_cfg = user_cfg or user_config_dir()
    borrow_dir = pack / ".shared" / "borrow"
    item = load_borrow(pack)[VENDORED]
    mp, pin = item["marketplace"], item.get("pin") or {}
    pin_v = pin.get("version")
    pin_key = _version_key(pin_v)
    if pin_key is None:
        print(f"borrow.json の {VENDORED} の pin の版 {pin_v!r} を数で読めない（比べる元が無い。dev/toolset.py vendor で写す）")
        print(NEWER_LAST)
        return 0
    copy = spseam.vendored_dir(item, borrow_dir)
    seams = spseam.load_seams(borrow_dir)
    overlay = (borrow_dir / spseam.OVERLAY_FILE).read_text(encoding="utf-8")
    folders, homeless, notes = _local_versions(user_cfg, mp)
    listed, mp_notes = _marketplace_versions(user_cfg, mp)
    for ln in notes + mp_notes:
        print(ln)
    if not folders and not homeless:
        print(f"{VENDORED} が入っていない（{user_cfg / 'plugins' / 'cache' / mp / VENDORED} に版のフォルダが無く、"
              f"installed_plugins.json に {VENDORED}@{mp} の行も無い）")
    # 決まりは 1 つ: 数で読めて固定より古い版だけを飛ばし、ほかは全部（数で読めない版の名も）pin と節の契約を当てる。
    # 固定と同じ版で、pin・契約・人に聞く文のどれにも違いが無い物だけは知らせることが無い
    def older(v):
        key = _version_key(v)
        return key is not None and key < pin_key

    found = False
    seen = set()   # 手元で当てた版（名と数の組の両方。一覧の同じ版を 2 度出さない）
    for v in sorted(folders, key=lambda n: (_version_key(n) is None, _version_key(n) or (), n)):
        d, key = folders[v], _version_key(v)
        seen |= {v, key} - {None}
        if older(v):
            continue
        try:
            pp = spseam.pin_problems(d, item)
            sp = spseam.seam_problems(d, item, seams, overlay)
            asks = _new_asks(d, copy, item)
        except (OSError, ValueError) as e:   # 版のフォルダの中が読めない（文字のコードが違うなど）
            found = True
            print(f"{VENDORED} {v}（{d}）の中を読めない（{e}）")
            continue
        if key == pin_key and not (pp or sp or asks):
            continue
        found = True
        if key is None:
            print(f"{VENDORED} {v}（{d}）: 版の名を数で読めない（数で比べず、写しと照らした）")
        elif key == pin_key:
            print(f"{VENDORED} {v}（{d}）: 写しと同じ版なのに中身が違う")
        else:
            print(f"{VENDORED} {v}（{d}）: 写した {pin_v} より新しい")
        for ln in pp:
            print(f"- {ln}")
        for ln in sp or ["錨・穴・語は全部そのまま在る"]:
            print(f"- 契約: {ln}")
        for rel, ln in asks:
            print(f"- 人に聞く文が増えた: {rel}: {ln}")
    # 手元にフォルダの無い版（installed_plugins.json の行・marketplace の一覧）は当てられないので、同じ決まりで名指すだけ
    for v, where in [*((v, "installed_plugins.json に在るが版のフォルダが無い") for v in homeless),
                     *((v, "marketplace の一覧に在る") for v in listed)]:
        key = _version_key(v)
        if older(v) or key == pin_key or v in seen or key in seen:
            continue
        found = True
        seen |= {v, key} - {None}
        how = "数で読めない版の名。" if key is None else ""
        tail = f"。入れるなら claude plugin update {VENDORED}@{mp}" if where.startswith("marketplace") else ""
        print(f"{VENDORED} {v}: {where}（{how}手元に無いので契約は当てていない{tail}）")
    if not found:
        print(f"{VENDORED}: 写した {pin_v} より新しい版・違う中身は、手元にも marketplace の一覧にも無い")
    print(NEWER_LAST)
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
    if not args or args[0] not in ("install", "guard", "vendor", "contract", "newer"):
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
        elif cmd in ("install", "vendor", "contract", "newer") and a == "--user-config" and rest:
            user_cfg = pathlib.Path(rest.pop(0))
        elif a.startswith("--"):
            print(USAGE, file=sys.stderr)
            return 2
        else:
            pos.append(a)
    if (len(pos) > 1 or (cmd not in ("contract", "newer") and not pos) or (cmd == "newer" and pos)
            or (cmd == "install" and no_plugins == bool(claude_bin))):
        print(USAGE, file=sys.stderr)
        return 2
    pack = pathlib.Path(__file__).resolve().parents[1]
    if cmd == "newer":
        try:
            return _newer_cli(pack, user_cfg)
        except (OSError, ValueError, ToolsetError) as e:   # 確かめは知らせるだけ。読めない物を名指して 0 で終わる
            print(f"superpowers の新しい版の確かめが途中で読めない物に当たった（{e}）")
            print(NEWER_LAST)
            return 0
    if cmd == "contract":
        try:
            return _contract_cli(pack, user_cfg, pos[0] if pos else None)
        except ToolsetError as e:
            print(f"toolset.py: {e}", file=sys.stderr)
            return 2
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
                       for n, i in borrow.items() if i["kind"] == "plugin"}
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
