#!/usr/bin/env python3
"""destgate — 投稿の宛先を許可一覧で縛るゲート(PreToolUse:Bash)。

coldread(通じやすさ)とは別の軸「その宛先へ出してよいか」を検査する。
許可一覧が無ければ眠っている(何も出さず allow)。一覧の管理は人の仕事で、
モデルが自分で追記して通すのはゲートの無効化になる——deny 文言でも明示する。

coldread と別フックにしてあるのは、通じやすさの検査の倒れ方(読み役の故障・続けて止まる往復)に
宛先の検査を巻き込まないため(前は coldread に逃げ道 COLDREAD_SKIP=1 が在り、それで宛先の検査まで
外れる経路を作らないためでもあった)。宛先の判定は決定的(LLM なし)なので、
このゲート自身には逃げ道が無い——通したければ人が一覧へ追記する。それが記録になる。
解析部(トークン化・単純コマンド分割・旗表)は coldread-gate.py から読み込んで共有する。
"""
import fnmatch
import functools
import json
import os
import re
import sys
import time

# `sys.path[0]` に頼らない(coldread-gate.py が claude_auth を読むのと同じ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_auth  # noqa: E402
import gate_shell  # noqa: E402

# 解析部の coldread-gate.py は、許可一覧が在るときだけ読む(眠っている既定の形では、Bash のたびに読まない)
cr = None

CONFIG_DIR = claude_auth.config_dir(os.environ)   # 隣の coldread-gate と同じ置き場（決め方の正本は共通の claude_auth）
ALLOWLIST = os.path.join(CONFIG_DIR, "destgate", "allowlist")
DENY_LOG = os.path.join(CONFIG_DIR, "destgate", "denies.log")
# gh に宛先を引かせる時間の合計。hooks.json の destgate の timeout(30 秒)より短くする: フックが時間切れで終わると
# Claude Code は止めずに通すので、引き切れないときはこのゲートが自分で止める(宛先不明)
GH_BUDGET = 20
_DEADLINE = None   # coldread-gate.py を読んだ時から GH_BUDGET 秒
# どのサブコマンドでも値に本文・題を取ると見る旗(その値は宛先でない)。ほかの本文の旗は coldread の表(text_value)
TEXT_FLAGS = {"-b", "--body", "-t", "--title", "--subject"}
# 投稿先を指す issue・PR・discussion の URL(gh はこれを位置引数に受ける)。gh は綴りの大文字の scheme(HTTPS://)も受けるので
# scheme だけは大小を問わない(パスの issues・pull は gh も小文字しか受けないので、大文字を宛先と読まない)
ITEM_URL_RE = re.compile(r"(?i:https?)://[^/\s]+/(?P<o>[^/\s]+)/(?P<r>[^/\s]+)/(?:issues|pull|discussions)/\d+")
# 位置引数に issue・PR の URL を受け、その repo へ投稿するサブコマンドの頭の語
URL_SELECTOR_SUBS = {"issue", "pr", "discussion"}
# gh が -R の無い投稿の宛先を決めるのに読む環境変数(GH_REPO。https://cli.github.com/manual/gh_help_environment)と、
# gh が宛先を引く git の repo と remote を差し替える git の環境変数(GIT_DIR など。https://git-scm.com/docs/git#_environment_variables)
DEST_ENV_RE = re.compile(r"GH_REPO|GIT_DIR|GIT_WORK_TREE|GIT_COMMON_DIR|GIT_CONFIG\w*")
# 位置引数に issue・PR を受けるサブコマンドの、値を取らない旗(gh 2.102.0 の `gh <サブコマンド> --help` の FLAGS と
# https://cli.github.com/manual/ の各ページ)。同じ短い旗がサブコマンドで意味を変える(pr merge の -r は rebase で値を取らず、
# pr close の -c は本文の値を取る)ので、サブコマンドごとに引く。表に無い旗は今までどおり値を取ると見る(後の URL を投稿先と
# 読まず、URL の repo と走る場所の repo の両方を宛先と見る側に倒す)
_COMMENT_SWITCHES = {"--create-if-none", "--delete-last", "--edit-last", "-e", "--editor", "-w", "--web", "--yes"}
SWITCH_FLAGS = {
    ("pr", "merge"): {"--admin", "--auto", "-d", "--delete-branch", "--disable-auto",
                      "-m", "--merge", "-r", "--rebase", "-s", "--squash"},
    ("pr", "review"): {"-a", "--approve", "-c", "--comment", "-r", "--request-changes"},
    ("pr", "comment"): _COMMENT_SWITCHES,
    ("issue", "comment"): _COMMENT_SWITCHES,
    ("pr", "close"): {"-d", "--delete-branch"},
    ("pr", "edit"): {"--remove-milestone"},
    ("issue", "edit"): {"--remove-milestone", "--remove-parent", "--remove-type"},
}
# gh api のパスの中の、gh が走る場所の repo(GH_REPO が在ればそれ)で埋める印(https://cli.github.com/manual/gh_api。
# gh は古い書き方の :owner・:repo も埋める)
API_OWNER_RE = re.compile(r"\{owner\}|:owner\b")
API_REPO_RE = re.compile(r"\{repo\}|:repo\b")
# -R の無い投稿の宛先を gh が引く repo と remote を、同じコマンドの中で替えうるコマンド(gh repo set-default・remote の
# 追加と書き換え・clone・init など)。gh repo view を引くのはコマンドが走る前なので、引いた repo が投稿の宛先と違いうる
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
GIT_RETARGET_SUBS = {"init", "clone"}
GIT_REMOTE_READS = {"get-url", "show"}
GH_RETARGET_SUBS = {("repo", "set-default"), ("repo", "clone"), ("repo", "fork"), ("repo", "create"), ("repo", "rename")}


