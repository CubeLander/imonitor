# Ascend Smoke 使用说明

## 1. 运行 vLLM smoke（默认双卡）

```bash
/home/user8/workspace/imonitor/msprof-docs-processed/ascend/run_vllm_smoke.sh
```

可选参数示例：

```bash
SMOKE_VISIBLE_DEVICES=4,5 SMOKE_TP=2 CONTAINER_NAME=vllm-hust3 \
  /home/user8/workspace/imonitor/msprof-docs-processed/ascend/run_vllm_smoke.sh
```

## 2. 运行 msprof + vLLM smoke（默认双卡）

```bash
/home/user8/workspace/imonitor/msprof-docs-processed/ascend/run_msprof_vllm_smoke.sh
```

可选参数示例：

```bash
SMOKE_VISIBLE_DEVICES=4,5 SMOKE_TP=2 MSPROF_TIMEOUT_SECONDS=1200 CONTAINER_NAME=vllm-hust3 \
  /home/user8/workspace/imonitor/msprof-docs-processed/ascend/run_msprof_vllm_smoke.sh
```

说明：如仅需 analyzer 消费的原始库，建议加 `MSPROF_TYPE=db`（默认已是 `db`），可显著减少导出时间与体积。

目标入口可独立指定（与 msprof 开关解耦）：

```bash
TARGET_PROGRAM=python3 TARGET_SCRIPT=/path/in/container/target.py TARGET_ARGS="--foo bar" \
  /home/user8/workspace/imonitor/msprof-docs-processed/ascend/run_msprof_vllm_smoke.sh
```

也支持直接给完整命令：

```bash
TARGET_COMMAND="python3 /path/in/container/target.py --foo bar" \
  /home/user8/workspace/imonitor/msprof-docs-processed/ascend/run_msprof_vllm_smoke.sh
```

可显式指定输出根和 run_id（用于固定目录布局）：

```bash
OUT_BASE=/some/out/root RUN_ID=msprof_raw \
  /home/user8/workspace/imonitor/msprof-docs-processed/ascend/run_msprof_vllm_smoke.sh
```

### 2.1 稳定导出 2x2（推荐先用）

这个脚本固定 `tp=2, pp=2`，并关闭重型采集项，优先保证 `msprof_*.db` 稳定导出：

```bash
CONTAINER_NAME=vllm-cyj \
  /home/user8/workspace/imonitor/msprof-docs-processed/ascend/run_msprof_vllm_2x2_stable.sh
```

可选参数示例（手动指定 4 张卡）：

```bash
CONTAINER_NAME=vllm-cyj SMOKE_VISIBLE_DEVICES=4,5,6,7 \
  /home/user8/workspace/imonitor/msprof-docs-processed/ascend/run_msprof_vllm_2x2_stable.sh
```

## 3. 生成总览报告

```bash
python3 /home/user8/workspace/imonitor/msprof-docs-processed/ascend/generate_smoke_report.py \
  --ascend-dir /home/user8/workspace/imonitor/msprof-docs-processed/ascend \
  --report /home/user8/workspace/imonitor/msprof-docs-processed/ascend/out/report.md
```

## 4. 解析某次 msprof 结果（高价值指标）

按 latest 自动解析：

```bash
python3 /home/user8/workspace/imonitor/msprof-docs-processed/ascend/analyze_msprof_output.py \
  --ascend-dir /home/user8/workspace/imonitor/msprof-docs-processed/ascend
```

指定 run 解析：

```bash
python3 /home/user8/workspace/imonitor/msprof-docs-processed/ascend/analyze_msprof_output.py \
  --ascend-dir /home/user8/workspace/imonitor/msprof-docs-processed/ascend \
  --run-dir /home/user8/workspace/imonitor/msprof-docs-processed/ascend/out/msprof_smoke/<run_id>
```

解析报告会写到：

- `<run_dir>/analysis.md`

## 5. 重点看什么

- `Top 算子耗时（op_statistic）`：先定位最耗时 OP Type。
- `Top API 耗时（api_statistic）`：看 Host/Runtime 开销热点。
- `通信开销（communication_statistic）`：判断是否被 `hcom_*` 主导。
- `AI Core 利用率均值`：快速看算力利用是否偏低。
- `L2 与内存`：看 L2 命中与组件内存峰值（`APP/HCCL/RUNTIME`）。
