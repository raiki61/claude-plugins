#!/usr/bin/env python3
"""role ノード: 会社の形のファイル（tree.read_info が見つけた物）から、役の項目と gh のアカウントを読み、部署に渡す物を組み立てる。書くのは、部署を起動するときの設定のファイル 1 つ（write_settings）だけ。

会社の形の設計（docs/specs/2026-10-16-company-shape-design.md）の 4.7（役ごとに起動時の文脈を絞る）と 4.8（役の渡し方）に当たる。
役は会社の形の [[roles]] に 1 つずつ書く。フィールドは次のとおりで、知らないフィールドは読み飛ばす。
- name: 役の名前（部署の属性 company.role と同じ字）
- instructions: 部署の会話の指示に足す役の本文。SessionStart のフックが毎回の起動で足すので短くし、AGENTS.md と同じことは書かない
- model: 部署を起動するときの --model。省けばそのアカウントの既定のまま起動する。受け持ち（[[skills]]）に model が有れば、
  その部署ではそちらが先に効く（launch_flags）。inherit（頼み元と同じ）は作らない（頼み元の会話の
  今のモデルを外から読む口が無い。Bash のツールの環境変数に無く〔hooks の文書 "There is no $CLAUDE_MODEL environment variable"〕、
  claude agents --json の 1 件にも無い）ので、書けば problems に書いて役を外す
- effort: 部署を起動するときの --effort（low・medium・high・xhigh・max・ultracode）。省けばそのアカウントの既定のまま起動する。
  inherit なら、呼んだ会話（頼み元）の今の effort で起動する。Claude Code は Bash のツールに今の effort を CLAUDE_EFFORT として渡す
  （hooks の文書）ので、入口がそれを読む。--effort はその会話にだけ効き、設定の effortLevel・modelSettings より強く、保存されない
  （CLI の文書）。知らない値は claude が注意を 1 行出すだけで既定に戻す（2.1.302 の -p で見た。裏の会話の注意は誰も読まない）ので、読むときに弾く
- settings: 部署を起動するときの --settings に渡す Claude Code の設定（表）。enabledPlugins・permissions.deny・skillOverrides など。
  その会話にだけ効き、利用者の全体の設定とリポジトリの設定は触らない
- deliver: その役が納品する要約の必須の項目（空でない文字列の並び）。省けば既定の項目（deliver ノードが持つ）
- deliver_check: その役の納品の検査のコマンド（シェルの字）。--deliver が項目を確かめた後に部署の作業場のルートで走らせ、0 以外で終われば
  送らない（何を確かめるかは会社の側のスクリプトが持つ。渡す物と終わりの値は deliver ノードの gate）。省けば検査しない
- holders: 納品の頭書きの [[open]]（残った疑問）の 1 件ごとの holder（担当者）を --deliver が確かめる（true か、持ち主の側と
  みなす名前の並び〔例 ["社長室"]。持ち主への中継の会話。空の並びは true と同じ〕）。holder に書けるのは、受付番号・owner:choose・
  owner:confirm・頼み元の名前（並びの名前を除く）だけ（部署の名前は --todo が追えない）。残った疑問の外の項目の「要確認」も止める。
  欠けていれば送らない（deliver ノードの holder_problems。my_notes の tools/deliver_check.py から移した）。
- ask_check: この役へ宛てた --ask のゲートのコマンド（シェルの字）。頼む会話がどの会社に居ても、--ask が受ける会社の origin の既定のブランチの
  中身（一時の worktree）で走らせ、JSON（to・role・body・ask・from・version〔works-dispatch の版〕）を標準入力に渡す。0 以外で終われば頼まない。止める中身は受ける会社の側のスクリプトが持つ。
  --dry-run（試し打ち）でも走る（通るかを試しで見られるように）（deliver_check の頼みの側。例 my_notes の社長室あての返事の要らない知らせを止める tools/no_notice.py --ask-check）
- ask_holders: holders と同じ形で、この役へ宛てた --ask の本文の頭書きに [[open]] が在れば、同じ検査を掛ける（頼み元の名前は頼む側の
  名前に読み替える。問いを受ける相談の役に書く）
- resident: true なら、その役の部署は常設（--resident を付けたのと同じ）。担当のように受け持ちに常設の役に書く。役で宛てた頼み
  （--ask 会社/役）で部署がまだ無いときに --resident を付け忘れると、都度の部署が立って次の頼みがその部署を見つけないため
- fresh: true なら、その役の部署は頼みごとに空の会話で受ける（前の頼みを納品し終えていれば、--ask が新しい頼みを打つ前に /clear を
  打つ）。省けば会話を持ち越す。resident とは別の軸で、常設の席（順番を 1 本にする・宛先の名前・決まった窓）は残したまま、
  前の頼みの記憶を持ち越さない（記憶は太るうえ、覚えた中身で書き直すと、ほかの部署が入れた行を消す。まっさらな環境での 2 回目の試し）
- machine: true なら、AI の部署を持たない役（ツールだけを持つ。--ask で宛てられない。部署を立てない）
- tools: 機械窓口のツールの並び（[[roles.tools]]。受付の設計 5.2）。フィールドは MCP の Tool に合わせた name・title・description・inputSchema と、
  ここだけの command（走らせるコマンド）・fallback_role（片づかなかったときに回す役。省けばその役。machine の役では要る）
- former_names: その役の前の名前の並び。役の名前を替えたときに書くと、前の名前で宛てた頼み（--ask 会社/前の名前）と、前の名前を
  属性 company.role に持つ部署・本社が、今の役に当たる（Terraform の moved のように、名前の替え方を会社の形に書いて、属性の側を
  手で直させない）。ほかの役の名前・前の名前と重なる物は problems に書いて外す
役ごとの項目を名前で引く表（[roles."役"]）の形は読まず、[[roles]] に移すよう problems に書く（TOML では同じ鍵 roles を
表の並びと表の両方で書けず、二つの形を混ぜると片方が黙って効かないため）。
会社の形の頭の gh_user は、その会社の gh のアカウント（部署の会話の Bash に GH_TOKEN として入れる。env_line）。
会社の形の頭の default_role は、--task で --role を省いたときの役（[[roles]] のどれかの name）。省けば入口の既定（作業）。
会社の形の頭の desk_role は、本社（代表の clone）で持ち主と話す会話の役（--desk で --role を省いたときの役。[[roles]] のどれかの name）。

入口の dispatch.py --task が起動するときに load・pick・settings_for・write_settings・gh_user・warnings を呼び、プラグインのフック
role_hook.py が context と env_line を呼ぶ。
"""

