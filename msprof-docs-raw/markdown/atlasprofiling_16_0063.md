# api\_statistic（API耗时统计信息）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0063.html

API耗时信息统计数据timeline信息在msprof\_\*.json文件的CANN层级展示，summary信息在api\_statistic\_\*.csv文件汇总，用于统计CANN层的API执行耗时信息，主要包括AscendCL、Runtime、Node、Model、Communication层级的API。

* AscendCL：AscendCL API，昇腾平台上开发深度神经网络应用的C语言API库。
* Runtime：Runtime API，CANN运行时API。
* Node：对应CANN层算子。
* Model：模型，内部分析使用，无须关注。
* Communication：集合通信算子。

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品/Atlas A2 推理系列产品

Atlas A3 训练系列产品/Atlas A3 推理系列产品

#### msprof\_\*.json文件的CANN层级数据说明

msprof\_\*.json文件CANN层数据部分主要展示当前Thread下运行的接口耗时，如下图所示。

**图1** CANN层数据

通过图中的timeline色块，可以直接观察到哪些接口耗时较长，并通过单击选中耗时较长的接口查看该接口的详细信息，如下表所示。

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Title | 选择某个接口名称。 |
| Start | 显示界面中时间轴上的时刻点，chrome trace自动对齐，单位ms。 |
| Wall Duration | 表示当前接口调用耗时，单位ms。 |
| Self Time | 表示当前接口本身执行耗时，单位ms。 |
| Mode | AscendCL API类型。包含：ACL\_OP（单算子模型接口）、ACL\_MODEL（模型接口）、ACL\_RTS（Runtime接口）等。 |
| level | 层级，当前为AscendCL层。 |

#### api\_statistic\_\*.csv文件说明

api\_statistic\_\*.csv文件内容格式示例如下：

**图2** api\_statistic\_\*.csv

上图根据Time列进行降序排列，找出耗时最长的TopN算子；也可以根据最大、最小、平均耗时、方差等信息判断该算子运行是否稳定或者是否存在某次调用耗时较长的情况。例如方差数值越小，则代表算子运行越稳定；最大最小值越接近平均值且不存在个别数据差异较大的情况，则代表算子运行越稳定。

**表2** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。采集到的数据来源于Host侧时，显示值为host。 |
| Level | API所属层级。 |
| API Name | API名称。 |
| Time(us) | 总耗时，单位us。 |
| Count | 调用次数。 |
| Avg(us) | 耗时平均值，单位us。 |
| Min(us) | 最小耗时，单位us。 |
| Max(us) | 最大耗时，单位us。 |
| Variance | 耗时方差。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
