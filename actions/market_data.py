#market_data.py
"""
market_data.py — stock/index price checks, market statistics, and
educational investment-direction discussion.

Mirrors actions/web_search.py's DDG-primary / Gemini-enhance pattern so it
shares the same reliability characteristics (DDG quota is cheap and large,
Gemini enhance is best-effort and always has a raw-text fallback).

This is a separate, explicit, on-demand tool — distinct from
actions/background_monitor.py's passive daily topic-watcher, which
deliberately blocks crypto/finance topics. That block is untouched and
intentional; this module only ever runs when the user directly asks.

Every 'suggest' response ends with a short not-financial-advice
disclaimer — this tool is informational/educational only, never a
licensed recommendation or trade execution.
"""
from actions.web_search import _ddg_search, _enhance_or_raw, _format_ddg


_DISCLAIMER = (
    "\n\n(This is general market information, not licensed financial advice — "
    "please do your own research or consult a financial advisor before investing.)"
)


def _quote(query: str) -> str:
    """Single stock / index price lookup."""
    results = _ddg_search(f"{query} stock price today", max_results=6)
    raw = _format_ddg(query, results)
    return _enhance_or_raw(
        query, raw,
        "Extract and clearly state the current price, today's change (amount and %), "
        "and the exchange/ticker if visible.",
    )


def _stats(query: str) -> str:
    """Broad market statistics — major indices snapshot."""
    topic = query.strip() or "stock market today Nifty Sensex Dow Jones S&P 500 Nasdaq"
    results = _ddg_search(f"{topic} market today indices", max_results=8)
    raw = _format_ddg(topic, results)
    return _enhance_or_raw(
        topic, raw,
        "Summarise today's overall market picture: key indices and their moves, "
        "sectors that are up or down, and the general sentiment (bullish/bearish/mixed). "
        "Be concise and organised.",
    )


def _suggest(query: str) -> str:
    """Educational investment-direction discussion — never a specific buy/sell order."""
    topic = query.strip() or "where to invest right now"
    results = _ddg_search(f"{topic} investment outlook analysis", max_results=8)
    raw = _format_ddg(topic, results)
    body = _enhance_or_raw(
        topic, raw,
        "Discuss investment directions/sectors/asset classes relevant to this query in an "
        "educational way: what's being discussed, the general reasoning, and the key risks. "
        "Present it as informational context, not a personal recommendation. "
        "Do not tell the user to buy or sell a specific security.",
    )
    return body + _DISCLAIMER


def market_data(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query = params.get("query", "").strip()
    mode  = params.get("mode", "quote").lower().strip()

    if player:
        player.write_log(f"[Market:{mode}] {query}")

    print(f"[MarketData] 📈 mode={mode!r}  query={query!r}")

    try:
        if mode == "stats":
            return _stats(query)
        if mode == "suggest":
            return _suggest(query)
        if not query:
            return "Please specify a stock, index, or ticker to check."
        return _quote(query)
    except Exception as e:
        print(f"[MarketData] ❌ Failed: {e}")
        return f"Market data lookup failed: {e}"
