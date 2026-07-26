"""
Multi-key Gemini API rotation.

Stores up to 5 Gemini API keys in config/api_keys.json under "gemini_api_keys"
(a list). Falls back to the legacy single "gemini_api_key" field if the list
is empty, so existing configs keep working without migration.

Whenever a call hits a quota / rate-limit error (HTTP 429 / RESOURCE_EXHAUSTED),
the offending key is marked "exhausted" for a cooldown window and the rotation
cursor advances to the next configured key — so callers automatically spread
load across all 5 keys instead of failing the moment one hits its quota.
"""
import json
import sys
import threading
import time
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = _base_dir()
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

MAX_KEYS       = 5
_COOLDOWN_SECS = 5 * 60   # how long an exhausted key is skipped before retrying it

_lock      = threading.Lock()
_cursor    = 0                        # index of the "current" key in rotation
_exhausted: dict[str, float] = {}     # key -> timestamp it was marked exhausted


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
    except Exception as e:
        print(f"[GeminiKeys] ⚠️ Could not save config: {e}")


def get_all_keys() -> list[str]:
    """
    Returns all configured Gemini keys (up to 5).
    Falls back to the single legacy 'gemini_api_key' if 'gemini_api_keys' is empty.
    """
    cfg  = _load_config()
    keys = [k.strip() for k in cfg.get("gemini_api_keys", []) if k and k.strip()]
    if not keys:
        legacy = (cfg.get("gemini_api_key") or "").strip()
        if legacy:
            keys = [legacy]
    return keys[:MAX_KEYS]


def set_all_keys(keys: list[str]) -> None:
    """
    Persists up to 5 Gemini keys. Keeps the legacy 'gemini_api_key' field
    in sync with the first key so older code paths keep working.
    Resets rotation state (fresh keys deserve a clean slate).
    """
    cleaned = []
    for k in keys:
        k = (k or "").strip()
        if k and k not in cleaned:
            cleaned.append(k)
    cleaned = cleaned[:MAX_KEYS]

    cfg = _load_config()
    cfg["gemini_api_keys"] = cleaned
    if cleaned:
        cfg["gemini_api_key"] = cleaned[0]
    _save_config(cfg)

    with _lock:
        global _cursor
        _cursor = 0
        _exhausted.clear()


def _is_cooled_down(key: str) -> bool:
    ts = _exhausted.get(key)
    return ts is None or (time.time() - ts) >= _COOLDOWN_SECS


def get_key() -> str:
    """
    Returns the best key to use right now — the current rotation slot,
    skipping any key still inside its cooldown window.
    Raises RuntimeError if no key is configured at all.
    """
    keys = get_all_keys()
    if not keys:
        raise RuntimeError(
            "No Gemini API key configured. Add up to 5 keys in Settings / setup."
        )

    with _lock:
        n = len(keys)
        for i in range(n):
            idx = (_cursor + i) % n
            k   = keys[idx]
            if _is_cooled_down(k):
                return k
        # every key is on cooldown — use the one that's been resting longest
        return min(keys, key=lambda k: _exhausted.get(k, 0))


def mark_exhausted(key: str) -> None:
    """Call when a key hits a 429 / RESOURCE_EXHAUSTED — rotates past it."""
    keys = get_all_keys()
    if key not in keys:
        return
    with _lock:
        _exhausted[key] = time.time()
        global _cursor
        _cursor = (keys.index(key) + 1) % len(keys)
    tail = key[-4:] if len(key) >= 4 else key
    print(f"[GeminiKeys] ⚠️ Key …{tail} exhausted — rotating to next key "
          f"({len(keys)} configured).")


def is_quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "resource_exhausted" in msg or "quota" in msg


def call_with_rotation(fn, *args, **kwargs):
    """
    Calls fn(api_key, *args, **kwargs) — fn's first positional argument must
    accept the Gemini API key. Automatically retries across all configured
    keys when a quota error is hit, so a single exhausted key doesn't fail
    the whole request as long as another key still has quota left.

    Non-quota errors are raised immediately (no point burning other keys
    on e.g. a malformed request).
    """
    keys = get_all_keys()
    if not keys:
        raise RuntimeError(
            "No Gemini API key configured. Add up to 5 keys in Settings / setup."
        )

    last_exc: Exception | None = None
    tried: set[str] = set()

    for _ in range(len(keys)):
        key = get_key()
        if key in tried:
            break
        tried.add(key)
        try:
            return fn(key, *args, **kwargs)
        except Exception as e:
            last_exc = e
            if is_quota_error(e):
                mark_exhausted(key)
                continue
            raise

    raise last_exc or RuntimeError("All configured Gemini API keys are exhausted.")
