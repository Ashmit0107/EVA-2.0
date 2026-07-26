"""
EVA task list / agenda + quick notes.

Two lightweight JSON-backed stores under memory/:
  - memory/tasks.json  — a running to-do list (add/list/complete/delete)
  - memory/notes.json  — short free-form notes the user asks EVA to remember

Both are simple local stores (no external services) so they work fully
offline and stay in sync with EVA's existing memory/ folder conventions.
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _tasks_path() -> Path:
    return _base_dir() / "memory" / "tasks.json"


def _notes_path() -> Path:
    return _base_dir() / "memory" / "notes.json"


def _load(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(path: Path, items: list) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Tasks] ⚠️ Could not save {path.name}: {e}")


# ── Tasks / agenda ────────────────────────────────────────────────────────────

def _find_task(items: list, identifier: str) -> dict | None:
    for it in items:
        if it.get("id") == identifier:
            return it
    ident_lc = identifier.lower().strip()
    for it in items:
        if ident_lc in it.get("text", "").lower():
            return it
    return None


def manage_task(parameters: dict, player=None) -> str:
    action = (parameters.get("action") or "").strip().lower()
    items  = _load(_tasks_path())

    if action == "add_task":
        text = (parameters.get("text") or "").strip()
        if not text:
            return "What would you like me to add to the list?"
        due = (parameters.get("due") or "").strip()
        entry = {
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "due": due,
            "done": False,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        items.append(entry)
        _save(_tasks_path(), items)
        if player:
            player.write_log(f"[Task] ➕ {text}")
        due_str = f" (due {due})" if due else ""
        return f"Added to your list: {text}{due_str}."

    if action == "list_tasks":
        pending = [it for it in items if not it.get("done")]
        if not pending:
            return "Your to-do list is empty."
        lines = []
        for it in pending:
            due_str = f"  [due {it['due']}]" if it.get("due") else ""
            lines.append(f"- {it['text']}{due_str}  (id: {it['id']})")
        return "Your to-do list:\n" + "\n".join(lines)

    if action == "complete_task":
        identifier = (parameters.get("task_id") or parameters.get("query") or "").strip()
        if not identifier:
            return "Which task should I mark complete?"
        match = _find_task(items, identifier)
        if not match:
            return f"I couldn't find a task matching '{identifier}'."
        match["done"] = True
        match["completed_at"] = datetime.now().isoformat(timespec="seconds")
        _save(_tasks_path(), items)
        if player:
            player.write_log(f"[Task] ✅ {match['text']}")
        return f"Marked as done: {match['text']}."

    if action == "delete_task":
        identifier = (parameters.get("task_id") or parameters.get("query") or "").strip()
        if not identifier:
            return "Which task should I remove?"
        match = _find_task(items, identifier)
        if not match:
            return f"I couldn't find a task matching '{identifier}'."
        items = [it for it in items if it.get("id") != match["id"]]
        _save(_tasks_path(), items)
        if player:
            player.write_log(f"[Task] 🗑️ {match['text']}")
        return f"Removed from your list: {match['text']}."

    return "Specify an action: add_task, list_tasks, complete_task, or delete_task."


def pending_task_count() -> int:
    """Used by the morning briefing to mention how many open tasks exist."""
    items = _load(_tasks_path())
    return sum(1 for it in items if not it.get("done"))


# ── Quick notes ──────────────────────────────────────────────────────────────

def quick_note(parameters: dict, player=None) -> str:
    action = (parameters.get("action") or "add").strip().lower()
    items  = _load(_notes_path())

    if action == "list" or action == "search":
        query = (parameters.get("query") or "").strip().lower()
        matches = [it for it in items if not query or query in it.get("text", "").lower()]
        if not matches:
            return "No matching notes found." if query else "You have no saved notes."
        lines = [f"- {it['text']}  ({it['created_at'][:10]})" for it in matches]
        return "Notes:\n" + "\n".join(lines)

    text = (parameters.get("text") or "").strip()
    if not text:
        return "What would you like me to note down?"
    entry = {
        "id": uuid.uuid4().hex[:8],
        "text": text,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    items.append(entry)
    _save(_notes_path(), items)
    if player:
        player.write_log(f"[Note] 📝 {text[:60]}")
    return "Noted."
