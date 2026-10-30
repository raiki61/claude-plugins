"""単価を引く。同梱の写し → 最新（1 日に 1 回まで取る）→ 使う人のファイル → 呼ぶときの JSON の順に重ね、後が勝つ。

手本は ccusage（写しを同梱し、最新を取りに行き、取れなければ写しで計算する）。
"""
import json
import math
import os
import threading
import time
import tomllib
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from . import names

HERE = Path(__file__).resolve().parent
LITELLM_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
COMMIT_URL = "https://api.github.com/repos/BerriAI/litellm/commits/main"
LITELLM_AT_URL = "https://raw.githubusercontent.com/BerriAI/litellm/%s/model_prices_and_context_window.json"  # commit を指して取る口
DAY = 24 * 3600
FETCH_TIMEOUT_S = 5  # 1 日 1 回の取り直し全体（2 回の HTTP をまとめて）の持ち時間。keepalive のたびに裏で呼ばれるので、ネットワークが固まっても判断を待たせない
LATEST_MAX_AGE_DAYS = 7  # 最新の控えがこれより古ければ使わない

# 内側の名前 → LiteLLM のフィールド（1 トークンあたりのドル）
FIELDS = {
    "input": "input_cost_per_token",
    "write_5m": "cache_creation_input_token_cost",
    "write_1h": "cache_creation_input_token_cost_above_1hr",
    "read": "cache_read_input_token_cost",
    "output": "output_cost_per_token",
}
TIER_SUFFIX = "_above_100k_tokens"  # 送る文が 10 万トークンを超えると単価が上がるモデル（Haiku 5.5）のフィールド
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
    if not all(_positive(x) for x in v.values()):
        return False
    return v["read"] < v["input"] < min(v["write_5m"], v["write_1h"])


