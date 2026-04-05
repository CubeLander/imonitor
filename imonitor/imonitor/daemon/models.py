from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunStartRequest(BaseModel):
    run_id: str
    command: list[str]
    start_ns: int
    interval_sec: float
    root_pid: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawRow(BaseModel):
    run_id: str
    ts_ns: int
    sensor: str
    metric: str
    value: float
    unit: str
    pid: int | None = None
    tags_json: str | None = None


class SignalBatch(BaseModel):
    rows: list[RawRow] = Field(default_factory=list)


class LogChunk(BaseModel):
    ts_ns: int
    text: str
    stream: str = "combined"


class LogBatch(BaseModel):
    chunks: list[LogChunk] = Field(default_factory=list)


class RunRow(BaseModel):
    run_id: str
    command: str
    start_ns: int
    end_ns: int
    duration_sec: float
    exit_code: int
    interval_sec: float
    sample_count: int
    peak_total_cpu_pct: float
    peak_total_rss_bytes: float
    status: str = "completed"


class ProcessRow(BaseModel):
    run_id: str
    pid: int
    comm: str | None = None
    first_seen_ns: int
    last_seen_ns: int


class AggRow(BaseModel):
    run_id: str
    sensor: str
    metric: str
    pid: int | None = None
    unit: str
    sample_count: int
    min: float
    max: float
    avg: float
    last: float


class FrameRow(BaseModel):
    run_id: str
    frame_id: int
    ts_ns: int
    signal_count: int
    active_pids: int


class RollupRow(BaseModel):
    run_id: str
    sensor: str
    metric: str
    pid: int | None = None
    unit: str
    bucket_ns: int
    bucket_start_ns: int
    sample_count: int
    min: float
    max: float
    avg: float
    p95: float
    last: float


class RunFinishRequest(BaseModel):
    run_row: RunRow
    process_rows: list[ProcessRow] = Field(default_factory=list)
    agg_rows: list[AggRow] = Field(default_factory=list)
    frame_rows: list[FrameRow] = Field(default_factory=list)
    rollup_rows: list[RollupRow] = Field(default_factory=list)


class SQLQueryRequest(BaseModel):
    sql: str
    params: list[Any] = Field(default_factory=list)
    limit: int = Field(default=1000, ge=1, le=10000)
