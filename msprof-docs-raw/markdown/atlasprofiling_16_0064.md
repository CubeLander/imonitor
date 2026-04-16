# step\_trace（迭代轨迹信息）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0064.html

迭代轨迹数据timeline信息在step\_trace\_\*.json文件展示，summary信息在step\_trace\_\*.csv文件汇总，用于判断并找出耗时较长的迭代。

单算子场景（如PyTorch场景）下无此性能数据文件。

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品/Atlas A2 推理系列产品

Atlas A3 训练系列产品/Atlas A3 推理系列产品

#### step\_trace\_\*.json文件说明

迭代轨迹数据step\_trace\_\*.json，根据Iteration的长短，判断哪个迭代耗时最长。

step\_trace\_\*.json文件内容格式示例如下：

**图1** step\_trace\_\*.json

迭代轨迹数据即训练任务及AI软件栈的软件信息，实现对训练任务的性能分析。以默认的两段式梯度切分为例，通过打印出训练任务中关键节点fp\_start/bp\_end/Reduce Start/Reduce Duration(us)的时间，达到把一个迭代的执行情况描述清楚的目的。

离线推理场景下不采集FP（训练网络迭代轨迹正向算子的开始位置）和BP（训练网络迭代轨迹反向算子的结束位置），采集结果将显示FP Start、BP End为NA且不存在timeline。

如上图，如果需要确定梯度切分策略，则需要计算图中bp\_end - allreduce1\_end的大小。根据已获取的迭代轨迹数据，我们需要使用**第一组**集合通信时间来计算，具体公式如：（BP End – Reduce End）/ freq。

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Title | 选择某个组件的接口名称。 |
| Start | 显示界面中时间轴上的时刻点，chrome trace自动对齐，单位ms。 |
| Wall Duration | 表示当前接口调用耗时，单位ms。 |
| Iteration ID | 以Graph为粒度统计的迭代ID，每个Graph执行一次，Iteration ID加1，当一个脚本被编译为多个Graph时，该ID与脚本层面的Step ID不一致。 |
| FP Start | FP开始时间，单位ns。 |
| Iteration End | 每轮迭代结束时间，单位ns。 |
| Iteration Time(ns) | 迭代时长，单位ns。 |
| BP End | BP结束时间，单位ns。 |
| FP\_BP Time | FP/BP计算时间（BP End - FP Start），单位ns。 |
| Iteration Refresh | 迭代拖尾时间（Iteration End - BP End），单位ns。 |
| Data\_aug Bound | 数据增强拖尾（本轮迭代FP Start - 上一个迭代Iteration End）。如果计算第一轮数据增强拖尾时没有上一轮迭代的Iteration End数据，那么第一轮迭代的数据增强拖尾数据值默认为N/A。 |
| Reduce | 集合通信时间，可能存在多组集合通信时间（ph：B表示某一组的开始时间，ph：E表示该组的结束时间）；如果非多P环境，则没有Reduce数据。 |

#### 数据读取时间分析

对于前一个迭代结束到后一个迭代开始之间的迭代间隙，若因数据读取耗时较长导致间隙过大，可以通过GetNext时间片，判断是否由于迭代的数据读取时间较长导致间隙过大。如[图2](#ZH-CN_TOPIC_0000002502718444__fig989215211178)所示。

仅TensorFlow框架支持。

**图2** GetNext

**表2** GetNext字段说明

| 字段名 | 字段含义 |
| --- | --- |
| GetNext Start | 数据读取开始时间，单位ns。 |
| GetNext End | 数据读取结束时间，单位ns。 |
| GetNext Time(ns) | 数据读取耗时，单位ns。 |

#### step\_trace\_\*.csv文件说明

step\_trace\_\*.csv文件内容格式示例如下：

**图3** step\_trace\_\*.csv

根据step\_trace\_\*.json文件的判断，可以对照step\_trace\_\*.csv文件的信息得到印证。

**表3** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。 |
| Iteration ID | 以Graph为粒度统计的迭代ID，每个Graph执行一次，Iteration ID加1，当一个脚本被编译为多个Graph时，该ID与脚本层面的Step ID不一致。 |
| FP Start(us) | FP开始时间，单位us。 |
| BP End(us) | BP结束时间，单位us。 |
| Iteration End(us) | 每轮迭代结束的时间，单位us。 |
| Iteration Time(us) | 迭代时长，单位us。 |
| FP to BP Time(us) | FP/BP计算时间（BP End - FP Start），单位us。 |
| Iteration Refresh(us) | 迭代拖尾时间（Iteration End - BP End），单位us。 |
| Data Aug Bound(us) | 数据增强拖尾（本轮迭代FP Start - 上一个迭代Iteration End），单位us。如果计算第一轮数据增强拖尾时没有上一轮迭代的Iteration End数据，那么第一轮迭代的数据增强拖尾数据值默认为N/A。 |
| Model ID | 某轮迭代的模型中的图ID。 |
| Reduce Start(us) | 集合通信开始时间，单位us。 |
| Reduce Duration(us) | 集合通信时间，可能存在多组集合通信时间，本示例按照系统默认切分策略是分为两段集合通信时间，Reduce Start表示开始时间，Reduce Duration表示由开始到结束时间，单位us。如果非多P环境，则没有Reduce数据。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