import json
import os
import re
import shlex
import tomllib

from nodes import tools

# 役の effort に書ける値（CLI の文書の --effort の Options）と、頼み元と同じ値で起動する印
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultracode")
INHERIT = "inherit"

# 頼みごとに空の会話で受ける部署の属性 company.fresh の値（役の fresh = true を写す。無ければ会話を持ち越す）
FRESH = "true"
# --role を渡さず、会社の形に default_role も無いときの役（一度きりの作業をする役。持ち主 2026-10-16 にサブエージェントから改名）
DEFAULT = "作業"

# 部署を起動するときに必ず効かせる設定の鍵。役の設定より強い（裏の会話が自分で worktree を作らず、先に作った作業場で働くため）
FIXED = {"worktree": {"bgIsolation": "none"}}


# 部署の席の種類のキー（機械が比べ・並べる値）と、人に見せる語（herdr の作業場の印 kind と --tree に役の後ろへ添える字）。
# 語は表示にだけ使い、比べない（語を言い換えても、並びと判定が替わらない）
SEAT_LABELS = {"resident-carry": "常設・持ち越し", "resident-fresh": "常設・毎回空", "per-task": "都度"}


def seat(residency, fresh):
    """部署の席の種類のキー（SEAT_LABELS の鍵）。常設なら会話の持ち越し方も分ける。"""
    if residency == "resident":
        return "resident-fresh" if fresh else "resident-carry"
    return "per-task"


