"""単価を引く。同梱の写し → 最新（1 日に 1 回まで取る）→ 使う人のファイル → 呼ぶときの JSON の順に重ね、後が勝つ。

手本は ccusage（写しを同梱し、最新を取りに行き、取れなければ写しで計算する）。
"""
import json
import os
import time
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import names

HERE = Path(__file__).resolve().parent
LITELLM_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
COMMIT_URL = "https://api.github.com/repos/BerriAI/litellm/commits/main"
DAY = 24 * 3600
FETCH_TIMEOUT_S = 5  # keepalive のたびに裏で呼ばれるので、ネットワークが固まっても判断を待たせない

# 内側の名前 → LiteLLM の欄（1 トークンあたりのドル）
FIELDS = {
    "input": "input_cost_per_token",
    "write_5m": "cache_creation_input_token_cost",
    "write_1h": "cache_creation_input_token_cost_above_1hr",
    "read": "cache_read_input_token_cost",
    "output": "output_cost_per_token",
}
TIER_SUFFIX = "_above_100k_tokens"  # 送る文が 10 万トークンを超えると単価が上がるモデル（Haiku 5.5）の欄
TIER_LIMIT = 100_000
KEEP = tuple(FIELDS.values()) + tuple(f + TIER_SUFFIX for f in FIELDS.values())


class PricesError(Exception):
    """単価を決められない。key は機械の読む鍵、code は bin/rent-or-buy の終わりのコード。"""

    def __init__(self, key: str, why: str, code: int):
        super().__init__(why)
        self.key, self.why, self.code = key, why, code


def cache_dir(env=os.environ) -> Path:
    return Path(env.get("RENT_OR_BUY_CACHE_DIR") or Path.home() / ".cache" / "rent-or-buy")


def usable(entry) -> bool:
    """5 つの単価が揃って正の数で、読み < 入力 < 書き込みの順か。"""
    try:
        v = {k: entry[f] for k, f in FIELDS.items()}
    except (KeyError, TypeError):
        return False
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in v.values()):
        return False
    return v["read"] < v["input"] < min(v["write_5m"], v["write_1h"])


def pick(raw: dict) -> dict:
    """値段表から、Anthropic に直に繋ぐときの `claude-` の項目で、使える物の、使う欄だけを抜く。"""
    out = {}
    for key, entry in raw.items():
        if key.startswith("claude-") and "/" not in key and usable(entry):
            out[key] = {f: entry[f] for f in KEEP if f in entry}
    return dict(sorted(out.items()))


def build_snapshot(raw: dict, commit: str, fetched: str) -> dict:
    return {"source": LITELLM_URL, "commit": commit, "fetched": fetched, "models": pick(raw)}


