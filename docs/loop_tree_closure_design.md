# Loop Tree 闭环设计（v0.1）

## 1. 背景与目标

当前最有价值产物是 `loop_analyzer` 生成的可读树（`*.tree.readable.md`），已经能让人快速识别一个 stream 的执行阶段。

下一阶段目标是把它升级为可查询、可归因、可落地优化的完整闭环：

1. 结构化表示：不仅“看得懂”，还要能按节点/子树做统计。
2. 性能归因：每个子树都有时间窗、利用率、等待占比、跨 stream 关系。
3. 源码映射：把子树映射到可能的源码位置，形成可执行优化建议。

## 2. 闭环范围

从 `可视化` 升级为 `结构 + 统计 + 代码` 三位一体：

1. Trace -> Loop Tree
2. Loop Tree -> Subtree Perf
3. Subtree Perf -> Source Mapping
4. Source Mapping -> 优化动作与回归验证

## 3. 核心数据模型

### 3.1 NodeTemplate（结构层）

记录树结构，不绑定具体发生时刻。

字段建议：

- `node_id`
- `parent_id`
- `ord`（兄弟顺序）
- `node_type`（`Atom` / `Repeat` / `MacroRef` / `Seq`）
- `label`
- `repeat_count`
- `macro_name`

### 3.2 NodeInstance（时序层）

记录节点每次实际出现的时间窗。

字段建议：

- `instance_id`
- `node_id`
- `occ_idx`
- `device_id`
- `stream_id`
- `start_ns`
- `end_ns`
- `dur_ns`

### 3.3 NodePerf（统计层）

记录节点/子树性能统计。

字段建议：

- `scope`（`node` / `instance`）
- `scope_id`
- `exec_ns`
- `comm_ns`
- `wait_ns`
- `idle_ns`
- `wait_ratio`
- `npu_util_avg`
- `overlap_stream_topk`

### 3.4 NodeSourceLink（代码映射层）

记录子树到源码的候选映射及证据。

字段建议：

- `scope_id`
- `module`
- `file`
- `line_start`
- `line_end`
- `function`
- `confidence`（`high` / `medium` / `low`）
- `evidence_kind`（op 名命中、custom kernel 命中、调用栈邻近、launch 邻近等）
- `evidence_text`
- `needs_review`

## 4. 指标口径（统一定义）

1. `timespan`: 节点（或子树）窗口，`Repeat` 保留每次 occurrence。
2. `wait_ratio`: 窗口内 wait 时间 / 窗口总时间。
3. `npu_util_avg`: 窗口内 exec union time / 窗口总时间。
4. `stream_overlap`: 窗口内其他 stream 的活跃重叠覆盖率（top-k）。
5. `queue_delay`（后续）：API submit 到 stream task start 的延迟。

## 5. loop_source_mapper skill 设计

定位：半自动证据驱动映射，不允许“无证据硬猜”。

输入：

- `*.tree.v2.json`
- `*.symbols.csv`
- `*.macros.csv`
- 子树/节点时间窗
- 代码仓（vllm 与业务代码）

输出：

- `node_source_links.json`
- `source_annotated_report.md`

流程：

1. 规则候选检索：按 op/kernel 名、函数名、模块名、launch 邻近位置生成候选。
2. LLM 重排归因：结合上下文对候选排序并解释证据。
3. 置信度打标：每条结果必须包含 `confidence + evidence`。
4. 人工复核位：`low` 置信度默认 `needs_review=true`。

## 6. 里程碑

1. M1（先做）：`node_instances.csv` + `node_perf.csv` + `subtree_report.md`。
2. M2：支持跨 stream 关联统计（重叠、同步、等待传播）。
3. M3：接入 `loop_source_mapper` 产出源码注释报告。
4. M4：支持多卡对比（0/1/4/5）与瓶颈聚类。

## 7. 产物清单（目标）

- `tree.v2.json`（结构）
- `tree.readable.md`（阅读）
- `node_instances.csv`（发生时序）
- `node_perf.csv`（性能）
- `node_source_links.json`（映射证据）
- `subtree_report.md`（闭环报告）

## 8. 仓库清理原则

- 删除探索期遗留脚本与补丁目录（例如根目录 `scripts/`、`patches/`）。
- 保留当前主流程必需脚本（例如 `analyzer/scripts/run_hprofile_smoke.sh`）。
- 历史实验结果保留在 `develop/` 与 `analyzer/out/`，作为证据样本。
