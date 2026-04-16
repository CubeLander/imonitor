# operator\_memory（CANN算子的内存占用明细）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0078.html

CANN算子的内存占用明细无timeline信息，summary信息在operator\_memory\_\*.csv文件汇总，主要记录CANN层级的算子在NPU上执行时所需内存及占用时间。

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品/Atlas A2 推理系列产品

Atlas A3 训练系列产品/Atlas A3 推理系列产品

#### operator\_memory\_\*.csv文件数据说明

operator\_memory\_\*.csv文件内容格式示例如下：

**图1** operator\_memory\_\*.csv

关键字段说明如下。

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。 |
| Name | 算子名称。 |
| Size(KB) | 算子占用内存大小，单位KB。 |
| Allocation Time(us) | 内存分配时间，单位us。 |
| Duration(us) | 内存占用时间，单位us。 |
| Allocation Total Allocated(KB) | 算子内存分配时GE内存池分配总额，单位KB。 |
| Allocation Total Reserved(KB) | 算子内存分配时GE内存池总额，单位KB。 |
| Release Total Allocated(KB) | 算子内存释放时GE内存池分配总额，单位KB。 |
| Release Total Reserved(KB) | 算子内存释放时GE内存池总额，单位KB。 |
| Device | 设备类型和设备ID，仅涉及NPU。 |

#### 负值空值说明

operator\_memory\_\*.csv文件中的部分信息存在空值或负值，是因为部分算子申请或释放不在性能数据采集进程的范围内，所以可能未采集到这些算子的内存申请或释放的过程。详细请参考下面示例：

**图2** 空值负值说明

负值说明：上图中4873行的Size列出现了负值（内存申请Size为正值，内存释放Size为负值，如果在采集性能数据的范围内申请且释放了内存，那么Size取申请的数值），而Name列无法识别到算子名称，且其他Allocation列分配内存为空，Release列释放内存数值正常，说明该算子的内存申请在性能数据采集进程前，但内存释放在性能数据采集的范围内，所以仅采集到了内存释放的负值。另外算子名的识别仅在内存申请时进行，所以内存释放时无法识别到算子名，又因为内存申请不在采集性能数据的范围内，所以Allocation列分配内存为空。

空值说明：上图中4874行之后的算子在Release列释放内存数值为空，其他数值正常，说明这些算子的内存申请在性能数据采集的范围内，内存释放却在性能数据采集的范围外，未采集到内存释放所以Release列为空。

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
