# analyzer

`analyzer/msprof_stage_analyzer.py` 是第一版 `msprof` 时间线分析器，目标是把 `TASK` 级时间线转成便于后续 AI 报告生成的结构化结果。

## hprofile（新入口）

`analyzer/hprofile` 是新的 augmentation bundle 入口（最终命名方向）。它会复用现有 stage analyzer 结果，产出：

- `derived/unified_profile.json`
- `derived/lineage.json`
- `derived/quality_report.json`
- `web/index.html + assets/*`（静态离线可打开）
- `manifest.json`

运行示例：

```bash
cp analyzer/hprofile/profile.default.yaml ./hprofile.yaml
python3 -m analyzer.hprofile
```

仅处理已有 raw：

```bash
cp analyzer/hprofile/process.default.yaml ./hprofile.process.yaml
python3 -m analyzer.hprofile process
```

帮助：

```bash
python3 -m analyzer.hprofile --help
```

标准化 vLLM distributed smoke（一键 collect + process + web）：

```bash
analyzer/scripts/run_hprofile_smoke.sh
```

可选覆盖 workload 参数（保持 hprofile 配置不改）：

```bash
VLLM_SMOKE_MODEL=/data/models/... \
VLLM_SMOKE_TP=8 VLLM_SMOKE_PP=1 \
VLLM_SMOKE_MAX_TOKENS=64 \
CONTAINER_NAME=train8-docker \
analyzer/scripts/run_hprofile_smoke.sh
```

新链路文件：

- 配置：[analyzer/config/hprofile.yaml](/home/user8/workspace/imonitor/analyzer/config/hprofile.yaml)
- 采集入口：`analyzer/hprofile/collect_target.py`（hprofile 内置采集器）
- 负载脚本：[vllm_distributed_smoke.py](/home/user8/workspace/imonitor/analyzer/workload/vllm_distributed_smoke.py)
- 一键启动：[run_hprofile_smoke.sh](/home/user8/workspace/imonitor/analyzer/scripts/run_hprofile_smoke.sh)

说明：该组合不依赖 `msprof-docs-processed/ascend/*` 旧 smoke 脚本，hprofile 只消费通用 `target/msprof/profiler` 配置。
采集参数以 `analyzer/config/hprofile.yaml` 为单一配置源；内置采集器只负责执行，不再维护第二套参数默认值。
其中模型路径等 workload 参数位于 `target.env`（例如 `VLLM_SMOKE_MODEL`），不再放在 target 顶层字段。

默认配置样例：

- [profile.default.yaml](/home/user8/workspace/imonitor/analyzer/hprofile/profile.default.yaml)

说明：`hprofile` v2 配置分为 `target / msprof / profiler` 三段。`profiler` 阶段是采集后的交付打包（raw -> derived/web/manifest），不是目标启动阶段。

原始 msprof 产物说明书：

- [MSPROF_RAW_ARTIFACTS.md](/home/user8/workspace/imonitor/analyzer/MSPROF_RAW_ARTIFACTS.md)

当前版本能力：

1. 自动定位并聚合包含 `TASK` 表的 `msprof_*.db`（`run-dir` 下全部 `PROF_*/msprof_*.db`）。
2. 对任务按 `wait / comm / exec / other` 分类，并将 `wait` 拆分为：
   - `comm_wait`
   - `sync_wait`
   - `unknown_wait`
3. 统计全局、按 `stream`、按粗粒度 `model_exec` 阶段的占比与时间线气泡：
   - `total_task_us`
   - `span_us`
   - `idle_gap_us`
   - `idle_ratio_span`
4. 基于 `EVENT_WAIT -> EVENT_RECORD` 的时间配对，统计跨 stream 因果等待边：
   - 哪个 `producer_stream` 经常唤醒哪个 `consumer_stream`
   - 对应 `EVENT_WAIT` 的总等待时间、占比和 p95
   - `wait_end - record_end` 的解阻延迟分布
5. 在热点 stream 上挖掘重复 micro-loop 候选，并输出 loop 步骤平均耗时与步间等待。

## 运行方法

默认直接分析仓库里的 `latest`：

```bash
python3 analyzer/msprof_stage_analyzer.py
```

说明：默认会聚合该 run 下的所有 `msprof_*.db`。如果只想分析单个库，使用 `--db`。

指定 run 目录：

```bash
python3 analyzer/msprof_stage_analyzer.py \
  --run-dir msprof-docs-processed/ascend/out/msprof_smoke/20260414_163910 \
  --out-dir analyzer/out/20260414_163910
```

直接指定 DB：

```bash
python3 analyzer/msprof_stage_analyzer.py \
  --db msprof-docs-processed/ascend/out/msprof_smoke/20260414_163910/PROF_xxx/msprof_xxx.db \
  --out-dir analyzer/out/manual_db
```

## 输出文件

- `summary.md`: 人读摘要。
- `meta.json`: 本次分析元信息。
- `global_breakdown.csv`: 全局占比。
- `stream_breakdown.csv`: 每个 stream 的 `wait/comm/exec/other` 占比。
- `phase_stream_breakdown.csv`: 粗粒度阶段（由 `MODEL_EXECUTE` 自动合并）下的 stream 占比与 `idle_gap`。
- `stream_causality_edges.csv`: `EVENT_WAIT -> EVENT_RECORD` 推断的 producer/consumer stream 因果边统计。
- `stream_causality_meta.json`: 因果配对覆盖率、跨流占比、配对窗口参数等元信息。
- `task_type_breakdown.csv`: 每个 `task_type` 被归类到哪个 bucket（含 `wait_kind`）的汇总。
- `classification_rules.md`: 分类规则说明（显式写明哪些事件会被统计到哪里）。
- `top_kernels.csv`: `exec` 类热点 kernel。
- `loop_candidates.csv`: micro-loop 候选列表。
- `loop_best.json`: 覆盖时间最高 loop 的步骤级统计（每步平均耗时、步间等待）。

## 说明

- 第一版阶段划分是“无侵入”的：基于 `MODEL_EXECUTE` 合并窗口。
- 因果边是时间线启发式推断，不是 runtime 显式依赖表；建议结合 `stream_causality_meta.json` 的匹配率一起解读。
- 后续接入 vLLM 内部显式阶段标记（例如 `prefill/decode step`）后，可以把 `phase_stream_breakdown.csv` 的 phase 粒度升级成业务语义阶段。