def patterns():
    """許可一覧(1 行 1 パターン。owner/repo・owner/*・gist。# 始まりと空行は無視)。"""
    try:
        with open(ALLOWLIST, encoding="utf-8") as f:
            return [ln.strip() for ln in f
                    if ln.strip() and not ln.strip().startswith("#")]
    except OSError:
        return []


def owner_repo(value):
    r"""-R の値から owner/repo を取り出す。取れなければ None。

    gh の -R は OWNER/REPO・HOST/OWNER/REPO・完全 URL(https/ssh)のどれも受けるので、
    末尾 2 セグメントを取り .git を落とす。ssh の別名ホスト(github.com-xxx:o/r)も
    : 以降がパスなので同じ規則で拾える。

    読むのは利用者が打った -R の値だけ。-R の無い投稿の宛先は git の remote の URL を読まず gh に解かせる(current_repo)。
    `\` を `/` に替えるのは、Windows で打った URL の綴りを受けるため。
    """
    v = value.strip().replace("\\", "/").rstrip("/")
    v = re.sub(r"^[a-z+]+://", "", v)
    v = v.split(":", 1)[-1] if ":" in v and "/" not in v.split(":", 1)[0] else v
    parts = [p for p in v.split("/") if p]
    if len(parts) < 2:
        return None
    o, r = parts[-2], parts[-1]
    r = re.sub(r"\.git$", "", r)
    if not o or not r or o.startswith("-"):
        return None
    return f"{o}/{r}"


@functools.lru_cache(maxsize=None)
def current_repo(cwd):
    """-R の無い投稿の宛先。gh 自身に解かせて owner/repo を返す。解けなければ None(宛先不明で止める)。

    origin を読まない: gh は -R の無いとき、gh repo set-default で決めた repo か、remote の中から選んだ repo へ投稿する
    (origin とは限らない。https://cli.github.com/manual/gh_repo_set-default)。投稿と同じ解き方の
    `gh repo view --json nameWithOwner` で引く(機械向けの形。docs/standards/machine-readable-values.md の決まり 2)。
    cwd ごとに 1 回だけ引き(1 本のコマンドの中の、-R の無い gh を同じ cwd で何度も引かない)、引く時間の合計は GH_BUDGET で縛る。"""
    if not os.path.isdir(cwd):
        # まだ無い場所(`git clone … /tmp/p && cd /tmp/p && gh …`)。cr.Screen は無い場所をフックの場所に替えて引くので、
        # 引かずに宛先不明にする(前はフックの場所の repo を宛先と取り違えて通していた)
        cr.log_line(DENY_LOG, "gh が走る場所が無い: %s" % cwd[:150])
        return None
    try:
        # gh の呼び方(差し替えの口 COLDREAD_GH_CMD・時間の上限)は coldread の画面の取得と同じ 1 本
        screen = cr.Screen(cwd)
        screen.deadline = min(screen.deadline, _DEADLINE)
        got = screen.json(["repo", "view", "--json", "nameWithOwner"])
        name = got.get("nameWithOwner") if isinstance(got, dict) else None
    except Exception as exc:   # 起動できない・gh が失敗した・JSON でない: 宛先不明として止める(呼び元)
        cr.log_line(DENY_LOG, "gh repo view で宛先を引けない: %s" % str(exc)[:150].replace("\n", " "))
        return None
    if not isinstance(name, str) or name.count("/") != 1:
        cr.log_line(DENY_LOG, "gh repo view の nameWithOwner が owner/repo でない: %r" % (name,))
        return None
    return name


