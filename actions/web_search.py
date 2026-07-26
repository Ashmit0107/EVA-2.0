#web_search.py
import json
import sys
from pathlib import Path

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _gemini_enhance(prompt: str) -> str:
    """
    Plain-text Gemini call — NO google_search grounding tool.
    This draws from the normal text-generation quota, which is separate from
    (and much larger than) the grounded-search quota that gets exhausted fast.
    Used to synthesise/clean up DDG results into a readable answer — never as
    the primary data source, so a quota hit here just means slightly rougher
    formatting, not a failed search.
    """
    from google import genai
    from core.gemini_keys import call_with_rotation

    def _do(api_key: str) -> str:
        client   = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
        )
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            raise ValueError("Gemini returned an empty response.")
        return text

    return call_with_rotation(_do)


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title":   r.get("title",  ""),
                "snippet": r.get("body",   ""),
                "url":     r.get("href",   ""),
            })
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """DDG news search — returns actual articles, not website homepages."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("url",    ""),
                    "source":  r.get("source", ""),
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG news() failed ({e}) — falling back to text search")
        results = _ddg_search(query, max_results=max_results)
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"No news found for: {query}"

    lines = [f"Latest news: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        src = f"  [{r['source']}]" if r.get("source") else ""
        lines.append(f"{i}. {title}{src}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:140]}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _enhance_or_raw(query: str, raw_text: str, instruction: str) -> str:
    """
    Tries to have Gemini rewrite/synthesise raw_text per `instruction`.
    On ANY failure (quota, network, empty), silently returns raw_text as-is —
    DDG's own result is always a valid answer on its own.
    """
    if not raw_text or raw_text.startswith("No results") or raw_text.startswith("No news"):
        return raw_text
    try:
        prompt = (
            f"{instruction}\n\n"
            f"Query: {query}\n\n"
            f"Raw search results:\n{raw_text}\n\n"
            "Write a clear, well-organised answer using ONLY the facts above. "
            "Do not invent information not present in the results."
        )
        return _gemini_enhance(prompt)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Gemini enhance skipped ({e}) — using raw DDG result")
        return raw_text


# ── Briefing helper ────────────────────────────────────────────────────────────

def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """
    Fetches current headlines. DDG news is the primary source; Gemini (plain
    text, no grounding tool) just reformats into a clean numbered list.
    Returns (headline_list, raw_text_for_display).
    """
    import re

    results = _ddg_news("top world news today", max_results=n)
    raw_ddg = _format_news("top world news today", results)

    raw = _enhance_or_raw(
        "top world news today",
        raw_ddg,
        f"Extract exactly {n} distinct headlines from these results.",
    )

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Only accept lines that begin with a number — skips preamble/closing sentences
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*',          '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    if not headlines:
        # Enhancement didn't produce a numbered list (or was skipped) —
        # fall back to titles straight from the DDG results.
        headlines = [r["title"] for r in results if r.get("title")][:n]

    return headlines[:n], raw.strip()


# ── Modes ──────────────────────────────────────────────────────────────────────

def _search(query: str) -> str:
    """Default search — DDG primary, Gemini reformats when available."""
    results = _ddg_search(query)
    raw = _format_ddg(query, results)
    return _enhance_or_raw(query, raw, "Answer the user's query directly and concisely.")


def _news(query: str) -> str:
    """News — DDG primary, Gemini reformats when available."""
    ddg_query = query if query else "world news today"
    results = _ddg_news(ddg_query, max_results=8)
    raw = _format_news(ddg_query, results)
    return _enhance_or_raw(ddg_query, raw, "Summarise the latest news on this topic.")


def _research(query: str) -> str:
    """Deep dive — wider DDG fetch, Gemini synthesises when available."""
    results = _ddg_search(query, max_results=10)
    raw = _format_ddg(query, results)
    return _enhance_or_raw(
        query, raw,
        "Give a comprehensive, detailed explanation including background context, "
        "key facts, current state, and important nuances.",
    )


def _price(query: str) -> str:
    """Product price lookup — DDG primary, Gemini reformats when available."""
    results = _ddg_search(f"{query} price buy", max_results=6)
    raw = _format_ddg(query, results)
    return _enhance_or_raw(query, raw, "Extract and state the current market price clearly.")


def _compare(items: list[str], aspect: str) -> str:
    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    raw = "\n".join(lines)

    query = f"{', '.join(items)} — {aspect}"
    return _enhance_or_raw(
        query, raw,
        f"Compare {', '.join(items)} in terms of {aspect}. Give specific facts and data, "
        "organised per item.",
    )


# ── Public entry point ─────────────────────────────────────────────────────────

def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"

    if player:
        player.write_log(f"[Search:{mode}] {query or ', '.join(items)}")

    print(f"[WebSearch] 🔍 mode={mode!r}  query={query!r}")

    try:
        if mode == "compare" and items:
            return _compare(items, aspect)
        if mode == "news":
            return _news(query)
        if mode == "research":
            return _research(query)
        if mode == "price":
            return _price(query)
        return _search(query)

    except Exception as e:
        print(f"[WebSearch] ❌ All backends failed: {e}")
        return f"Search failed: {e}"
