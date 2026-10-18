"""engine が claude を起動する語の正本——起動する側（advance の launch_spec・delegate_launch_spec・runner_launch_spec）と、
起動してよいかのチェック（commands の許可表）が、ここから組む。

以前は graph の launch.<形>.argv・resume・via に同じ語を約 14 か所並べ、チェックの許可表（commands の *_FLAGS）を別に手で書いていた。
チェックは graph の宣言を根拠にしない（graph を書き換えられる立場の人がチェックごと書き換えられる）ので、許可表は engine が持つしかない
——同じ語を 2 か所に持つと、片方だけ直したときに起動が黙って拒まれるか、graph の語がチェックの外に出る。語は engine が 1 か所で持ち、
graph は形ごとに起動するか（launch.<形> を書くか）・前置きの文・モデルなどの engine の語彙の外の値だけを持つ。

値の穴（{model} など）は advance.LAUNCH_HOLES の語で、起動する側が埋める。値の決まった語（"" や "json"）は、チェックが値まで
突き合わせる（commands.FIXED_VALUES と _want_values）。"""

CLAUDE = "claude"
# 解決した argv の前に置く語（認証だけを足す同梱の層）。子は対話の claude の認証を継がない（理由の正本は graph の launch.isolated.why）
VIA = ("{python}", "{plugin_root}/scripts/with-auth.py")
# 前置の層が足した認証の段を JSON で書く先を名指す環境変数（層の側の AUTH_NOTE_ENV と同じ名前。試験が突き合わせる）
AUTH_NOTE_ENV = "GRAPHLOOPS_AUTH_NOTE"
RESUME = ("--resume", "{session_id}")   # 同じ会話を続ける語。-p の直後に置く
# 返答の形（ノードの schema）を渡す旗。schema を持つノードの子にだけ付け、値は advance.cli_schema が組む
JSON_SCHEMA = "--json-schema"

_MODEL = (("--model", "{model}"), ("--effort", "{effort}"))
_TAIL = (("--setting-sources", ""), ("--append-system-prompt-file", "{role_file}"), ("--output-format", "json"))
_TOOLED = (("--tools", "{tools}"), ("--allowedTools", "{allowed_tools}"), ("--permission-mode", "{permission_mode}"),
           ("--settings", "{settings}"), ("--permission-prompts", "none"))
# 形ごとの (旗, 値) の並び。-p と続ける語と --json-schema は形に依らないので argv() が足す
FLAGS = {
    # ツールゼロの役: ツールも設定も読まない
    "isolated": _MODEL + (("--tools", ""),) + _TAIL,
    # ツールゼロの役に、ノードの read_file の写し 1 本だけを読む Read を渡す形
    "isolated_read": _MODEL + (("--tools", "Read"), ("--allowedTools", "{allowed_tools}"), ("--permission-mode", "dontAsk"),
                               ("--permission-prompts", "none")) + _TAIL,
    # ツールつきの役。権限の値は engine が役の定義のツールから決める（role_run.tooled_permission）
    "tooled": _MODEL + _TOOLED + _TAIL,
    # 任せ先。モデルだけを graph の delegate.model で名指す（effort は持たない）
    "delegate": _MODEL[:1] + _TOOLED + _TAIL,
    # 回す側のノード。権限の値は engine が決める（role_run の runner_permission・skill_permission）
    "runner": _MODEL + _TOOLED + _TAIL,
}
KINDS = tuple(FLAGS)


def argv(kind, resume=False, schema=False):
    """形 kind の claude の語（穴は埋めない）。resume は同じ会話を続ける語、schema は --json-schema {json_schema} を足すか"""
    words = [CLAUDE, "-p", *(RESUME if resume else ())]
    for flag, value in FLAGS[kind]:
        words += [flag, value]
    return words + ([JSON_SCHEMA, "{json_schema}"] if schema else [])


def flags(kind):
    """形 kind の許可表（チェックの _parse_flags が読む旗の並び）。-p・--resume・--json-schema を含む"""
    return ("-p", RESUME[0], *(f for f, _ in FLAGS[kind]), JSON_SCHEMA)
