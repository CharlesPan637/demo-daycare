#!/usr/bin/env python3
"""Verify Telegram command access guard patterns in bot/app.py."""

from pathlib import Path
import re
import sys


APP_PATH = Path(__file__).resolve().parents[1] / "bot" / "app.py"
SOURCE = APP_PATH.read_text(encoding="utf-8")


def command_body(command_function: str) -> str:
    pattern = re.compile(rf"^async def {re.escape(command_function)}\(", re.MULTILINE)
    match = pattern.search(SOURCE)
    if not match:
        return ""
    start = match.start()
    rest = SOURCE[start:]
    next_match = re.search(r"^async def [a-zA-Z0-9_]+\(", rest[1:], flags=re.MULTILINE)
    if not next_match:
        return rest
    return rest[: next_match.start() + 1]


EXPECTATIONS = {
    "activity_cmd": ["_require_staff(update)"],
    "checkin_cmd": ["_require_staff(update)"],
    "checkout_cmd": ["_require_staff(update)"],
    "observe_cmd": ["_require_staff(update)"],
    "staffing_cmd": ["_require_staff(update)"],
    "callout_cmd": ["_require_staff(update)"],
    "subsidies_cmd": ["_require_staff(update)"],
    "forecast_cmd": ["_require_staff(update)"],
    "health_cmd": ["_require_staff(update)"],
    "moment_cmd": ["_require_staff(update)"],
    "schedule_cmd": ["_require_staff(update)"],
    "announce_cmd": ["_require_staff(update)"],
    "logmenu_cmd": ["_require_staff(update)"],
    "setschedule_cmd": ["_require_staff(update)"],
    "addsub_cmd": ["_require_staff(update)"],
    "substitutes_cmd": ["_require_staff(update)"],
    "report_cmd": ["_require_child_access(update, child)"],
    "milestones_cmd": ["_require_child_access(update, child)"],
    "vaccines_cmd": ["_require_child_access(update, child)", "_require_staff(update)"],
    "portfolio_cmd": ["_require_child_access(update, child)"],
    "book_cmd": ["_require_child_access(update, child)", "_is_staff(chat_id)"],
    "meetings_cmd": ["_is_staff(chat_id)", "_linked_children_for_chat(chat_id)", 'meeting_type="parent_teacher"'],
    "ask_cmd": ["restricted_dashboard_keys", "not _is_staff(chat_id)"],
    "fallback": ["_require_child_access(update, child)"],
    "button_callback": ["_require_child_access(update, child)"],
}


def main() -> int:
    failures: list[str] = []
    for fn_name, required_snippets in EXPECTATIONS.items():
        body = command_body(fn_name)
        if not body:
            failures.append(f"{fn_name}: function not found")
            continue
        for snippet in required_snippets:
            if snippet not in body:
                failures.append(f"{fn_name}: missing snippet `{snippet}`")

    if failures:
        print("ACCESS MATRIX VERIFICATION FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("ACCESS MATRIX VERIFICATION OK")
    print(f"Checked {len(EXPECTATIONS)} command handlers in {APP_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
