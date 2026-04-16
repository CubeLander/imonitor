# fusion\_op（算子融合信息）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0074.html

展示模型中算子融合前后的信息数据，该数据无timeline信息，summary信息在fusion\_op\_\*.csv文件汇总。

单算子场景（如PyTorch场景）下无此性能数据文件。

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品/Atlas A2 推理系列产品

Atlas A3 训练系列产品/Atlas A3 推理系列产品

#### fusion\_op\_\*.csv文件说明

模型中算子融合前后信息数据fusion\_op\_\*.csv文件内容格式示例如下：

**图1** fusion\_op\_\*.csv

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。采集到的数据来源于Host侧时，显示值为host。 |
| Model Name | 模型名称。 |
| Model ID | 模型ID。 |
| Fusion Op | 融合算子名称。 |
| Original Ops | 被融合算子名称。 |
| Memory Input(KB) | 输入Tensor内存大小，单位KB。 |
| Memory Output(KB) | 输出Tensor内存大小，单位KB。 |
| Memory Weight(KB) | 权值内存大小，单位KB。 |
| Memory Workspace(KB) | Workspace内存大小，单位KB。 |
| Memory Total(KB) | 总内存，Memory Input、Memory Output、Memory Weight、Memory Workspace四项之和，单位KB。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