def seat_label(residency, fresh):
    """部署の席の見え方（人に見せる語）。"""
    return SEAT_LABELS[seat(residency, fresh)]


# 部署を並べる仕事の流れの順（席の種類 seat のキー → 順。持ち主 2026-10-17 の案 A）。役の無い場所は最後
FLOW = ("resident-carry", "resident-fresh", "per-task")


def flow_rank(attrs, duties):
    """部署の、仕事の流れの順の鍵（小さい方が先）。常設・持ち越し（相談の社長室など）、常設・毎回空（担当。この中は duties の並び
    〔会社の形の [[skills]] の名前の書き順〕）、都度（作業）、役の無い場所。同じ鍵の物の順は呼ぶ側が決める（herdr の並びは今の順、
    --tree はブランチの名前）。herdr の作業場の並び（sync.flow_order）と --tree の部署の並び（tree.build）が同じ鍵を使う。"""
    attrs = attrs or {}
    seat_ = seat(attrs.get("residency"), attrs.get("fresh")) if attrs.get("role") else None
    rank = FLOW.index(seat_) if seat_ in FLOW else len(FLOW)
    names = list(duties)
    duty = names.index(attrs["name"]) if seat_ == "resident-fresh" and attrs.get("name") in names else len(names)
    return rank, duty


# ツールの名前（MCP の Tool.name の決まり: 英数字・_・-・. の 1〜128 字）
TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")


def _tools(r, where, problems):
    """役の [[roles.tools]] を読む。形の違うツールは problems に書いて外す。"""
    raw = r.get("tools", [])
    if not isinstance(raw, list):
        problems.append(f"{where}（{r['name']}）: tools が表の並び（[[roles.tools]]）で無い")
        return []
    out = []
    for j, t in enumerate(raw):
        at = f"{where}（{r['name']}）の tools[{j}]"
        if not isinstance(t, dict):
            problems.append(f"{at} が表で無い")
            continue
        bad = []
        if not (isinstance(t.get("name"), str) and TOOL_NAME.fullmatch(t["name"])):
            bad.append("name（英数字・_・-・. の 1〜128 字）")
        schema = t.get("inputSchema")
        if not (isinstance(schema, dict) and schema.get("type") == "object"):
            bad.append("inputSchema（ルートに type = \"object\" の表）")
        if not (isinstance(t.get("command"), str) and t["command"].strip()):
            bad.append("command（空でない文字列）")
        bad += [k for k in ("title", "description", "fallback_role") if k in t and not (isinstance(t[k], str) and t[k].strip())]
        if not bad:
            unchecked = tools.schema_problems(schema)
            if unchecked:
                problems.append(f"{at}: inputSchema の {', '.join(unchecked)} は入力の検査が確かめない（書いた制約が黙って効かない）ので外す。"
                                f"使えるのは {', '.join(sorted(tools.SCHEMA_KEYS))} と、各鍵の {', '.join(sorted(tools.PROPERTY_KEYS))}")
                continue
        if bad:
            problems.append(f"{at}: {', '.join(bad)} の形が違うので外す")
            continue
        if r.get("machine") is True and not t.get("fallback_role"):
            problems.append(f"{at}（{t['name']}）: 機械だけの役（machine = true）のツールなのに、片づかなかったときに回す役（fallback_role）が"
                            "無いので外す")
            continue
        if any(x["name"] == t["name"] for x in out):
            problems.append(f"{at}: ツール {t['name']} が 2 度書かれている（先の物を使う）")
            continue
        out.append({"name": t["name"], "title": (t.get("title") or "").strip() or None,
                    "description": (t.get("description") or "").strip() or None, "inputSchema": schema,
                    "command": t["command"].strip(), "fallback_role": (t.get("fallback_role") or "").strip() or r["name"]})
    return out


def _empty():
    return {"roles": {}, "gh_user": None, "default_role": None, "desk_role": None, "former": {}, "problems": []}