def _read_table(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def defaults() -> dict:
    """prices.toml（実測の値と既定）。"""
    return tomllib.loads((HERE / "prices.toml").read_text(encoding="utf-8"))


def _http_json(url: str):
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.%d" % os.getpid())
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def fetch_snapshot(today: str) -> dict:
    """LiteLLM の main から値段表と commit を取って、写しの形にする。失敗は例外のまま出す。"""
    commit = _http_json(COMMIT_URL)["sha"]
    return build_snapshot(_http_json(LITELLM_URL), commit, today)


def refresh_latest(env=os.environ, now: Optional[float] = None) -> None:
    """最新を 1 日に 1 回まで取り、cache_dir/latest.json に控える。RENT_OR_BUY_OFFLINE=1 なら取りに行かない。

    取れない・使える項目が 0 のときは、写しで計算する（仕様）ので何も書かない。試した印 latest.tried は
    失敗でも残し、次の 1 日は取りに行かない。
    """
    if env.get("RENT_OR_BUY_OFFLINE") == "1":
        return
    now = time.time() if now is None else now
    d = cache_dir(env)
    tried = d / "latest.tried"
    try:
        if tried.exists() and now - tried.stat().st_mtime < DAY:
            return
        d.mkdir(parents=True, exist_ok=True)
        tried.touch()
        os.utime(tried, (now, now))
        snap = fetch_snapshot(time.strftime("%Y-%m-%d", time.gmtime(now)))
        if snap["models"]:
            _atomic_write(d / "latest.json", json.dumps(snap, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError):
        # 取れない・読めない・書けないときは写しで計算する。ここで止めない（費用の最適化で、止めるゲートではない）
        return


def _layer(path: Path, label: str, tolerate: bool):
    """写しか最新のファイルを読む。tolerate なら読めない・壊れた物は無いものとする（写しは試験が守る）。"""
    try:
        data = _read_table(path)
        models = {k: v for k, v in data["models"].items() if usable(v)}
        return models, {"commit": data.get("commit"), "fetched": data.get("fetched")}
    except (OSError, ValueError, KeyError, AttributeError):
        if tolerate:
            return {}, {}
        raise PricesError("prices_unreadable", "%s を読めない: %s" % (label, path), 2)


def _override(data, label: str) -> dict:
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        raise PricesError("invalid_input", "%s は モデル名→{欄: 単価} の表でなければならない" % label, 2)
    return data


@dataclass(frozen=True)
class Price:
    model: str   # 揃えた値段表の名前
    entry: dict  # LiteLLM の欄 → 単価
    source: str  # snapshot・latest・override
    origin: dict

    def rate(self, kind: str, prompt_tokens: int = 0) -> float:
        """kind（FIELDS の鍵）の 1 トークンあたりの単価。送る文が 10 万を超えれば上の段の欄を使う。"""
        field = FIELDS[kind]
        if prompt_tokens > TIER_LIMIT and field + TIER_SUFFIX in self.entry:
            return self.entry[field + TIER_SUFFIX]
        return self.entry[field]

    def info(self) -> dict:
        return {"model": self.model, "source": self.source, "origin": self.origin}


def lookup(model: str, override: Optional[dict] = None, env=os.environ, now: Optional[float] = None) -> Price:
    """モデル名から単価を引く。知らないモデルは PricesError（unknown_model、コード 3）。"""
    snap, snap_origin = _layer(HERE / "snapshot.json", "同梱の写し", tolerate=False)
    layers = [("snapshot", snap, snap_origin)]
    refresh_latest(env, now)
    latest, latest_origin = _layer(cache_dir(env) / "latest.json", "最新", tolerate=True)
    if latest:
        layers.append(("latest", latest, {"fetched": latest_origin["fetched"], "commit": latest_origin["commit"]}))
    path = env.get("RENT_OR_BUY_PRICES")
    if path:
        try:
            data = _override(_read_table(Path(path)), "RENT_OR_BUY_PRICES")
        except (OSError, ValueError) as e:
            raise PricesError("invalid_input", "RENT_OR_BUY_PRICES を読めない: %s" % e, 2)
        layers.append(("override", data, {"file": path}))
    if override:
        layers.append(("override", _override(override, "prices"), {"arg": True}))

    try:
        aliases = names.parse_aliases(env.get("RENT_OR_BUY_MODEL_ALIASES"))
    except ValueError as e:
        raise PricesError("invalid_input", "RENT_OR_BUY_MODEL_ALIASES: %s" % e, 2)
    known = {k for _, table, _ in layers for k in table}
    key = names.resolve(model, known, aliases)
    if key is None:
        raise PricesError("unknown_model", "値段表に無いモデル: %r（揃えた名前 %r）" % (model, names.normalize(model)), 3)

    entry, source, origin = {}, "", {}
    for label, table, org in layers:
        if key in table:
            entry, source, origin = {**entry, **table[key]}, label, org
    if not usable(entry):
        raise PricesError("invalid_input" if source == "override" else "unknown_model",
                          "%s の単価が揃っていないか、読み < 入力 < 書き込みの順でない" % key,
                          2 if source == "override" else 3)
    return Price(key, entry, source, origin)
