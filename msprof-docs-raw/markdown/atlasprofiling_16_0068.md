# op\_statistic（算子调用次数及耗时）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0068.html

AI Core和AI CPU算子调用的次数及耗时数据无timeline信息，summary信息在op\_statistic\_\*.csv文件汇总。

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品/Atlas A2 推理系列产品

Atlas A3 训练系列产品/Atlas A3 推理系列产品

#### op\_statistic\_\*.csv文件数据说明

分析各类算子的调用总时间、总次数等，排查是否某类算子总耗时较长，进而分析这类算子是否有优化空间。

**图1** op\_statistic\_\*.csv

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。 |
| Model Name | 模型名称。如果Model Name值为空，则可能由于获取的数据中该值为空。（默认情况下或单算子场景不显示该字段） |
| OP Type | 算子类型。 |
| Core Type | Core类型，包含AI\_CORE、AI\_VECTOR\_CORE、AI\_CPU等。 |
| Count | 算子调用次数。 |
| Total Time(us) | 算子调用总耗时，单位us。 |
| Avg Time(us)、Min Time(us)、Max Time(us) | 分别对应算子调用平均耗时、最小耗时、最大耗时，单位us。 |
| Ratio(%) | 该类算子在对应模型中的耗时占比。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
