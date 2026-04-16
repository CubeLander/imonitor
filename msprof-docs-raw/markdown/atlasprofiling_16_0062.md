# task\_time（任务调度信息）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0062.html

任务调度信息数据timeline信息在msprof\_\*.json文件的Ascend Hardware层级展示，summary信息在task\_time\_\*.csv文件汇总，用于识别AI任务运行时的调度耗时。

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品/Atlas A2 推理系列产品

Atlas A3 训练系列产品/Atlas A3 推理系列产品

#### msprof\_\*.json文件中的任务调度信息数据说明

msprof\_\*.json文件中的任务调度信息数据在Ascend Hardware中的各个Stream呈现，通过记录AI任务运行时，各个Task在不同加速器下的执行耗时，可以直观判断任务调度耗时长短。

msprof\_\*.json文件中的任务调度信息数据示例如下：

**图1** Ascend Hardware

关键字段说明如下。

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Title | 选择某个组件的接口名称。 |
| Start | 显示界面中时间轴上的时刻点，chrome trace自动对齐，单位ms。 |
| Wall Duration | 表示当前接口调用耗时，单位ms。 |
| Task Time(us) | AI CPU算子的Task任务耗时，单位us。 |
| Reduce Duration(us) | ALL REDUCE算子的集合通信时间，单位us。 |
| Model Id | 模型ID。 |
| Task Type | 执行该Task的加速器类型，包含AI\_CORE、AI\_VECTOR\_CORE、AI\_CPU等。 |
| Stream Id | 该Task所处的Stream ID。在Ascend Hardware下的Stream Id为该任务的完整逻辑流ID，而在右侧timeline内的各个接口的Stream Id属性则为该接口的物理流ID（Physical Stream Id）。 |
| Task Id | 对应的Task ID。 |
| Subtask Id | 对应的Subtask ID。 |
| Aicore Time(ms) | 当所有的Block被同时调度，且每个Block的执行时长相等时，该Task在AI Core上的理论执行时间，单位ms。通常情况下，不同的Block开始调度时间略有差距，故该字段值略小于Task在AI Core上的实际执行时间。手动调频、功耗超出默认功耗值时动态调频以及Atlas 300V/Atlas 300I Pro情况下该数据不准确，不建议参考。 |
| Total Cycle | 该Task在AI Core上执行的cycle总数，由所有的Block的执行cycle数累加而成。 |
| Receive Time | Device收到内存拷贝Task的信息接收时间，单位us。仅MemcopyAsync接口展示。 |
| Start Time | 内存拷贝Task开始拷贝的时间，单位us。仅MemcopyAsync接口展示。 |
| End Time | 内存拷贝Task结束拷贝的时间，单位us。仅MemcopyAsync接口展示。 |
| size(B) | 拷贝的数据量，单位B。仅MemcopyAsync接口展示。 |
| bandwidth(GB/s) | 拷贝的带宽，单位GB/s。仅MemcopyAsync接口展示。 |
| operation | 拷贝类型，host to device或device to host等。仅MemcopyAsync接口展示。 |

#### task\_time\_\*.csv文件说明（Atlas 推理系列产品）（Atlas 训练系列产品）（Atlas A2 训练系列产品）（Atlas A3 训练系列产品/Atlas A3 推理系列产品）（Atlas 200I/500 A2 推理产品）

task\_time\_\*.csv文件内容格式示例如下：

**图2** task\_time\_\*.csv

可以通过查看Task的Top耗时对应的算子，根据该算子的具体实现来判断算子是否存在问题。

**表2** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。 |
| kernel\_name | Kernel的名称。显示为N/A表示为非计算类算子。 |
| kernel\_type | Kernel的类型，包含：KERNEL\_AICORE、KERNEL\_AICPU等。 |
| stream\_id | 该Task所处的Stream ID。 |
| task\_id | Task任务的ID。 |
| task\_time(us) | Task耗时，包含调度到加速器的时间、加速器上的执行时间以及结束响应时间，单位us。 |
| task\_start(us) | Task开始时间，单位us。 |
| task\_stop(us) | Task结束时间，单位us。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
