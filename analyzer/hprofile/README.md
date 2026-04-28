# hprofile

`hprofile` 是 msprof 采集与处理入口。

## 命令入口

1. 启动采集并处理（隐式 start）：
```bash
cp analyzer/hprofile/profile.default.yaml ./hprofile.yaml
python3 -m analyzer.hprofile
```

2. 仅处理已有 raw：
```bash
cp analyzer/hprofile/process.default.yaml ./hprofile.process.yaml
python3 -m analyzer.hprofile process
```

3. 查看帮助：
```bash
python3 -m analyzer.hprofile --help
```

推荐的一键 smoke（标准化 distributed workload 组合）：
```bash
analyzer/scripts/run_hprofile_smoke.sh
```

按需覆盖 workload 参数：
```bash
VLLM_SMOKE_TP=8 VLLM_SMOKE_PP=1 CONTAINER_NAME=train8-docker \
analyzer/scripts/run_hprofile_smoke.sh
```

## 配置分层（v2）

1. `target`：目标程序及启动参数（容器配置也在这里）。
2. `msprof`：观测参数。
3. `profiler`：产物路径、run_tag、process_only 处理参数。

约定：`target.entry_script` 为空时，使用 hprofile 内置采集器；workload 参数放在 `target.env`（如 `VLLM_SMOKE_MODEL`）。

推荐配置文件位置：

- [analyzer/config/hprofile.yaml](/home/user8/workspace/imonitor/analyzer/config/hprofile.yaml)
- `analyzer/hprofile/collect_target.py`（内置采集器，参数来源为配置映射后的环境变量）

## 固定产物布局

每次 run 固定输出：

- `out/<run_tag>/msprof_raw`
- `out/<run_tag>/hprofile_processed`

`hprofile_processed` 下包含：

- `derived/unified_profile.json`
- `derived/lineage.json`
- `derived/quality_report.json`
- `derived/loop_analyzer/*`（stream trace 压缩表达式与带时间窗的树）
- `web/index.html + assets/*`
- `manifest.json`

`loop_analyzer` 默认开启，可在 `profiler.loop_analyzer` 调整：

```yaml
profiler:
  loop_analyzer:
    enabled: true
    top_streams_per_db: 3
    max_events_per_stream: 20000
    max_period: 12
    min_repeat_count: 2
```

## Loop Tree 离线增广（不重跑 workload）

基于现有 `derived/loop_analyzer/*.tree.v2.json` 直接做节点级聚合统计：

```bash
python3 -m analyzer.hprofile.loop_analyzer.augment \
  analyzer/out/<run_tag>/hprofile_processed/derived/loop_analyzer/dbXX_rankXX_devX_streamXXXX.tree.v2.json
```

目录批量处理时，可先按工作量筛选重点 stream：

```bash
python3 -m analyzer.hprofile.loop_analyzer.augment \
  analyzer/out/<run_tag>/hprofile_processed/derived/loop_analyzer \
  --top-streams-by-total-dur 8
```

可选源码注释文件（用于覆盖自动推断的源码锚点）：

```bash
python3 -m analyzer.hprofile.loop_analyzer.augment \
  analyzer/out/<run_tag>/hprofile_processed/derived/loop_analyzer/dbXX_rankXX_devX_streamXXXX.tree.v2.json \
  --source-notes /path/to/source_notes.json
```

`source_notes.json` 结构示例：

```json
{
  "task_label": {
    "AddRmsNormBias": "vllm/model_executor/layers/layernorm.py:120"
  },
  "node": {
    "Root[73].body[1]": "vllm/worker/model_runner.py:450"
  }
}
```

输出（同目录）：

- `*.node_perf_core.csv`：通用聚合指标（按节点路径）
- `*.node_perf_detail.jsonl`：按节点类型的专属指标
- `*.node_instances.csv`：节点实例窗口明细
- `*.macro_summary.csv`：macro 级别平均性能统计
- `*.macro_steps.csv`：macro 内部步骤纵向聚合
- `*.tree.readable.augmented.md`：带关键指标的增广报告

其中增广报告和 CSV 均包含 `source_deepest` 字段，表示当前能追溯到的 Python/框架侧调用锚点（自动推断，可被 `source_notes` 覆盖）；对容器（Block）节点，会优先做子节点锚点的公共祖先（LCA）归并。

## 兼容策略

- `collect.preset` 仍保留兼容（deprecated），内部会映射到通用入口脚本与默认参数。
- `collect.smoke` 仍可读取（deprecated），建议迁移到 `target.env`。
- `collect.out_root / collect.run_tag` 仍可读取（deprecated），建议迁移到 `profiler.out_root / profiler.run_tag`。
- 迁移完成后将移除 `collect.*` 兼容字段，统一到 `target / msprof / profiler`。
