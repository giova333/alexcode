"""Daily memory file management."""

from __future__ import annotations

from datetime import date
from pathlib import Path


class DailyMemory:
    """Creates and appends to daily memory files: memory/daily/YYYY-MM-DD.md."""

    def __init__(self, daily_dir: str, base_dir: Path) -> None:
        self._daily_dir = base_dir / daily_dir

    def _today_path(self) -> Path:
        return self._daily_dir / f"{date.today().isoformat()}.md"

    def append(self, entry: str) -> None:
        """Append a timestamped entry to today's daily file."""
        from datetime import datetime

        path = self._today_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"\n## {timestamp}\n{entry}\n"

        if path.exists():
            content = path.read_text()
            path.write_text(content + formatted)
        else:
            header = f"# Daily Notes — {date.today().isoformat()}\n"
            path.write_text(header + formatted)

    def read_today(self) -> str:
        """Read today's daily file."""
        path = self._today_path()
        if path.exists():
            return path.read_text()
        return ""

    def read_date(self, dt: date) -> str:
        """Read a specific date's daily file."""
        path = self._daily_dir / f"{dt.isoformat()}.md"
        if path.exists():
            return path.read_text()
        return ""

    def read_recent(self, days: int = 2) -> list[tuple[date, str]]:
        """Read the last N days of daily files (today included)."""
        from datetime import timedelta

        results = []
        today = date.today()
        for i in range(days):
            dt = today - timedelta(days=i)
            content = self.read_date(dt)
            if content:
                results.append((dt, content))
        return results

    def list_dates(self) -> list[str]:
        """List available daily file dates."""
        if not self._daily_dir.exists():
            return []
        return sorted(
            [p.stem for p in self._daily_dir.glob("*.md")],
            reverse=True,
        )