def _positive(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def clean(entry: dict) -> dict:
    """10 万トークン超の段のフィールドのうち、正の有限の数でない物と、基の単価より低い物を落とす。"""
    out = dict(entry)
    for f in FIELDS.values():
        t = f + TIER_SUFFIX
        if t in out and not (_positive(out[t]) and out[t] >= entry.get(f, 0)):
            del out[t]
    return out


def pick(raw: dict) -> dict:
    """値段表から、Anthropic に直に繋ぐときの `claude-` の項目で、使える物の、使うフィールドだけを抜く。"""
    out = {}
    for key, entry in raw.items():
        if key.startswith("claude-") and "/" not in key and usable(entry):
            out[key] = clean({f: entry[f] for f in KEEP if f in entry})
    return dict(sorted(out.items()))


def build_snapshot(raw: dict, commit: str, fetched: str) -> dict:
    return {"source": LITELLM_URL, "commit": commit, "fetched": fetched, "models": pick(raw)}


def _read_table(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def defaults() -> dict:
    """prices.toml（実測の値と既定）。"""
    return tomllib.loads((HERE / "prices.toml").read_text(encoding="utf-8"))


def _http_json(url: str, deadline: float):
    """url の JSON を取る。deadline（time.monotonic の時刻）を過ぎたら TimeoutError。読みも区切って見る。"""
    def left() -> float:
        t = deadline - time.monotonic()
        if t <= 0:
            raise TimeoutError("fetch deadline passed")
        return t
    with urllib.request.urlopen(url, timeout=left()) as r:
        chunks = []
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
            left()
        data = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("%s did not return a JSON object" % url)
    return data


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.%d" % os.getpid())
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def fetch_snapshot(today: str, timeout: float = FETCH_TIMEOUT_S) -> dict:
    """LiteLLM の main の commit を取り、その commit の値段表を取って、写しの形にする。2 回の取得をまとめて timeout 秒で打ち切る。
    失敗は例外のまま出す。値段表を main の URL から取らないのは、CDN の写しが数分遅れて別の commit の値段になりうるため。"""
    deadline = time.monotonic() + timeout
    commit = _http_json(COMMIT_URL, deadline)["sha"]
    return build_snapshot(_http_json(LITELLM_AT_URL % commit, deadline), commit, today)


def _fetch_within_deadline(today: str) -> dict:
    """fetch_snapshot を使い捨ての別スレッドで回し、FETCH_TIMEOUT_S で打ち切る（名前引きや遅い読みで固まっても待たせない）。"""
    box: dict = {}

    def run():
        try:
            box["snap"] = fetch_snapshot(today)
        except BaseException as e:  # noqa: BLE001 - 呼び側へ運ぶ
            box["err"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(FETCH_TIMEOUT_S)
    if t.is_alive():
        raise TimeoutError("fetch did not finish in %s s" % FETCH_TIMEOUT_S)
    if "err" in box:
        raise box["err"]
    return box["snap"]


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
        snap = _fetch_within_deadline(time.strftime("%Y-%m-%d", time.gmtime(now)))
        if snap["models"]:
            _atomic_write(d / "latest.json", json.dumps(snap, ensure_ascii=False))
    except Exception:
        # 最新の取り直しは費用の最適化にすぎない。どんな失敗（通信・形・書き込み・想定外）でも写しで計算し、
        # 判断を止めない（止めるゲートではない）。なので例外の種類を絞らない
        return


def _layer(path: Path, label: str, tolerate: bool):
    """写しか最新のファイルを読む。tolerate なら読めない・壊れた物は無いものとする（写しは試験が守る）。"""
    try:
        data = _read_table(path)
        if not isinstance(data, dict):
            raise ValueError("top level is not an object")
        models = {k: clean(v) for k, v in data["models"].items() if usable(v)}
        return models, {"commit": data.get("commit"), "fetched": data.get("fetched")}
    except (OSError, ValueError, KeyError, AttributeError):
        if tolerate:
            return {}, {}
        raise PricesError("prices_unreadable", "cannot read %s: %s" % (label, path), 2)


def _override(data, label: str) -> dict:
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        raise PricesError("invalid_input", "%s must be a table of model name -> {field: price}" % label, 2)
    for model, fields in data.items():
        for f in KEEP:
            if f in fields and not _positive(fields[f]):
                raise PricesError("invalid_input", "%s: %s.%s must be a positive finite number: %r" % (label, model, f, fields[f]), 2)
    return data


@dataclass(frozen=True)
class Price:
    model: str   # 揃えた値段表の名前
    entry: dict  # LiteLLM のフィールド → 単価
    source: str  # snapshot・latest・override
    origin: dict
    latest_skipped: Optional[str] = None  # 最新の控えを使わなかった訳（stale）

    def rate(self, kind: str, prompt_tokens: int = 0) -> float:
        """kind（FIELDS の鍵）の 1 トークンあたりの単価。送る文が 10 万を超えれば上の段のフィールドを使う。"""
        field = FIELDS[kind]
        if prompt_tokens > TIER_LIMIT and field + TIER_SUFFIX in self.entry:
            return self.entry[field + TIER_SUFFIX]
        return self.entry[field]

    def info(self) -> dict:
        out = {"model": self.model, "source": self.source, "origin": self.origin}
        if self.latest_skipped:
            out["latest_skipped"] = self.latest_skipped
        return out


def _stale(fetched, snap_fetched, now: Optional[float]) -> bool:
    """最新の控えの取得日が、写しの取得日より古いか、今から 7 日より前か（読めない日付も古い扱い）。"""
    try:
        got = date.fromisoformat(fetched)
        if snap_fetched and got < date.fromisoformat(snap_fetched):
            return True
        today = date.fromisoformat(time.strftime("%Y-%m-%d", time.gmtime(time.time() if now is None else now)))
        return (today - got).days > LATEST_MAX_AGE_DAYS
    except (TypeError, ValueError):
        return True


def lookup(model: str, override: Optional[dict] = None, env=os.environ, now: Optional[float] = None) -> Price:
    """モデル名から単価を引く。知らないモデルは PricesError（unknown_model、コード 3）。"""
    snap, snap_origin = _layer(HERE / "snapshot.json", "bundled snapshot", tolerate=False)
    layers = [("snapshot", snap, snap_origin)]
    refresh_latest(env, now)
    latest, latest_origin = _layer(cache_dir(env) / "latest.json", "latest", tolerate=True)
    skipped = None
    if latest and _stale(latest_origin.get("fetched"), snap_origin.get("fetched"), now):
        latest, skipped = {}, "stale"
    if latest:
        layers.append(("latest", latest, {"fetched": latest_origin["fetched"], "commit": latest_origin["commit"]}))
    path = env.get("RENT_OR_BUY_PRICES")
    if path:
        try:
            data = _override(_read_table(Path(path)), "RENT_OR_BUY_PRICES")
        except (OSError, ValueError) as e:
            raise PricesError("invalid_input", "cannot read RENT_OR_BUY_PRICES: %s" % e, 2)
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
        raise PricesError("unknown_model", "model not in the price table: %r (normalized %r)" % (model, names.normalize(model)), 3)

    entry, source, origin = {}, "", {}
    for label, table, org in layers:
        if key in table:
            entry, source, origin = {**entry, **table[key]}, label, org
    if not usable(entry):
        raise PricesError("invalid_input" if source == "override" else "unknown_model",
                          "prices of %s are incomplete or not in the order read < input < write" % key,
                          2 if source == "override" else 3)
    return Price(key, clean(entry), source, origin, skipped)  # 上書きで基の単価が上がり、段が基より低くなった物を落とす
