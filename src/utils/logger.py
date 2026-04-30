import logging
from datetime import datetime
from typing import List, Optional


class Logger:
    def __init__(self, log_level: Optional[int] = logging.DEBUG):
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.logger = logging.getLogger(__name__)
        self.history: List[str] = []

    def _record(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.history.append(f"{timestamp} [{level}] {message}")
        getattr(self.logger, level.lower())(message)

    def debug(self, message: str) -> None:
        self._record("DEBUG", message)

    def warning(self, message: str) -> None:
        self._record("WARNING", message)

    def info(self, message: str) -> None:
        self._record("INFO", message)

    def error(self, message: str) -> None:
        self._record("ERROR", message)

    def end(self, message: str, is_error: bool = False) -> None:
        if is_error:
            self.error(message)
        else:
            self.info(message)

    def get_history_text(self) -> str:
        return "\n".join(self.history)
