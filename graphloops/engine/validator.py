"""graph が宣言する plugin の中の物（記録の検証器 scripts/<loop>-record.py・役割 agent の定義 agents/<役>.md）の探し方と、検証器の呼び方、報告前の仕上げ。"""
import glob
import json
import os
import pathlib
import re
import subprocess
import sys

from .intake import version_key
from .rules import hook
from .util import PLUGIN_ROOT, claude_config_dir, die

VALIDATOR_TIMEOUT = 600  # 秒

# engine が読む「受理集合」の鍵。**鍵の綴りを engine が持ち、graphcheck は import する**——
# 以前はチェックの側が鍵の名前を手で並べており、engine か rules が鍵を増やした周に、その鍵だけ
# 形（整数の空でない一覧）を誰も検査しないまま通った。ループ固有の鍵は rules が ACCEPT_KEYS で宣言する。
REPORT_ACCEPTS = "report_accepts_exit"
ENGINE_ACCEPT_KEYS = (REPORT_ACCEPTS,)


def report_accepts(b):
    """報告に進んでよい検証器の終了コード（正本は graph）。**読む側が 2 か所に散っていたので口を 1 つにする。**"""
    return b.graph.get("record", {}).get(REPORT_ACCEPTS, [0])


def env_root(plugin):
    """plugin の置き場を指す環境変数の名前（convergence-loops → CONVERGENCE_LOOPS_ROOT）。"""
    return plugin.upper().replace("-", "_") + "_ROOT"


def _sibling(plugin):
    """同じリポジトリに並ぶ plugin のルート（`<リポジトリ>/<plugin>/`。その plugin.json の name で確かめる）。並んでいなければ None。
    キャッシュの中では plugin ごとに `<marketplace>/<plugin>/<版>/` に置かれるので、隣には並ばない（キャッシュから探す）。"""
    root = PLUGIN_ROOT.parent / plugin
    p = root / ".claude-plugin" / "plugin.json"
    try:
        return root if json.loads(p.read_text(encoding="utf-8")).get("name") == plugin else None
    except OSError:
        return None  # 無い＝並んでいない
    except ValueError as e:
        # 壊れている≠無い。黙って None にすると同じリポジトリの検証器を飛ばしてキャッシュの別版を読む
        print(f"警告: {p} が読めない（{e}）——同梱の plugin として扱えず、キャッシュから探す", file=sys.stderr)
        return None


def find_plugin_path(rel, plugin, explicit=None, kind="file"):
    """plugin の中のファイルかディレクトリを順に探す: 明示 → <PLUGIN>_ROOT → 同じリポジトリに並ぶ plugin → インストール済みキャッシュの最新版。
    plugin が無ければ明示だけ。**先の候補で見つかれば後の候補は見ない**——キャッシュの曖昧さ（同名 plugin が複数の
    出所に在る）で落とすのはキャッシュを実際に引くときだけ。以前は明示や同梱が在っても先に die して、案内した
    --validator がその場で効かず、agents/<役>.md の経路には回避策自体が無かった（実測 2026-09-12: 2 出所を置くと
    実在する --validator を渡しても exit 2）。"""
    def ok(p):
        return p.is_file() if kind == "file" else p.is_dir()

    if explicit:
        if ok(pathlib.Path(explicit)):
            return str(pathlib.Path(explicit).resolve())
        # 明示は「これを使え」であって候補の 1 つではない——無ければ黙って別の物に倒さない
        # （実測 2026-09-12: --validator /nonexistent/x.py でも init は exit 0 で同梱の検証器に倒れ、警告も出なかった）
        die(f"明示された {explicit} が無い（{kind}）——パスを確かめよ。明示を外せば同梱・キャッシュから探す")
    if not plugin:
        return None
    env = os.environ.get(env_root(plugin))
    if env and ok(pathlib.Path(env) / rel):
        return str((pathlib.Path(env) / rel).resolve())
    sib = _sibling(plugin)
    if sib and ok(sib / rel):
        return str((sib / rel).resolve())
    # キャッシュは**実行中のプロファイル 1 つ**だけ見る（CLAUDE_CONFIG_DIR、既定は ~/.claude）。
    # 以前は ~/.claude* を横断していたので、別プロファイル・別マーケットプレイスの同名プラグインが
    # 版の大小だけで選ばれ、動いている出所と無関係なコードが importlib でこのプロセスに読み込まれた。
    cfg = pathlib.Path(claude_config_dir())
    hits = glob.glob(str(cfg / "plugins" / "cache" / "*" / plugin / "*" / rel))
    depth = len(pathlib.Path(rel).parts)

    hits.sort(key=lambda p: version_key(pathlib.Path(p).parents[depth - 1].name), reverse=True)
    # 出所（マーケットプレイス）が複数に跨がったら選ばない——明示を求める
    origins = {pathlib.Path(h).parents[depth].parent.name for h in hits}
    if len(origins) > 1:
        die(f"{plugin} の {rel} が複数の出所に在る（{sorted(origins)}）——どれを使うか明示しろ"
            f"（検証器は --validator。役の定義は同じリポジトリに並べるか {env_root(plugin)} で指す）")
    for h in hits:
        if ok(pathlib.Path(h)):
            return str(pathlib.Path(h).resolve())
    return None


