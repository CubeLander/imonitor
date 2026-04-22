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
- `web/index.html + assets/*`
- `manifest.json`

## 兼容策略

- `collect.preset` 仍保留兼容（deprecated），内部会映射到通用入口脚本与默认参数。
- `collect.smoke` 仍可读取（deprecated），建议迁移到 `target.env`。
- `collect.out_root / collect.run_tag` 仍可读取（deprecated），建议迁移到 `profiler.out_root / profiler.run_tag`。
- 迁移完成后将移除 `collect.*` 兼容字段，统一到 `target / msprof / profiler`。
