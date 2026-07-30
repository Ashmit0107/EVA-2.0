"""
Multi-key Gemini API rotation.

Keys now live ONLY in the .env file at the project root, under the
GEMINI_API_KEYS env var (comma-separated, up to 5). They are never written
to config/api_keys.json anymore — that file was previously committed to git
by mistake and must only ever hold non-secret settings.

If no keys are found in .env, get_all_keys() returns an empty list and the
existing UI setup / "Manage Gemini Keys" overlay prompts the user, then
set_all_keys() persists whatever they enter back into .env.

Whenever a call hits a quota / rate-limit error (HTTP 429 / RESOURCE_EXHAUSTED),
the offending key is marked "exhausted" for a cooldown window and the rotation
cursor advances to the next configured key — so callers automatically spread
load across all 5 keys instead of failing the moment one hits its quota.
"""
import sys
import threading
import time
from pathlib import Path

try:
    from dotenv import load_dotenv, dotenv_values, set_key
except ImportError:  # pragma: no cover - dotenv should always be installed
    load_dotenv = None
    dotenv_values = None
    set_key = None


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
ENV_PATH = BASE_DIR / ".env"
ENV_VAR  = "GEMINI_API_KEYS"

MAX_KEYS       = 5
_COOLDOWN_SECS = 5 * 60   # how long an exhausted key is skipped before retrying it

_lock      = threading.Lock()
_cursor    = 0                        # index of the "current" key in rotation
_exhausted: dict[str, float] = {}     # key -> timestamp it was marked exhausted

# Load .env once at import time so os.environ has the keys available
# for the whole process (main.py also calls load_dotenv() at startup —
# calling it again here is harmless and keeps this module self-sufficient
# even if it's imported before main.py runs).
if load_dotenv is not None:
    load_dotenv(dotenv_path=ENV_PATH, override=False)


def _ensure_env_file() -> None:
    if not ENV_PATH.exists():
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        ENV_PATH.write_text("", encoding="utf-8")


def _read_env_keys() -> list[str]:
    """Read GEMINI_API_KEYS straight from the .env file (source of truth),
    falling back to the current process environment if dotenv isn't available."""
    raw = ""
    if dotenv_values is not None and ENV_PATH.exists():
        raw = (dotenv_values(ENV_PATH).get(ENV_VAR) or "").strip()
    if not raw:
        import os
        raw = (os.environ.get(ENV_VAR) or "").strip()
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


def _write_env_keys(keys: list[str]) -> None:
    _ensure_env_file()
    value = ",".join(keys)
    if set_key is not None:
        set_key(str(ENV_PATH), ENV_VAR, value, quote_mode="never")
    else:
        # Minimal fallback if python-dotenv isn't installed for some reason
        lines = []
        replaced = False
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{ENV_VAR}="):
                    lines.append(f"{ENV_VAR}={value}")
                    replaced = True
                else:
                    lines.append(line)
        if not replaced:
            lines.append(f"{ENV_VAR}={value}")
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # keep the current process' env in sync too
    import os
    os.environ[ENV_VAR] = value


def get_all_keys() -> list[str]:
    """
    Returns all configured Gemini keys (up to 5), read from .env.
    """
    return _read_env_keys()[:MAX_KEYS]


def set_all_keys(keys: list[str]) -> None:
    """
    Persists up to 5 Gemini keys to .env (GEMINI_API_KEYS=key1,key2,...).
    Resets rotation state (fresh keys deserve a clean slate).
    """
    cleaned = []
    for k in keys:
        k = (k or "").strip()
        if k and k not in cleaned:
            cleaned.append(k)
    cleaned = cleaned[:MAX_KEYS]

    _write_env_keys(cleaned)

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