def find_validator(loop, plugin, explicit=None):
    """検証器の名前は <loop>-record.py で、loop 名の末尾の -loop は付かない（research-loop → research-record.py）。"""
    loop = loop[:-5] if loop.endswith("-loop") else loop
    return find_plugin_path(f"scripts/{loop}-record.py", plugin, explicit=explicit)


def agent_def(agent_type):
    """役割 agent の定義（<plugin>:<役> の agents/<役>.md）を読む——ツール・モデル・effort と本文（役の指示）。

    None = 定義が見つからない（接頭の無い組み込み agent を含む）。tools の行が無い定義は全部を継承する（[] はツールなし）。
    本文が要るのは、役を別プロセスの CLI で起動するときに system prompt として渡すため（advance.launch_spec。ツールゼロの役もツールつきの役も）。
    """
    plugin, _, role = agent_type.rpartition(":")
    if not plugin:
        return None
    f = find_plugin_path(f"agents/{role}.md", plugin)
    if not f:
        return None
    try:
        fm, body = frontmatter(pathlib.Path(f).read_text(encoding="utf-8"))
    except ValueError as e:
        # 読めない形を読み飛ばすと、役が黙ってツール無し・既定のモデルで起動する（標準の決まり 4・5）
        die(f"{f}: 役の定義の frontmatter が読めない（{e}）")

    def scalar(name):
        v = fm.get(name)
        if isinstance(v, list):
            die(f"{f}: frontmatter の {name} は 1 つの値で書け（リストを受け取った: {v}）")
        return v or None

    tools = fm.get("tools")
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",") if t.strip()]   # Claude Code の書き方「tools: Read, Grep」
    return {
        "file": str(f),
        "tools": ["*"] if tools is None else tools,
        "model": scalar("model"),
        "effort": scalar("effort"),
        "body": body,
    }


_FM_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]+(.*))?$")