def text_value(args, i, sub):
    """args[i] が、本文・題を値に取る旗の値か(その値は宛先でない)。

    本文の旗の表は coldread と同じ物を引く(長い旗はどのサブコマンドでも本文。短縮形は本文を意味するサブコマンドでだけ)。
    前は -b・--body・-t・--title しか見ず、`gh issue close 5 -c "https://…/pull/9 で直した"` の本文の頭の URL を宛先と読み、
    走る場所の repo へ出す投稿を、URL の repo(許可一覧の repo)と取り違えて通していた。"""
    if not i:
        return False
    prev = args[i - 1]
    if prev in TEXT_FLAGS:
        return True
    if prev in cr.LONG_TEXT_FLAGS:
        return (prev, sub) not in cr.LONG_FLAG_NOT_BODY
    if prev in cr.SHORT_TEXT_FLAGS:
        return sub in cr.SHORT_TEXT_FLAGS[prev][1]
    # 新しく作る PR・issue は、値を取る旗の表(coldread の CREATE_VALUE_FLAGS)がある。-R の値は宛先なので除く
    return sub in cr.NEW_ITEM_SUBS and prev in ({*cr.CREATE_VALUE_FLAGS, *cr.CREATE_VALUE_FLAGS.values()} - {"-R", "--repo"})


def selector_of(args, sub):
    """サブコマンドの後の最初の位置引数(投稿先の issue・PR を選ぶ語)。無ければ None。

    読み方は coldread の positional_after と同じで、違うのは、サブコマンドごとの値を取らない旗(SWITCH_FLAGS)の後の語を
    旗の値と見ないこと。前は全部の旗を値を取ると見て、`gh pr merge --squash <URL>` の URL を旗の値と読み、URL の repo に加えて
    走る場所の repo も宛先と見て止めていた。"""
    switches = SWITCH_FLAGS.get(tuple(sub[:2]), set())
    i, seen, after_flag = 0, 0, False
    while i < len(args):
        tok = args[i]
        width = cr.global_flag_width(tok)
        if width:
            i += width
            continue
        if seen < len(sub):
            seen += 1
            i += 1
            continue
        if tok.startswith("-") and tok != "-":
            after_flag = "=" not in tok and tok not in switches   # --旗=値 は値込みなので次の語は位置引数
        elif after_flag:
            after_flag = False  # 直前の旗の値
        elif not tok.startswith("__HEREDOC"):
            return tok
        i += 1
    return None


def retargets(args):
    """単純コマンド 1 件(語の列)が、-R の無い gh が宛先に選ぶ repo を替えうるか(GIT_RETARGET_SUBS・GH_RETARGET_SUBS など)。"""
    i = cr.command_start(args)
    name = os.path.basename(args[i]) if i < len(args) else ""
    rest = args[i + 1:]
    if name == "gh":
        sub = cr.subcommand(rest)
        if sub is None:
            return False   # サブコマンドを読めない gh は、投稿なら dest_of が宛先不明にする
        # `gh repo set-default --view`(-v)は今の設定を出すだけ
        return tuple(sub) in GH_RETARGET_SUBS and not (sub == ("repo", "set-default") and {"-v", "--view"} & set(rest))
    if name != "git":
        return False
    j = 0
    while j < len(rest) and rest[j].startswith("-"):
        j += 2 if rest[j] in GIT_VALUE_OPTS else 1
    if j >= len(rest):
        return False
    sub, more = rest[j], rest[j + 1:]
    if sub in GIT_RETARGET_SUBS:
        return True
    if sub == "remote":
        # 一覧を出すだけの形(`git remote`・`git remote -v`・get-url・show)は替えない
        words = [t for t in more if t not in ("-v", "--verbose")]
        return bool(words) and words[0] not in GIT_REMOTE_READS
    if sub == "config":
        # remote.<名>.url・remote.<名>.gh-resolved(gh repo set-default の印)を書く形
        return any(t.lower().startswith("remote.") for t in more)
    return False


