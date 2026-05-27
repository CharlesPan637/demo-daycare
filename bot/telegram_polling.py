"""Standalone Telegram polling runner for container startup."""

import logging
import time

from app import TELEGRAM_AVAILABLE, TOKEN, run_telegram_bot

logger = logging.getLogger(__name__)


def main() -> None:
    token_valid = TELEGRAM_AVAILABLE and TOKEN and TOKEN != "placeholder" and not TOKEN.startswith("placeholder")
    if token_valid:
        run_telegram_bot()
        return

    logger.warning("Telegram bot not started (no valid token).")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