def load(path, text=None):
    """会社の形のファイルから {roles: 名前 → {name, instructions, model, effort, settings, deliver, deliver_check, resident, fresh}, gh_user, default_role, problems}。
    path が None なら空。
    text を渡せば、それを中身として読む（tree.read_info が読んだ物。path は注記に出す場所の札）。
    形の違う役は problems に書いて外し、ほかの役は読む。"""
    out = _empty()
    if not path:
        return out
    try:
        if text is None:
            with open(path, "rb") as f:
                raw = tomllib.load(f)
        else:
            raw = tomllib.loads(text)
    except (OSError, tomllib.TOMLDecodeError) as e:
        out["problems"].append(f"{path}: TOML として読めない（{e}）")
        return out
    gh_user = raw.get("gh_user")
    if gh_user is not None and not (isinstance(gh_user, str) and gh_user):
        out["problems"].append(f"{path}: gh_user が文字列で無い")
    elif gh_user:
        out["gh_user"] = gh_user
    roles = raw.get("roles", [])
    if isinstance(roles, dict):
        out["problems"].append(f"{path}: 役を [roles.\"役\"] の形で書いている（{', '.join(roles)}）。この形は読まないので、"
                               f"[[roles]] の項目（name = \"役\"）に移す")
        return out
    if not isinstance(roles, list):
        out["problems"].append(f"{path}: roles が表の並び（[[roles]]）で無い")
        return out
    for i, r in enumerate(roles):
        where = f"{path}: roles[{i}]"
        if not isinstance(r, dict) or not isinstance(r.get("name"), str) or not r["name"]:
            out["problems"].append(f"{where} に name が無い")
            continue
        bad = [k for k in ("instructions", "model") if k in r and not isinstance(r[k], str)]
        for k in ("deliver_check", "ask_check"):
            if k in r and not (isinstance(r[k], str) and r[k].strip()):
                bad.append(k)
        if "settings" in r and not isinstance(r["settings"], dict):
            bad.append("settings")
        bad += [k for k in ("resident", "fresh", "machine") if k in r and not isinstance(r[k], bool)]
        bad += [k for k in ("holders", "ask_holders") if k in r and not (isinstance(r[k], bool) or isinstance(r[k], list)
                                                                        and all(isinstance(x, str) and x for x in r[k]))]
        if "effort" in r and r["effort"] not in EFFORTS + (INHERIT,):
            bad.append("effort")
        if "deliver" in r and not (isinstance(r["deliver"], list) and r["deliver"]
                                   and all(isinstance(x, str) and x.strip() for x in r["deliver"])):
            bad.append("deliver")
        if bad:
            out["problems"].append(f"{where}（{r['name']}）: {', '.join(bad)} の形が違う（instructions・model は文字列、settings は表、"
                                   f"deliver は空でない文字列の並び、deliver_check・ask_check は空でない文字列、resident・fresh・machine は true か false、"
                                   f"holders・ask_holders は true・false か名前の並び、"
                                   f"effort は {'・'.join(EFFORTS + (INHERIT,))} のどれか）")
            continue
        if r.get("model") == INHERIT:
            out["problems"].append(f"{where}（{r['name']}）: model の inherit は作っていない（頼み元の会話の今のモデルを外から読む口が"
                                   f"無い）。モデルの名前を書くか、省いてアカウントの既定で起動する")
            continue
        for k in ("deliver", "deliver_check"):
            if isinstance(r.get("settings"), dict) and k in r["settings"]:
                out["problems"].append(f"{where}（{r['name']}）: {k} が [roles.settings] の中に入っている（{k} は [roles.settings] "
                                       f"より前に書く）")
        if r["name"] in out["roles"]:
            out["problems"].append(f"{where}: 役 {r['name']} が 2 度書かれている（先の物を使う）")
            continue
        out["roles"][r["name"]] = {"name": r["name"], "instructions": (r.get("instructions") or "").strip() or None,
                                   "model": r.get("model") or None, "effort": r.get("effort"), "settings": r.get("settings") or None,
                                   "deliver": [x.strip() for x in r["deliver"]] if "deliver" in r else None,
                                   "deliver_check": (r.get("deliver_check") or "").strip() or None,
                                   "ask_check": (r.get("ask_check") or "").strip() or None,
                                   "resident": r.get("resident") is True, "fresh": r.get("fresh") is True,
                                   "machine": r.get("machine") is True, "tools": _tools(r, where, out["problems"]),
                                   "holders": _holders(r.get("holders")), "ask_holders": _holders(r.get("ask_holders"))}
        olds = r.get("former_names", [])
        if not (isinstance(olds, list) and all(isinstance(x, str) and x.strip() for x in olds)):
            out["problems"].append(f"{where}（{r['name']}）: former_names が空でない文字列の並びで無いので外す")
            olds = []
        for old in (x.strip() for x in olds):
            if old != r["name"]:
                out["former"].setdefault(old, []).append(r["name"])
    for old, now in list(out["former"].items()):
        if old in out["roles"] or len(now) > 1:
            why = "今の役の名前" if old in out["roles"] else f"2 つ以上の役（{', '.join(now)}）の前の名前"
            out["problems"].append(f"{path}: 前の名前 {old} が{why}なので、前の名前としては引かない")
            del out["former"][old]
        else:
            out["former"][old] = now[0]
    for r in out["roles"].values():
        keep = []
        for t in r["tools"]:
            to = out["roles"].get(t["fallback_role"])
            if to is None or to["machine"]:
                why = "会社の形に無い" if to is None else "機械だけの役（AI の部署を持たない）"
                out["problems"].append(f"{path}: 役 {r['name']} のツール {t['name']} の回す役 {t['fallback_role']} が{why}ので外す")
                continue
            keep.append(t)
        r["tools"] = keep
    default = raw.get("default_role")
    if default is not None and not (isinstance(default, str) and default):
        out["problems"].append(f"{path}: default_role が文字列で無い")
    elif default and default not in out["roles"]:
        out["problems"].append(f"{path}: default_role の役 {default} が [[roles]] に無い（在る役: {', '.join(out['roles']) or 'なし'}）")
    elif default:
        out["default_role"] = default
    desk = raw.get("desk_role")
    if desk is not None and not (isinstance(desk, str) and desk):
        out["problems"].append(f"{path}: desk_role が文字列で無い")
    elif desk and current(out, desk) not in out["roles"]:
        out["problems"].append(f"{path}: desk_role の役 {desk} が [[roles]] に無い（在る役: {', '.join(out['roles']) or 'なし'}）")
    elif desk:
        out["desk_role"] = current(out, desk)
    return out