def fed_dest(args, sub):
    """xargs・parallel・find -exec が足す語・差し込む語(coldread の gh_calls が置く FED_MARK・FED_WORD)が、宛先を変えうるか。

    足す語(FED_MARK)は何語になるか分からず、-R にもなりうるので、在れば変えうる。差し込む語(FED_WORD)が変えないのは、本文・題の
    値の中と、gh api のパスの owner/repo より後ろ(`repos/o/r/pulls/{}/comments` の番号)だけ。投稿先を選ぶ語・-R の値・旗の位置・
    パスの host と owner/repo に在れば、標準入力の語(URL・`-R 外/repo`)が宛先を決めうる。前は `… | xargs -I{} gh pr comment {}
    --body-file b.md` の差し込む語を URL でない番号と読み、走る場所の repo を宛先にして通していた(coldread の destination と同じ見方)。"""
    if any(cr.FED_MARK in t for t in args):
        return True
    endpoint = None
    if sub and sub[0] == "api" and len(sub) > 1:
        endpoint = next((i for i, t in enumerate(args) if t == sub[1]), None)
        lead = re.match(r"^(?:[A-Za-z+]+://[^/]*)?/*(?:[^/]+/+){0,2}[^/]*", sub[1]).group(0)
        if cr.FED_WORD in lead:
            return True
    return any(cr.FED_WORD in t for i, t in enumerate(args) if i != endpoint and not text_value(args, i, sub))


def api_input_post(args, sub):
    """gh api の --input(ファイルか -)が、coldread の読みで本文が見つからなくても投稿になりうるか。

    coldread は --input の JSON の .body と comments[].body だけを読み、ほかの所の短い文字列(200 字未満)は本文と見ない。
    そのため graphql の `{"query":"mutation{addComment(input:{…,body:\"短い本文\"}){…}}"}` と gist の
    `{"files":{"a.md":{"content":"短い中身"}}}` は投稿と見られない。宛先がこの 2 つになりうるとき(パスが graphql・gist か、
    xargs・find -exec が宛先のパスに語を差し込む・足すとき)は投稿と見る。前は投稿でないと見て素通しにし、許可一覧が在っても、
    `gh api graphql --input q.json` で一覧の外へコメントを出せていた(`-f query='mutation{…}'` の形は宛先不明で止めていた)。"""
    if not (sub and sub[0] == "api" and len(sub) > 1):
        return False
    head = args[:args.index("--")] if "--" in args else args
    if not any(t == "--input" or t.startswith("--input=") for t in head):
        return False
    return (cr.api_is_graphql(sub[1]) or cr.api_is_gist(sub[1])
            or cr.FED_WORD in re.split(r"[?#]", sub[1], maxsplit=1)[0] or any(cr.FED_MARK in t for t in args))