def _fm_scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def frontmatter(text):
    """役の定義（agents/<役>.md）の YAML frontmatter を (フィールドの辞書, 本文) に読む。標準ライブラリに YAML が無いので、
    役の定義が使う形だけをここ 1 か所で読み（標準 docs/standards/machine-readable-values.md の決まり 5）、知らない形は ValueError で止める。

    読む形: 頭の行の `key: 値`（引用符は外す）・`key: [a, b]`（流れの形のリスト）・`key:` の次の行から続く `  - a`（ブロックの形の
    リスト）・`key: |` か `key: >` の次の字下げした行（ブロックの文字列）・`#` で始まる注記の行と空行。区切りは 1 行目と、次の `---`
    だけの行。frontmatter の無い定義は ({}, 本文)。
    """
    text = text.removeprefix("\ufeff")   # BOM 付きで保存した定義を「frontmatter 無し」（ツール全部）と読まない
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("閉じる --- の行が無い")
    fm, key, block = {}, None, None

    def close_block():
        fm[key] = ("\n" if block == "|" else " ").join(fm[key]).strip()

    for n, raw in enumerate(lines[1:end], start=2):
        line = raw.rstrip()
        if block is not None:
            if not line or line[0] in " \t":
                fm[key].append(line.strip())
                continue
            close_block()
            block = None
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            item = line.strip()
            if key is None or not isinstance(fm.get(key), list) or not (item == "-" or item.startswith("- ")):
                raise ValueError(f"{n} 行目の字下げした行を読めない: {item!r}（読めるのはブロックの形のリストの「- 値」だけ）")
            fm[key].append(_fm_scalar(item[1:]))
            continue
        m = _FM_KEY.match(line)
        if not m:
            raise ValueError(f"{n} 行目を「key: 値」として読めない: {line!r}")
        key, v = m.group(1), (m.group(2) or "").strip()
        if key in fm:
            raise ValueError(f"{n} 行目: {key} が 2 度ある")
        if not v:
            fm[key] = []                # 次の行から「- 値」が続く（続かなければ空のリスト）
        elif v in ("|", ">", "|-", ">-"):
            fm[key], block = [], v[0]
        elif v.startswith("["):
            if not v.endswith("]"):
                raise ValueError(f"{n} 行目: {key} のリストが同じ行で閉じていない: {v!r}")
            fm[key] = [_fm_scalar(x) for x in v[1:-1].split(",") if x.strip()]
        elif v[0] in "{&*!|>":
            raise ValueError(f"{n} 行目: {key} の値の形を読めない: {v!r}（読めるのは文字列・リスト・ブロックの文字列）")
        else:
            fm[key] = _fm_scalar(v)
    if block is not None:
        close_block()
    return fm, "\n".join(lines[end + 1:]).strip()


def agent_tools(agent_type):
    d = agent_def(agent_type)
    return None if d is None else d["tools"]


def deliver_mode(agent_type, path_tools, tools=None, paste_roles=()):
    """プロンプトの渡し方: 役が path_tools（graph の deliver.path_tools——自分でファイルを読めるツール）のどれかを持てば path、
    持たなければ paste。定義が見つからなければ paste（安全側——貼れば必ず届く）。tools を渡せば定義を読み直さない。
    paste_roles（graph の deliver.paste_roles）の役はツールに依らず paste——ファイルの中の指示に従えという 1 文を拒む役が在る"""
    if agent_type in paste_roles:
        return "paste"
    if tools is None:
        tools = agent_tools(agent_type)
    if tools is None or not path_tools:
        return "paste"
    return "path" if ("*" in tools or any(t in tools for t in path_tools)) else "paste"


def run_validator(b, target=None):
    """検証器を回す。target を省くと graph の record.validator_arg（file か dir）に従う。
    graph の record.validator_output が "json" なら検証器に --json を渡し、標準出力の JSON（exit・stop・text）の stop を返りの stop に入れる
    ——rules は分岐を stop のキーで読み、人向けの文（out）を読まない。JSON として読めない・exit が終了コードと食い違うときは
    exit を None（検査が成立しなかった）にする"""
    v = b.state.get("validator")
    if not v:
        return {"exit": None, "out": "検証器が見つからない（init --validator で渡すか、graph の plugin の置き場を " + (env_root(b.plugin) if b.plugin else "<PLUGIN>_ROOT") + " で指す）"}
    if target is None:
        arg = b.graph.get("record", {}).get("validator_arg", "file")
        target = b.dir / ("rounds" if arg == "dir" else "record.json")
    as_json = b.graph.get("record", {}).get("validator_output") == "json"
    try:
        r = subprocess.run([sys.executable, v, *(["--json"] if as_json else []), str(target)], capture_output=True, text=True,
                           encoding="utf-8", timeout=VALIDATOR_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"exit": None, "out": f"検証器が {VALIDATOR_TIMEOUT} 秒で終わらない（{v}）", "validator": v}
    if not as_json:
        return {"exit": r.returncode, "out": (r.stdout + r.stderr).strip(), "validator": v}
    try:
        res = json.loads(r.stdout)
    except ValueError as e:
        return {"exit": None, "out": f"検証器の --json の出力が JSON でない（{e}。convergence-loops の版が古く --json を知らないかもしれない——0.50.0 以上が要る）: {(r.stdout + r.stderr).strip()[-1500:]}", "validator": v}
    if not isinstance(res, dict) or res.get("exit") != r.returncode or not isinstance(res.get("text"), str):
        return {"exit": None, "out": f"検証器の --json の出力の形が違う（exit・text が要り、exit は終了コード {r.returncode} と同じ）: "
                                     f"{r.stdout.strip()[-1500:]}", "validator": v}
    return {"exit": r.returncode, "out": (res["text"] + r.stderr).strip(), "stop": res.get("stop"), "validator": v}


