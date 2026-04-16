# l2\_cache（L2 Cache命中率）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0073.html

L2 Cache数据无timeline信息，summary信息在l2\_cache\_\*.csv文件汇总。

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品/Atlas A2 推理系列产品

Atlas A3 训练系列产品/Atlas A3 推理系列产品

#### l2\_cache\_\*.csv文件说明

L2 Cache数据l2\_cache\_\*.csv文件内容格式示例如下：

**图1** l2\_cache\_\*.csv

对于下列产品：

* Atlas 推理系列产品
* Atlas 训练系列产品

该文件中第一个算子的Hit Rate和Victim Rate数据不作为参考。

对于下列产品

* Atlas 200I/500 A2 推理产品
* Atlas A2 训练系列产品/Atlas A2 推理系列产品
* Atlas A3 训练系列产品/Atlas A3 推理系列产品

该文件中第一个算子数据缺失，不影响整体的性能分析。

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。 |
| Stream Id | 该Task所处的Stream ID。 |
| Task Id | Task任务的ID。 |
| Hit Rate | 内存访问请求命中L2次数与内存访问请求总次数的比值。  对于Atlas 200I/500 A2 推理产品，Hit Rate数据推荐使用aic\_metrics的L2 Cache分组实现，此采集方式下Hit Rate数据在op\_summary\_\*.csv文件中呈现。  对于Atlas A2 训练系列产品/Atlas A2 推理系列产品，Hit Rate数据推荐使用aic\_metrics的L2 Cache分组实现，此采集方式下Hit Rate数据在op\_summary\_\*.csv文件中呈现。  对于Atlas A3 训练系列产品/Atlas A3 推理系列产品，Hit Rate数据推荐使用aic\_metrics的L2 Cache分组实现，此采集方式下Hit Rate数据在op\_summary\_\*.csv文件中呈现。 |
| Victim Rate | 内存访问请求未命中并触发Cache中数据被换出的次数与内存访问请求总次数的比值。  对于Atlas 200I/500 A2 推理产品，Victim Rate数据可能出现大于1的情况。  对于Atlas A2 训练系列产品/Atlas A2 推理系列产品，Victim Rate数据可能出现大于1的情况。  对于Atlas A3 训练系列产品/Atlas A3 推理系列产品，Victim Rate数据可能出现大于1的情况。 |
| Op Name | 算子名称。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
