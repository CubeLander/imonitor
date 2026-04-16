# 昇腾虚拟化实例场景性能数据采集开关支持情况

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0003.html

本文以msprof命令行和Profiling options开关为例介绍。

**表1** 昇腾虚拟化实例场景采集开关支持情况

| 开关 | 采集内容 | Atlas 推理系列产品 | Atlas 训练系列产品 | Atlas A2 训练系列产品/Atlas A2 推理系列产品 | Atlas A3 训练系列产品/Atlas A3 推理系列产品 | Atlas 200I/500 A2 推理产品（Ascend RC） |
| --- | --- | --- | --- | --- | --- | --- |
| msproftx | msproftx | 支持 | 支持 | 支持 | 支持 | 支持 |
| host-sys=cpu | cpu | 支持 | 支持 | 支持 | 支持 | 不支持 |
| host-sys=mem | memory | 支持 | 支持 | 支持 | 支持 | 不支持 |
| host-sys=disk | disk | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| host-sys=network | network | 支持 | 支持 | 支持 | 支持 | 不支持 |
| host-sys=osrt | osrt | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| ascendcl | ACL | 支持 | 支持 | 支持 | 支持 | 支持 |
| model-execution | GE | 支持 | 支持 | 支持 | 支持 | 支持 |
| runtime-api  task-time  task\_trace（options） | Runtime | 支持 | 支持 | 支持 | 支持 | 支持 |
| hccl  task\_trace（options） | 通信相关数据 | 支持 | 支持 | 支持 | 支持 | 支持 |
| aicpu | DATAPROCESS | 支持 | 支持 | 支持 | 支持 | 支持 |
| aic-metrics  aic-mode=task-base | AICORE（task-based）  AI Vector CORE（task-based） | 支持 | 支持 | 支持 | 支持 | 支持 |
| training\_trace（options）  task-time  task\_trace（options） | TSFW | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| l2 | L2 Cache | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| sys-io-profiling | NIC、RoCE | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| dvpp-profiling | DVPP | 支持 | 不支持 | 支持 | 支持 | 支持 |
| sys-hardware-mem | 片上内存、LLC | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| sys-interconnection-profiling | PCIe、HCCS | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| sys-cpu-profiling | AICPU、CTRL CPU、TSCPU | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| sys-profiling  sys-pid-profiling | cpu、memory | 不支持 | 不支持 | 不支持 | 不支持 | 支持 |
| aic-metrics  aic-mode=sample-base | AICORE（sample-based） | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |
| task-time  task\_trace（options） | HWTS\_LOG | 支持 | 支持 | 支持 | 支持 | 支持 |
| training\_trace（options） | FMK | 支持 | 支持 | 支持 | 支持 | 支持 |
| instr-profiling | INSTRUCTION | 不支持 | 不支持 | 不支持 | 不支持 | 不支持 |

**父主题：** [附录](atlasprofiling_16_0135.html)