# **engine が積む痕跡のフィールドは、名前を 1 か所で持つ。** （記録のフィールド → state の鍵）。
# 以前は finalize が 1 行ずつ写しており、**読む側（人に見せる口）が 1 つも無かった**——鳴っても
# 何も起きないフィールドが 5 つ在った（実測 2026-09-14: 検証器 4 本とも process を 1 度も参照していない）。
# 名前をここ 1 つに寄せたので、写す側（finalize）と見せる側（cmd_finalize）が同じ表を引く。
TRACES = (
    # once で凍った出力が今の schema に合わないノード。**これを読む cond・述語は永久に偽**なので、
    # 記録にも報告にも出さないと「走らなかった」が「走らせる条件に当たらなかった」に見える
    ("stale_frozen", "stale_frozen"),
    # 周をまたいで育った穴。切られていないので truncated_inputs には出ない
    ("growing_prompts", "growing_prompts"),
    # 役がフィールドを省いたので起きなかった write。**起きなかったことは、起きたことと同じだけ記録に要る**
    ("writes_skipped", "writes_skipped"),
    ("truncated_inputs", "truncated"),
    ("git_mismatches", "git_mismatches"),
    ("thickness_changes", "thickness_changes"),
    ("patches", "patches"),
    # 周の数で止めた run を続けた痕跡（loop.py resume）。続けると state.halted が外れ、記録の halted からは消えるので、ここに残す
    ("resumes", "resumes"),
    ("graph_changes", "graph_changes"),
    ("role_def_missing", "role_def_missing"),  # 別 plugin の役で、定義がこの環境に無かったもの
    # 盤面の loop が graph の state_schema から外れた（Board.save が積む。止めないので、見せる口はここだけ）
    ("loop_drift", "loop_drift"),
    # 履歴から作る値（hist）が graph の hist_schema から外れた・作れなかった（Board.save が控えを書くときに積む）
    ("hist_drift", "hist_drift"),
)


def traces(rec):
    """記録に残った痕跡のうち、非空のものだけ（フィールド名 → 件数）。**人に見せる口はここ 1 つ。**"""
    proc = rec.get("process")
    if not isinstance(proc, dict):
        return {}
    # rules が積むフィールド（loop 固有）もここに並べる——engine の TRACES に足すと、そのフィールドを持たない
    # loop の記録にまで空のフィールドが生える。写すのは rules の finalize、見せる口はここ 1 つ
    names = [f for f, _ in TRACES] + ["skipped", "stopped_nodes", "launch_missing", "unevaluable", "context_lost",
                                      "read_through_unchecked"]
    return {f: len(proc[f]) for f in names if isinstance(proc.get(f), list) and proc[f]}


def finalize(b):
    """報告の前の仕上げ。ループ固有の仕上げは rules の finalize、engine は痕跡の一覧を process に写す。"""
    fn = hook(b.rules, "finalize")
    if fn:
        fn(b)
    proc = b.record.setdefault("process", {})
    if isinstance(proc, dict):
        proc["skipped"] = [{"node": k, "reason": v} for r in b.state["rounds"] for k, v in r["skipped"].items()]
        # 人が止めて走らせなかったノード（loop.py stop）。省いた機構（skipped）と混ぜない
        proc["stopped_nodes"] = [{"node": k, "round": r["round"], "reason": v} for r in b.state["rounds"] for k, v in (r.get("stopped") or {}).items()]
        for field, key in TRACES:
            proc[field] = b.state.get(key, [])
        # 起動できなかった遮断系（launch.missing）は state の instance にしか無く、記録にも報告にも出ていなかった
        proc["launch_missing"] = [{"instance": i["id"], "round": r["round"], "missing": i["launch"]["missing"]}
                                  for r in b.state["rounds"] for i in r["instances"].values() if (i.get("launch") or {}).get("missing")]