def current(shape, name):
    """役の名前を今の名前に引き直す（前の名前 former_names なら今の役の名前。ほかはそのまま）。"""
    return name if not name or name in shape["roles"] else shape.get("former", {}).get(name, name)


def default(shape, builtin):
    """--role を省いたときの役の名前と、止める訳。会社の形の default_role を先に、無ければ builtin。会社の形に役が書かれていて、
    その役が無ければ止める訳を返す（前は注記だけで、役の名前を英語で書いた会社では、どの役でもない「作業」の部署が役の本文も
    起動の設定も無いまま立った）。役を書いていない会社は builtin のまま止めない。"""
    name = shape.get("default_role") or builtin
    if shape["roles"] and name not in shape["roles"]:
        return name, (f"--role を省いたので役は既定の {name} だが、会社の形に無い（--role で名指すか、会社の形の頭に "
                      f"default_role = \"<役>\" を書く。在る役: {', '.join(shape['roles'])}）")
    return name, None


def pick(shape, name, explicit):
    """役の名前から役の項目。(項目か None, 止める訳か None)。会社の形に役が書かれていて、名前を明示したのに無ければ止める
    （書き損じで設定が黙って効かないのを防ぐ）。明示していない既定の役が無いのは止めない。"""
    got = shape["roles"].get(current(shape, name))
    if got is None and explicit and shape["roles"]:
        return None, f"役 {name} が会社の形に無い（在る役: {', '.join(shape['roles'])}）"
    return got, None


