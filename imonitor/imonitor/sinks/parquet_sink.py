from __future__ import annotations

from pathlib import Path


class ParquetSink:
    name = "parquet"

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pyarrow is required for parquet sink") from exc

        self._pa = pa
        self._pq = pq

    @staticmethod
    def is_available() -> bool:
        try:
            import pyarrow  # noqa: F401

            return True
        except ImportError:
            return False

    def persist(
        self,
        run_row: dict[str, object],
        process_rows: list[dict[str, object]],
        raw_rows: list[dict[str, object]],
        agg_rows: list[dict[str, object]],
        frame_rows: list[dict[str, object]],
        rollup_rows: list[dict[str, object]],
    ) -> None:
        run_id = str(run_row["run_id"])
        self._write(self.out_dir / f"{run_id}_run.parquet", [run_row])
        self._write(self.out_dir / f"{run_id}_processes.parquet", process_rows)
        self._write(self.out_dir / f"{run_id}_metrics_raw.parquet", raw_rows)
        self._write(self.out_dir / f"{run_id}_metrics_agg.parquet", agg_rows)
        self._write(self.out_dir / f"{run_id}_frames.parquet", frame_rows)
        self._write(self.out_dir / f"{run_id}_metrics_rollup.parquet", rollup_rows)

    def _write(self, path: Path, rows: list[dict[str, object]]) -> None:
        if not rows:
            return
        table = self._pa.Table.from_pylist(rows)
        self._pq.write_table(table, path)
