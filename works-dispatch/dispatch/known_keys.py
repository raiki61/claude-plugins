"""会社の形（.claude/company.toml）と dispatch の設定（dispatch.toml）の、読む鍵と外した鍵の一覧。一覧はここ 1 か所に持ち、読む側
（nodes/tree.py・nodes/role.py・nodes/land.py・config.py）は、ここで知らない鍵と外した鍵を拾う。

知らない鍵（書き間違い・新しい版の鍵）と外した鍵（前の版で読んでいた鍵）は、読み飛ばす前に注記に出す（壊れたら機械が知らせる標準
docs/standards/breakage-detection.md の決まり 3）。止めるかは読む側が決める。ゲートを持つ所（役の deliver_check・ask_check などと、
取り込みの決まり [land]）は止め、ほかは注記だけにする（Kubernetes のフィールドの検査の Strict と Warn。
https://kubernetes.io/docs/reference/using-api/api-concepts/#field-validation ）。消えた鍵や書き間違えた鍵がゲートだった場合、黙って
通すとチェックを緩めるため。

中を見ない表: 役の [roles.settings] と受け持ちの settings（Claude Code に渡す中身）、ツールの inputSchema（JSON Schema）、[[land.after]] の input（ツールに渡す中身）。
鍵を足す・外すときは、読む側と一緒にここを直す（試験 test_known_keys が今の会社の形の見本で、知らない鍵が 0 件かを確かめる）。
"""

# 会社の形の表ごとの、読む鍵。表の名前は TOML の書き方の表の名前（頂きは ""、[land.roles.<役>] は land.roles）
COMPANY = {
    "": ("name", "description", "desk", "gh_user", "shared_instructions", "default_role", "desk_role", "roles", "skills", "land"),
    "roles": ("name", "instructions", "model", "effort", "account", "settings", "deliver", "deliver_check", "holders", "ask_check",
              "ask_holders", "persistent", "fresh", "machine", "tools", "former_names", "keepalive"),
    "roles.tools": ("name", "title", "description", "inputSchema", "command", "fallback_role"),
    "roles.keepalive": ("every", "text"),
    "skills": ("id", "name", "description", "role", "model", "effort", "settings", "account", "start", "on_demand", "per_ask", "keepalive"),
    "skills.start": ("report_to", "brief", "text", "every", "by"),
    "skills.keepalive": ("every", "text"),
    "land": ("mode", "gate", "check", "bump", "main", "queue", "batch", "roles", "after"),
    "land.roles": ("mode", "gate", "check", "bump", "main"),
    "land.after": ("role", "tool", "input"),
}
# 会社の形の外した鍵: 表 → {鍵: 行き先（読まなくなった訳と、代わりに書く所）}。今は無い
COMPANY_RETIRED = {}

# dispatch の設定の表ごとの、読む鍵
CONFIG = {
    "": ("limit_percent", "limits_dir", "move_early_percent", "move_early_reset_hours", "hours_margin_minutes",
         "accounts", "repos"),
    "accounts": ("name", "command", "config_dir", "keychain_service", "limits", "plan", "hours", "named_only", "max_open"),
    "repos": ("repo", "second_prompt_file", "source", "copy_files", "copy_from", "gh_user"),
}
CONFIG_RETIRED = {
    "": {"reset_soon_hours": "週の切り替わりの近さは、アカウントを選ぶ点数（週の残り ÷ 切り替わりまでの時間）に入ったので、"
                             "24 時間などの線は要らなくなった。設定から消してよい"},
    "repos": {"clone_root": "0.3.0 で外した。作業場はブランチごとの git worktree で作る。設定から消してよい",
              "task_cwd": "0.5.0 で外した。部署は自分の作業場で起動する。設定から消してよい"},
}


def odd(table, d, known=COMPANY, retired=COMPANY_RETIRED):
    """表 d（dict）の鍵のうち、知らない物と外した物。[(鍵, 外した鍵なら行き先・知らない鍵なら None)]。書いた順。d が表でなければ空。"""
    if not isinstance(d, dict):
        return []
    gone = retired.get(table, {})
    return [(k, gone.get(k)) for k in d if k not in known[table]]


def say(where, key, gone):
    """知らない鍵か外した鍵の注記の 1 行。外した鍵は、知らない鍵と分けて行き先を添える。"""
    if gone:
        return f"{where}: 外した鍵 {key} は読まない（{gone}）"
    return f"{where}: 知らない鍵 {key}（読まない。書き間違いか、この版の知らない鍵）"


def _rows(raw, key):
    got = raw.get(key, [])
    return got if isinstance(got, list) else []


def company(raw, path):
    """会社の形の全部の表の、知らない鍵と外した鍵の注記の並び。形の違う表（並びのはずが表など）は、読む側が problems に書くのでここでは見ない。"""
    out = [say(path, k, g) for k, g in odd("", raw)]
    for i, r in enumerate(_rows(raw, "roles")):
        name = f"（{r['name']}）" if isinstance(r, dict) and isinstance(r.get("name"), str) else ""
        out += [say(f"{path}: roles[{i}]{name}", k, g) for k, g in odd("roles", r)]
        for j, t in enumerate(_rows(r, "tools") if isinstance(r, dict) else []):
            out += [say(f"{path}: roles[{i}]{name} の tools[{j}]", k, g) for k, g in odd("roles.tools", t)]
        if isinstance(r, dict):
            out += [say(f"{path}: roles[{i}]{name} の keepalive", k, g) for k, g in odd("roles.keepalive", r.get("keepalive"))]
    for i, s in enumerate(_rows(raw, "skills")):
        name = f"（{s['name']}）" if isinstance(s, dict) and isinstance(s.get("name"), str) else ""
        out += [say(f"{path}: skills[{i}]{name}", k, g) for k, g in odd("skills", s)]
        if isinstance(s, dict):
            out += [say(f"{path}: skills[{i}]{name} の start", k, g) for k, g in odd("skills.start", s.get("start"))]
            out += [say(f"{path}: skills[{i}]{name} の keepalive", k, g) for k, g in odd("skills.keepalive", s.get("keepalive"))]
    out += land(raw.get("land"), path)
    return out


ALL = object()   # land の role に渡す、[land.roles.<役>] を全部見る印（会社の形の全体を見るとき）


def land(raw, path, role=ALL):
    """[land] の表（raw）の、知らない鍵と外した鍵の注記の並び。role に役の名前を渡せば、[land.roles.<役>] はその役の物だけ見る（取り込みに
    効く物）。役の無い部署（None）は、どの役の物も見ない（land.read_rules がどの役の物も重ねないのと同じ）。"""
    if not isinstance(raw, dict):
        return []
    out = [say(f"{path}: land", k, g) for k, g in odd("land", raw)]
    roles = raw.get("roles", {})
    for name, layer in (roles.items() if isinstance(roles, dict) else ()):
        if role is ALL or name == role:
            out += [say(f"{path}: land.roles.{name}", k, g) for k, g in odd("land.roles", layer)]
    for i, x in enumerate(_rows(raw, "after")):
        out += [say(f"{path}: land.after[{i}]", k, g) for k, g in odd("land.after", x)]
    return out