def dest_of(args, sub, cwd, here_unknown=False):
    """gh 引数列から投稿の宛先になりうる repo の集まりを返す。分からなければ None。

    呼び元は、集まりの全部が許可一覧に在るときだけ通す。cwd はその gh が走る場所(前の `cd <絶対パス> &&` を読んだもの。
    決まらなければ None)。here_unknown は、gh が -R の無い投稿の宛先を引く環境変数(GH_REPO・GIT_DIR など。DEST_ENV_RE)を
    コマンドが書いているか殻の環境に在るか、同じコマンドの中に宛先の repo を替えうるコマンド(retargets)が在る。"""
    if fed_dest(args, sub):
        return None
    # -R / --repo が最優先(gh 自身の解決順もこれが勝つ)。旗の読み方は coldread と同じ 1 本(cr.flag_value)。
    # 何度も書けば gh は最後の値を使うので、全部を読み、食い違えば宛先不明にする(前は最初の値だけを見ていて、
    # `-R 許可した/repo -R 外/repo` を許可一覧の repo と取り違えて通していた)
    repos = {owner_repo(v) for i, tok in enumerate(args) if tok.startswith(("-R", "--repo"))
             for v in [cr.flag_value(args[i:i + 2], "-R", "--repo")] if v is not None}
    # 本文・題の値が -R で始まる(`--title -Ro/r`・`-c -Ro/r`)なら、gh はそれを -R と読まない。どちらか決めずに宛先不明にする
    if any(tok.startswith(("-R", "--repo")) and text_value(args, i, sub) for i, tok in enumerate(args)):
        return None
    # 投稿先の issue・PR を URL で書けば、gh は -R でも走る場所でもなく URL の repo へ投稿する
    # (`gh pr comment https://github.com/o/r/pull/3`。前は走る場所の repo を宛先と取り違えて通していた)。本文・題の値の URL は宛先でない
    urls = {f"{m['o']}/{m['r']}" for i, tok in enumerate(args) if not text_value(args, i, sub)
            for m in [ITEM_URL_RE.match(tok)] if m}
    explicit = repos | urls
    if None in explicit or len(explicit) > 1:
        return None
    if sub and sub[0] == "api":
        if len(sub) < 2:
            return None
        # GraphQL(`graphql`・`/graphql`・`https://api.github.com/graphql`)は宛先の repo をパスに持たない。パスの . と ..
        # (`repos/許可した/repo/../../外/repo/…`)は、送る先で畳まれると別の repo を指しうるので、宛先と読まない
        if cr.api_is_graphql(sub[1]) or cr.api_endpoint_path(sub[1])[1]:
            return None
        if cr.api_is_gist(sub[1]):
            # gist の作成・書き換え(`gists`・`gists/<id>`。GitHub Enterprise Server の `api/v3/gists` も)の宛先は、gh gist create と
            # 同じ gist。前は repos/・orgs/ でないパスと見て宛先不明にし、一覧に gist が在っても -R の明示を求めて止めていた
            return {"gist"} | explicit
        path = re.sub(r"^[a-z+]+://[^/]+", "", sub[1]).lstrip("/")
        if API_OWNER_RE.search(path) or API_REPO_RE.search(path):
            # `repos/{owner}/{repo}/…` の印は、gh が -R の無い投稿と同じ repo で埋める。同じ解き方で引いて埋める
            # (前は字のまま `{owner}/{repo}` を宛先と読み、一覧の repo への投稿まで止めていた)
            here = None if here_unknown or not cwd else current_repo(cwd)
            if here is None:
                return None
            owner, name = here.split("/")
            path = API_REPO_RE.sub(lambda _: name, API_OWNER_RE.sub(lambda _: owner, path))
        seg = [p for p in path.split("/") if p]
        if len(seg) >= 3 and seg[0] == "repos":
            return {f"{seg[1]}/{seg[2]}"} | explicit
        if len(seg) >= 2 and seg[0] == "orgs":
            return {f"{seg[1]}/*"} | explicit
        return None  # users/... 等は宛先を特定できない
    if sub and sub[0] == "gist":
        return {"gist"} | explicit
    if repos:
        return explicit
    # サブコマンドを読めない(`gh api --知らない旗 …`)なら、URL がどの位置かも決まらず、宛先は -R でしか決まらない。
    # 走る場所の repo に倒さない(前は倒していて、`gh api --bogus repos/外/x/… -f body=…` を走る場所の repo と取り違えて通していた)
    if sub is None:
        return None
    # URL が投稿先を選ぶ位置(サブコマンドの後の最初の位置引数)に在れば、それが宛先。旗の後ろの URL(`--approve <URL>`)は
    # 旗の値か投稿先かを決めきれないので、URL の repo と、-R の無いときの宛先の両方を宛先になりうると見る
    selector = selector_of(args, sub)
    if urls and sub and sub[0] in URL_SELECTOR_SUBS and selector and ITEM_URL_RE.match(selector):
        return explicit
    # 明示が無ければ gh が GH_REPO か、走る場所のリポジトリから選んだ repo へ投稿する。GH_REPO・GIT_DIR などの値と走る場所が
    # 読み切れないとき・同じコマンドの中で宛先の repo を替えうるとき(`gh repo set-default 外/repo && gh pr create …`・
    # `git remote set-url …`)は宛先不明にする(フックの cwd で引くと、別のリポジトリへの投稿を許可一覧の repo と取り違える)
    if here_unknown or not cwd:
        return None
    here = current_repo(cwd)
    return None if here is None else explicit | {here}