def launch_spec(role, duty=None):
    """会社の形が決める (model, effort)。effort の inherit は解かずにそのまま（launch_flags が呼んだ会話の値に解く）。"""
    duty = duty or {}
    return duty.get("model") or (role or {}).get("model"), duty.get("effort") or (role or {}).get("effort")


def desk_flags(role):
    """本社の窓口の会話を起動するときの (--model の値, --effort の値)。役のフィールドの値で、effort の inherit は旗を付けない（窓口には
    引き継ぐ呼んだ会話が無い）。None なら旗を付けない。"""
    model, effort = launch_spec(role)
    return model, None if effort == INHERIT else effort


def desk_spec(role):
    """窓口の会話が起きるときに効く (model, effort)。--tree の窓口の行に出す。フィールドごとに、旗（desk_flags）が --settings に渡す
    役の設定（[roles.settings]）の model・effortLevel より先に効き（CLI の文書）、どちらも無ければ None（アカウントの既定）。"""
    model, effort = desk_flags(role)
    conf = (role or {}).get("settings") or {}
    pick = lambda v: v if isinstance(v, str) and v else None
    return model or pick(conf.get("model")), effort or pick(conf.get("effortLevel"))


def launch_key(role, duty=None):
    """部署と窓口の属性 company.launched に書く字（起動したときの launch_spec と、役の起動の設定 [roles.settings]）。待ち受けが
    会社の形の今の値と比べ、違えば起動し直す（--move --if-changed。毎回空にする部署は次の頼みを渡す前、ほかは区切り〔--rest〕の
    ターンの終わり）。役に設定が無ければ settings のフィールドを書かない（設定のフィールドの無かった版で起動した部署を、違うと見て起動し直さない）。"""
    model, effort = launch_spec(role, duty)
    settings = (role or {}).get("settings")
    return json.dumps({"model": model, "effort": effort, **({"settings": settings} if settings else {})}, ensure_ascii=False,
                      sort_keys=True)


def launch_flags(role, env, duty=None):
    """部署を起動するときの (--model の値, --effort の値, 注記)。値が None なら旗を付けない（アカウントの既定のまま）。
    決める順はフィールドごとに、部署（duty。部署の名前と同じ name の受け持ち [[skills]] の項目）の値、役の値、アカウントの既定。
    役を 1 つ（担当）にして受け持ちを部署の名前で引くので、部署ごとに替えるなら受け持ちに書く。
    effort が inherit なら、呼んだ会話の今の effort（env の CLAUDE_EFFORT）。読めなければ旗を付けず、注記にする（止めない）。"""
    duty = duty or {}
    model, effort = launch_spec(role, duty)
    if effort != INHERIT:
        return model, effort, None
    if env.get("CLAUDE_EFFORT"):
        return model, env["CLAUDE_EFFORT"], None
    who = f"部署 {duty['name']}" if duty.get("effort") else f"役 {role['name']}"
    return model, None, (f"{who} の effort は inherit だが、呼んだ会話の effort が分からない（CLAUDE_EFFORT が無い。"
                         f"Claude Code の外から打ったか、頼み元のモデルが effort を持たない）ので、アカウントの既定の effort で起動する")


def _merge(base, top):
    out = dict(base)
    for k, v in top.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def settings_for(role):
    """部署を起動するときに --settings に渡す設定（dict）。役の設定に、必ず効かせる鍵（FIXED）を上から重ねる。"""
    return _merge((role or {}).get("settings") or {}, FIXED)


def _holders(value):
    """役の holders・ask_holders の値を、検査しないなら None、するなら持ち主の側とみなす名前の並び（空でもよい）にする。"""
    if value is True:
        return []
    return list(value) if isinstance(value, list) else None


