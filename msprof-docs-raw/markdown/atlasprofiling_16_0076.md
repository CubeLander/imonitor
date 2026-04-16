# npu\_module\_mem（NPU组件内存占用）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0076.html

NPU组件内存占用数据无timeline信息，summary信息在npu\_module\_mem\_\*.csv文件汇总。

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品/Atlas A2 推理系列产品

Atlas A3 训练系列产品/Atlas A3 推理系列产品

#### npu\_module\_mem\_\*.csv文件数据说明

npu\_module\_mem\_\*.csv文件内容格式示例如下：

**图1** npu\_module\_mem\_\*.csv

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。 |
| Component | 组件名称。 |
| Timestamp(us) | 时间戳，单位us。可查看组件在当前时刻占用的内存。 |
| Total Reserved(KB) | 内存占用大小，单位KB。若为-1，则可能是该组件只采集到了释放的内存。 |
| Device | 设备类型和设备ID，仅涉及NPU。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
