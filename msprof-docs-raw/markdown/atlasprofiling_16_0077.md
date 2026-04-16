# memory\_record（CANN算子的内存占用记录）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0077.html

CANN算子的内存占用记录无timeline信息，summary信息在memory\_record\_\*.csv文件汇总，主要记录CANN层级的GE组件申请的内存及占用时间。

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品/Atlas A2 推理系列产品

Atlas A3 训练系列产品/Atlas A3 推理系列产品

#### memory\_record\_\*.csv文件数据说明

memory\_record\_\*.csv文件内容格式示例如下：

**图1** memory\_record\_\*.csv

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。 |
| Component | 组件，使用CANN软件包的性能分析工具仅采集GE组件。 |
| Timestamp(us) | 时间戳，记录内存占用的起始时间，单位us。 |
| Total Allocated(KB) | 内存分配总额，单位KB 。 |
| Total Reserved(KB) | 内存预留总额，单位KB。 |
| Device | 设备类型和设备ID，仅涉及NPU。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
