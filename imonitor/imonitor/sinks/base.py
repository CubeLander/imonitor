from __future__ import annotations

from typing import Protocol


class Sink(Protocol):
    name: str

    def persist(
        self,
        run_row: dict[str, object],
        process_rows: list[dict[str, object]],
        raw_rows: list[dict[str, object]],
        agg_rows: list[dict[str, object]],
        frame_rows: list[dict[str, object]],
        rollup_rows: list[dict[str, object]],
    ) -> None:
        ...