def gh_user(repo_user, shape):
    """部署の会話に渡す gh のアカウントと、注記。dispatch の設定の [[repos]] の gh_user を先に、無ければ会社の形の gh_user。
    利用者の手元の設定を先にするのは、commit された会社の形に書かれたアカウントは、ほかの人のものでありうるため。"""
    company = shape.get("gh_user")
    if repo_user and company and repo_user != company:
        return repo_user, f"gh のアカウントは dispatch の設定の {repo_user} を使う（会社の形の gh_user {company} より先）"
    return repo_user or company, None


def context(role_name, role, company, duty=None, head_office=False, residency=None):
    """フックが部署の会話の指示に足す文。会社と役の 1 行に、受け持ち（duty。部署の名前と同じ name の受ける仕事 [[skills]] の項目が
    有れば）と、役の本文（会社の形に役の項目と本文が有れば）を続ける。受け持ちを足すのは、役を 1 つ（担当）にして、受け持ちごとの
    中身を部署の名前で引くため。head_office は代表の clone（--desk で名付けた窓口）の会話で、部署ではないので部署と書かない。"""
    head = f"この会話は会社「{company}」の{'本社の会話' if head_office else '部署'}で、役は「{role_name}」。"
    if duty and duty.get("description"):
        head += f"受け持ちは「{duty['name']}」（{duty['description']}）。"
    if duty and duty.get("standing") is False and not head_office and residency != "resident":
        head += "この受け持ちは頼まれたときだけ立てる物で、この部署は都度の部署（頼みを済ませたら畳まれる）。"
    return head + (f"\n{role['instructions']}" if role and role["instructions"] else "")


SETTINGS_FILE = "company-settings.json"


def write_settings(folder, data):
    """部署を起動するときの設定を、部署の worktree の .git の場所（folder。commit されず、部署と一緒に消える）に書いてパスを返す。
    シェルに JSON を直に打ち込まない（Windows のシェルでは二重引用符を渡せない）。"""
    path = os.path.join(folder, SETTINGS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_desk_settings(folder, role):
    """本社の窓口の会話を起動するときの設定を、代表の clone の .git の場所（folder）に書いてパスを返す。役に設定が無ければ None。
    役の設定だけを書き、部署の FIXED は重ねない（裏の会話が自分で worktree を作らないための鍵で、前で動く窓口には要らない）。"""
    data = (role or {}).get("settings")
    return write_settings(folder, data) if data else None


def warnings(role, plugin="works-dispatch"):
    """役の設定が、役を足すフックを持つこのプラグインを切っていれば、その注記。"""
    plugins = ((role or {}).get("settings") or {}).get("enabledPlugins")
    off = [k for k, v in (plugins.items() if isinstance(plugins, dict) else ()) if k.split("@")[0] == plugin and v is False]
    return [f"役 {role['name']} の設定が {', '.join(off)} を切っているので、部署の会話に役の本文が足されない"] if off else []


# 鍵を取り出せなかったときに GH_TOKEN に入れる字（gh が認証に失敗して止まり、ほかのアカウントに落ちない）
NO_TOKEN = "gh-user-not-logged-in"


def env_line(user):
    """SessionStart のフックが CLAUDE_ENV_FILE に足す 1 行。Claude Code は Bash のツールのコマンドごとに、このファイルをシェルのコードとして
    先に走らせる（hooks の文書 "Each Bash command runs the file's contents as shell code before the command itself"）ので、鍵の値は
    書かず、取り出すコマンドを書く。鍵はそのつど gh から取り出され、ファイルにも画面にも残らない。
    取り出せない（そのアカウントでログインしていない）ときは、空にせず使えない字を入れる。空の GH_TOKEN は無いのと同じに扱われ、gh が
    黙って有効なアカウントで動いてしまう（別の人として push やコメントをする）ため。
    起動するコマンドの前に環境変数として置く形は、裏の会話（--bg）に届かなかった（2026-10-16 に 2.1.301 で見た）。"""
    return f'export GH_TOKEN="$(gh auth token --user {shlex.quote(user)} || echo {NO_TOKEN})"'
