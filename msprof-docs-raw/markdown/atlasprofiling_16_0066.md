# communication\_statistic（集合通信算子统计信息）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0066.html

集合通信算子和计算及通信流水掩盖数据timeline信息在msprof\_\*.json文件的Communication层级展示，summary信息在communication\_statistic\_\*.csv文件汇总，以及在msprof\_\*.json下展示“Overlap Analysis”计算及通信的流水掩盖分析数据。

集合通信算子数据只有在多卡、多机或集群等存在卡间通信的场景下才能被采集并解析出性能数据。

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品/Atlas A2 推理系列产品

Atlas A3 训练系列产品/Atlas A3 推理系列产品

#### msprof\_\*.json文件的Communication层级数据说明

msprof\_\*.json文件Communication层数据如下图所示。

**图1** 通信大算子信息

**图2** 通信小算子信息

多卡、多机或集群场景时各Device之间存在通信，形成各个通信域，Communication层按照各个通信域进行排列，收集通信算子的耗时，该文件下可以直观找出耗时最长的通信算子。

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| **公共信息** | |
| Group \* Communication（通信域名称，根据实际上报的名称确定） | 通信域下的通信算子。一个卡（Rank）可以存在于不同的通信域中，一个Group标识当前卡在当前通信域的行为。 |
| Plane ID | 网络平面ID。对多个收发通信链路的并行调度执行，每个Plane就是一个并发通信维度。 |
| Title | 选择某个组件的接口名称。 |
| Start | 显示界面中时间轴上的时刻点，chrome trace自动对齐，单位ms。 |
| Wall Duration | 表示当前接口调用耗时，单位ms。 |
| Self Time | 表示当前指令本身执行耗时，单位ms。 |
| **通信大算子信息** | |
| connection\_id | CANN层API向NPU算子下发时二者关联的标识。 |
| model id | 模型ID。 |
| data\_type | 数据类型。 |
| alg\_type | 通信算子各阶段的算法类型，包含：MESH、RING、NB、HD、NHR、PIPELINE、PAIRWISE、STAR。 |
| count | 数据传输的数量。 |
| relay | 通信算子是否发生借轨。显示为yes（表示发生了借轨）或no（表示没有发生借轨）。支持型号：  Atlas A2 训练系列产品/Atlas A2 推理系列产品：仅显示为no，无意义  Atlas A3 训练系列产品/Atlas A3 推理系列产品 |
| retry | 通信算子是否发生重执行。显示为yes（表示发生了重执行）或no（表示没有发生重执行）。支持型号：  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 |
| **通信小算子信息** | |
| notify id | notify唯一ID。notify id仅对task type为notify类型及用于传输notify record信号的RDMA send类的task有效；其他task type时无效，显示为18446744073709551615。 |
| duration estimated(us) | 预估任务持续时间，单位us。 |
| stream id | Stream任务的ID。 |
| task id | Task任务的ID。 |
| task type | Task类型。 |
| src rank | 源Rank。 |
| dst rank | 目的Rank。若此字段显示为4294967295，则为本地片内操作。 |
| transport type | 传输类型，包含：LOCAL、SDMA、RDMA。 |
| size(Byte) | 数据量，单位Byte。在task type为notify类型时无效，填充为0。 |
| data type | 数据类型。 |
| link type | 链路类型，包含：HCCS、PCIe、RoCE。 |
| bandwidth(GB/s) | 带宽大小，单位GB/s。 |
| model id | 模型ID。 |

#### 计算及通信的流水掩盖分析

msprof\_\*.json下的“Overlap Analysis”为计算及通信的流水掩盖分析数据，由--task-time和--hccl开关控制。如[图3](#ZH-CN_TOPIC_0000002534478443__fig1514136114211)所示。

计算和通信存在并行，那么可通过查看流水掩盖的重叠时间（计算和通信并行的时间）从而判断计算通信效率。

**图3** 计算及通信的流水掩盖呈现效果图

**表2** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Communication | 通信时间。单卡场景无通信，不展示该字段。 |
| Communication(Not Overlapped) | 无掩盖的通信时间。单卡场景无通信，不展示该字段。 |
| Computing | 计算时间。 |
| Free | 间隙时间。 |
| Start | 表示当前接口开始调用的时刻点，单位ms。 |
| Wall Duration | 表示当前接口调用耗时，单位ms。 |

#### communication\_statistic\_\*.csv文件说明

communication\_statistic\_\*.csv文件内容格式示例如下：

**图4** communication\_statistic\_\*.csv

communication\_statistic\_\*.csv为集合通信算子统计信息，通过集合通信算子统计信息了解该类算子的耗时，以及各通信算子在集合通信内部的耗时占比，从而判断某个算子是否存在优化空间。

**表3** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。 |
| OP Type | 集合通信算子类型。 |
| Count | 集合通信算子执行次数。 |
| Total Time(us) | 集合通信算子执行总耗时，单位us。 |
| Min Time(us) | 集合通信算子执行最小耗时，单位us。 |
| Avg Time(us) | 集合通信算子执行平均耗时，单位us。 |
| Max Time(us) | 集合通信算子执行最大耗时，单位us。 |
| Ratio(%) | 集合通信算子执行耗时与整体集合通信耗时占比。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
