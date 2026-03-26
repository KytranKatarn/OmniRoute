"""KBS Background Worker — processes async events and scheduled jobs."""
import os
import sys
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("kbs.worker")


def main():
    logger.info("KBS Worker starting...")
    # Placeholder — will add Redis queue consumer and APScheduler in Phase 2
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
