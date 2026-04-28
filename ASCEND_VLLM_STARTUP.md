# Ascend vLLM 启动与 Smoke 手册（容器内执行）

> 说明（2026-04-23）：
> 根目录 `scripts/` 与 `patches/` 已作为探索期遗留内容清理。
> 本文中的脚本路径保留为历史记录，复现请优先使用 `analyzer/` 当前流程或参考 `develop/` 已落地产物。

本文档用于在**已配置好 vllm-ascend 的容器**里完成以下工作：

- 基线检查（CANN 8.5 / 8 张 NPU / msprof）
- vLLM on Ascend 启动
- vLLM TP/PP smoke
- msprof smoke（以 vLLM 为 workload）
- CANN 8.5 文档抓取为 Markdown

## 0. 前提

- 所有命令默认在容器内执行。
- 示例容器名：`vllm-workspace`
- 建议工作目录：`/workspace/imonitor`

进入容器：

```bash
docker exec -it vllm-workspace /bin/sh
cd /workspace/imonitor
```

## 1. 基线检查

```bash
python3 -V
npu-smi info
msprof --help | sed -n '1,80p'
python3 - <<'PY'
import torch, torch_npu, vllm
print('torch', torch.__version__)
print('torch_npu', torch_npu.__version__)
print('vllm', vllm.__version__)
print('npu_count', torch.npu.device_count())
PY
```

预期：

- `npu-smi info` 显示 8 张卡且 `Health=OK`
- `torch.npu.device_count()` 返回 `8`
- `msprof --help` 可正常输出参数列表

## 2. 启动 vLLM API 服务

8 卡示例：

```bash
VLLM_PLUGINS=ascend python3 -m vllm.entrypoints.openai.api_server \
  --model /data/models/Qwen3-32B-W4A4 \
  --served-model-name qwen3-32b-w4a4 \
  --host 0.0.0.0 \
  --port 18000 \
  --tensor-parallel-size 8 \
  --dtype bfloat16 \
  --max-model-len 4096
```

健康检查：

```bash
curl http://127.0.0.1:18000/v1/models
```

## 3. vLLM TP/PP Smoke

仓库脚本：`scripts/run_vllm_tp_pp_smoke_in_vllm_workspace.sh`

执行：

```bash
docker exec vllm-workspace /bin/sh -c '/workspace/imonitor/scripts/run_vllm_tp_pp_smoke_in_vllm_workspace.sh'
```

默认会跑两个 case：

- `tp2_pp1`（TP=2, PP=1）
- `tp2_pp2`（TP=2, PP=2）

结果目录：`develop/vllm_smoke_20260413`

## 4. msprof Smoke（vLLM workload）

仓库脚本：`scripts/run_msprof_smoke_in_vllm_workspace.sh`

执行：

```bash
docker exec vllm-workspace /bin/sh -c '/workspace/imonitor/scripts/run_msprof_smoke_in_vllm_workspace.sh'
```

默认会跑三个 case：

- `case1_app`：文档方式一 `msprof [options] <app>`
- `case2_application`：文档方式二 `msprof [options] --application=<app>`
- `case3_advanced`：高级参数组合（`--model-execution`、`--aic-mode`、`--aic-freq`、`--aic-metrics`、`--sys-hardware-mem`、`--sys-hardware-mem-freq`、`--l2`、`--ge-api`、`--task-memory`）

结果目录：`develop/msprof_smoke_runs_20260413`

## 5. 抓取 CANN 8.5 文档到 Markdown

抓取脚本：`scripts/crawl_cann850_docs.py`

msprof 子站点抓取（从 `atlasprofiling_16_0011.html` 出发）：

```bash
python3 -u scripts/crawl_cann850_docs.py \
  --start-url 'https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0011.html' \
  --max-pages 500 \
  --out-dir develop/cann850_docs_msprof \
  --sleep 0.01
```

全站入口抓取（850 文档入口）：

```bash
python3 -u scripts/crawl_cann850_docs.py \
  --start-url 'https://www.hiascend.com/document/detail/zh/canncommercial/850/index/index.html' \
  --max-pages 2500 \
  --out-dir develop/cann850_docs_full \
  --sleep 0.02
```

## 6. 关键产物

- `VLLM_ASCEND_SMOKE_REPORT_20260413.md`
- `develop/cann850_docs_msprof/INDEX.md`
- `develop/cann850_docs_msprof/markdown/devaids/Profiling/atlasprofiling_16_0011.md`
- `develop/msprof_smoke_runs_20260413/logs/*.log`
- `develop/vllm_smoke_20260413/logs/*.log`

## 7. 常见问题

### 7.1 `Cannot find any model weights`

模型目录里没有真实权重（`*.safetensors` / `*.bin`），请替换为实际 snapshot 路径。

### 7.2 `Engine core proc EngineCore died unexpectedly`

在单次离线 smoke 中，生成完成后引擎退出阶段可能出现该日志；若脚本 `exit_code.txt` 为 `0` 且已输出文本，可判定该 smoke 成功。

### 7.3 `docker exec ... /bin/bash -lc` 卡住

该环境中建议使用：

```bash
docker exec vllm-workspace /bin/sh -c '<your command>'
```