def main():
    global cr, _DEADLINE
    allow_patterns = patterns()
    if not allow_patterns:
        return   # 一覧が無ければ眠る(入力も読まない)
    cr = gate_shell.load_coldread()
    _DEADLINE = time.time() + GH_BUDGET
    try:
        raw = json.load(sys.stdin)
        command = raw.get("tool_input", {}).get("command", "") if raw.get("tool_name") == "Bash" else ""
        if not isinstance(command, str):
            raise ValueError("tool_input.command が文字列でない")
    except Exception as exc:
        # 読めない入力を通さない(決まり 4: ゲートは入力を読めなかったら通さない側に倒す)
        why = str(exc)[:150]
        gate_shell.refuse(cr, "destgate", "deny 入力を読めない: %s" % why,
                          "外部投稿ゲート(destgate): フックの入力(JSON)を読めないので、宛先を検査できない: %s" % why)
    if not cr.GH_WORD_RE.search(command):
        return
    # 解析の入口は coldread と同じ cr.analyze 1 本。ここで独自に組むと、片方だけ
    # 正規化が入って宛先検査が黙って外れる(行継続の穴のとき現にそうなっていた)。gh が走る場所(前の cd)も同じ読み方で取る
    prepared = cr.prepare(command)
    analysis = cr.analyze(command, raw.get("cwd") or None, prepared)
    snippet = command[:150].replace("\n", " ")
    if not analysis.parsed:
        # 解析できない gh のコマンドは宛先を確かめられないので通さない。宛先の軸は coldread(通じやすさの軸)に任せず
        # このゲートが自分で止める
        gate_shell.refuse(cr, "destgate", "deny 解析不能: " + snippet,
                          "外部投稿ゲート(destgate): 宛先の許可制が有効だが、このコマンドを解析できず(%s)、宛先を確かめられない。"
                          "そこを直し、-R owner/repo で宛先を明示して再実行すること。" % (getattr(analysis, "why", None) or "引用符の閉じ忘れなど"))
    # GH_REPO・GIT_DIR などはコマンドのどこで書いても(前置・export)後の gh に効くので、値を追わず、書いてあれば -R の無い
    # 宛先を不明にする。Bash のコマンドは Claude Code の環境を継ぐので、この殻の環境に在るときも同じに見る
    # (前は GH_REPO だけを見ていて、`GIT_DIR=<別の repo>/.git gh …` を走る場所の repo と取り違えて通していた)
    dest_env = bool(DEST_ENV_RE.search(prepared[0])
                    or any(DEST_ENV_RE.fullmatch(k) and v for k, v in os.environ.items()))
    # 宛先の repo を替えうるコマンドは、gh の前でも後でも見る(繰り返しの中・`&` で並べた物は後に書いても先に走りうる)。
    # 引用の外の $( ) の中のコマンドも見るので、置換を語に留めない割り方(words を偽)で割る
    retargeted = any(retargets(c.args) for c in cr.split_commands(cr.tokenize(prepared[0], words=False)))
    for sub, args, candidates, blocked, cwd in analysis.calls:
        if not candidates and not blocked and not api_input_post(args, sub):
            continue  # 投稿の形をしていない
        if sub and sub[0] == cr.DISPATCH_SUB:
            continue  # works-dispatch の納品・頼みは手元の会社の中で届き、GitHub の宛先を持たない(本文は coldread が読む)
        dests = dest_of(args, sub, cwd, dest_env or retargeted)
        if dests is None:
            gate_shell.refuse(cr, "destgate", "deny 宛先不明: " + snippet,
                              "外部投稿ゲート(destgate): 宛先の許可制が有効だが、この投稿の宛先を"
                              "コマンドから特定できない。-R owner/repo で宛先を明示して再実行すること。")
        for dest in sorted(dests):
            if any(fnmatch.fnmatchcase(dest.lower(), pat.lower()) for pat in allow_patterns):
                continue
            gate_shell.refuse(cr, "destgate", f"deny {dest}: " + snippet,
                              f"外部投稿ゲート(destgate): この投稿の宛先 {dest} は許可一覧に無い。\n"
                              f"許可一覧は {ALLOWLIST}(owner/repo か owner/* を 1 行ずつ)。\n"
                              "一覧の管理は人の仕事——この deny を受けたモデルは一覧を自分で編集せず、"
                              "宛先を許してよいか人に確認すること。")


if __name__ == "__main__":
    gate_shell.run(main, lambda why: "外部投稿ゲート(destgate): 検査自体に失敗した(%s)。" % why,
                   lambda reason: gate_shell.load_coldread().deny(reason))
