# msprof（timeline数据总表）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0059.html

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品
/
Atlas A2 推理系列产品

Atlas A3 训练系列产品
/
Atlas A3 推理系列产品

timeline数据总表文件为msprof\_\*.json。

msprof\_\*.json在“chrome://tracing”中展示如下。

**图1** timeline汇总展示
  

如[图1](#ZH-CN_TOPIC_0000002534478467__fig10608132131617)所示，timeline汇总数据主要展示如下区域：

* 区域1：应用层数据，包含上层应用运行的耗时信息，需要使用msproftx采集或PyTorch场景采集。
* 区域2：CANN层数据，主要包含Runtime等组件以及Node（算子）的耗时数据。
* 区域3：底层NPU数据，主要包含Ascend Hardware下各个Stream任务流的耗时数据和迭代轨迹数据、Communication和Overlap Analysis通信数据以及其他昇腾AI处理器系统数据。
* 区域4：展示timeline中各算子、接口的详细信息（单击各个timeline时展示）。

* timeline数据总表的数据在[性能数据文件参考](atlasprofiling_16_0056.html)均有对应数据的详细介绍。
* 上图中各区域的数据与采集场景有关，例如区域1仅在msproftx或PyTorch场景采集时生成；Communication和Overlap Analysis通信数据仅在多卡、多节点或集群等存在通信的场景可采集到数据等。请以采集数据实际情况为准。
* msprof\_\*.json展示的数据是迭代内的数据，迭代外的数据不展示。

#### 查看算子下发方向

在tracing中查看.json文件时，开启“Flow events”下的选项后，应用层算子到NPU算子之间通过连线方式展示下发到执行的对应关系。如[图2](#ZH-CN_TOPIC_0000002534478467__fig490591821019)所示。

主要包括的对应关系有：

* async\_npu：应用层算子 > Ascend Hardware的NPU算子的下发执行关系。
* MsTx：推理训练进程打点任务 > Ascend Hardware的NPU打点算子的下发执行关系。调用aclprofMarkEx接口打点时生成。
* async\_task\_queue：应用层Enqueue > Dequeue的入队列到出队列对应关系。
* HostToDevice：CANN层Node（算子） > AscendHardware的NPU算子的下发执行关系（Host到Device）。
* HostToDevice：CANN层Node（算子） > Communication通信算子的下发执行关系（Host到Device）。
* fwdbwd：前向API > 反向API。

* 由于软件测量的昇腾AI处理器频率与真实频率有误差，以及Host与Device的时间同步误差，可能会出现下层算子因错位而无法连线的问题。

* 各层的对应关系是否呈现与对应采集场景是否采集该数据有关，请以实际情况为准。

**图2** 算子映射关系

通过单击连线两端的算子或接口，即可查看算子下发的方向。如[图3](#ZH-CN_TOPIC_0000002534478467__fig11692135416129)所示。

**图3** 算子信息

其中Event(s)列查看该算子或接口的出入方向，Link列查看映射关系两端的信息。

#### 查看AI Core频率

支持的型号：

* Atlas 200I/500 A2 推理产品
* Atlas A2 训练系列产品
  /
  Atlas A2 推理系列产品
* Atlas A3 训练系列产品
  /
  Atlas A3 推理系列产品

msprof\_\*.json下的“AI Core Freq”层级展示AI Core芯片在执行AI任务的过程中频率的变化情况，如[图4](#ZH-CN_TOPIC_0000002534478467__fig66071155154219)所示。

**图4** 查看AI Core频率

在148089.72045898438时刻下，AI Core处于高频状态，而在170178.44116210938时刻频率降低，那么在该时间段下AI任务的性能必然下降。AI Core芯片可能因温度升高，触发保护机制，降低频率；也可能因当前无AI任务运行，AI Core进入低功耗状态而降频。

在发生变频时，实际变频时间与软件监测到的时间存在0~1ms的延时，该延时可能导致变频前后统计出的算子执行时间与实际不符。

#### SIO数据分析

支持的型号：

* 对于
  Atlas A2 训练系列产品
  /
  Atlas A2 推理系列产品
  ，该数据均为0，不具有参考性。
* Atlas A3 训练系列产品
  /
  Atlas A3 推理系列产品

msprof\_\*.json下的“SIO”层级展示
Atlas A3 训练系列产品
/
Atlas A3 推理系列产品
die间传输带宽信息。

**图5** SIO

图中色块横坐标对应时间Time，单位ms，纵坐标对应带宽Value，单位MB/s。

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| dat\_rx | 数据流通道的接收带宽。 |
| dat\_tx | 数据流通道的发送带宽。 |
| req\_rx | 请求流通道的接收带宽。 |
| req\_tx | 请求流通道的发送带宽。 |
| rsp\_rx | 回应流通道的接收带宽。 |
| rsp\_tx | 回应流通道的发送带宽。 |
| snp\_rx | 侦听流通道的接收带宽。 |
| snp\_tx | 侦听流通道的发送带宽。 |

#### QoS数据分析

msprof\_\*.json下的“QoS”层级展示设备QoS带宽信息。

支持的型号：

* Atlas A2 训练系列产品
  /
  Atlas A2 推理系列产品
* Atlas A3 训练系列产品
  /
  Atlas A3 推理系列产品

**图6** QoS OTHERS

图中色块横坐标对应时间Time，单位ms，纵坐标对应带宽Value，单位MB/s。

#### 计算及通信算子融合MC²

支持的型号：

* Atlas 推理系列产品
* Atlas A2 训练系列产品
  /
  Atlas A2 推理系列产品

存在计算和通信算子融合的场景。

MC²：Matrix Computation & Communication，是CANN中一系列计算通信融合算子的统称，把原本串行的两个通信、计算算子融合到一起，内部通过Tiling切分成多轮通信计算，轮次间形成流水并行，从而掩盖通信耗时，提升整体执行性能。

具体算子一般以原计算通信算子名称按照依赖关系排列命名。比如AllgatherMatmul融合算子代表通信算子Allgather和计算算子Matmul融合，Matmul依赖Allgather输出。

通信轮次commTurn：即融合算子Tiling切分的份数。一般值为总数据量/单次通信量。

MC²实现中，内部分别在计算流、通信流上加载两个算子，两个算子内部实现协同完成流水并行执行：

* 计算流对应算子名称为融合算子名称，比如AllgatherMatmul。
* 通信流对应算子名称为融合算子名称+Aicpu，比如AllgatherMatmulAicpu。

通信算子根据融合算子Tiling切分执行多个通信轮次，每轮的基本流程是，根据计算算子下发的通信参数，执行集合通信算法，编排好具体任务，下发给硬件执行，并等待执行完成，通知计算侧执行结果。

* 通信API场景暂不支持融合MC²，通信API场景包括：低bit通信MatmulAllReduce算子以及自定义的使用通信API的MC²算子。
* timeline的Communication部分仅呈现Level0级别的数据。

MC²性能数据结果示例如下：

**图7** MC²

[图7](#ZH-CN_TOPIC_0000002534478467__fig16795116316)展示了MatmulAllReduceAddRmsNormAicpu融合算子，内部各阶段含义介绍如[表2](#ZH-CN_TOPIC_0000002534478467__table137165193119)所示。

**表2** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| StartServer | KFC初始化时间。 |
| TaskWaitRequest | 等待计算算子下发通信参数。 |
| TaskOrchestration | 通信算子内部执行集合通信算法，编排执行任务耗时。 |
| TaskLaunch | 任务下发耗时。 |
| TaskExecute | 等待硬件任务执行完成耗时。 |
| Finalize | KFC结束流程。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
