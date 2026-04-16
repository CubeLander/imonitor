# static\_op\_mem（静态图算子内存）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0079.html

静态图算子内存无timeline信息，summary信息在static\_op\_mem\_\*.csv文件汇总。

#### 支持的型号

Atlas 200I/500 A2 推理产品

Atlas 推理系列产品

Atlas 训练系列产品

Atlas A2 训练系列产品/Atlas A2 推理系列产品

Atlas A3 训练系列产品/Atlas A3 推理系列产品

#### static\_op\_mem\_\*.csv文件数据说明

static\_op\_mem\_\*.csv文件内容格式示例如下：

**图1** static\_op\_mem\_\*.csv

单算子场景通过调用aclprofCreateConfig接口开启ACL\_PROF\_TASK\_MEMORY开关采集生成，该数据仅在模型编译阶段上报。通过该文件可以查看静态图场景下每个Graph子图下算子的内存申请情况。

静态图场景下由Graph ID区分不同的计算图；动态子图场景下由Model Name（根节点名字）区分不同的子图。

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。 |
| Op Name | 算子名称。其中最后一行为TOTAL，表示申请的总内存。 |
| Model Name | 表示的静态子图根节点的名字，如果为0表示为静态图，没有静态子图，如果有静态子图则显示其根节点名字。 |
| Graph ID | Graph ID，每个Graph ID对应一张计算图。 |
| Node Index Start | 算子申请内存的逻辑时间。 |
| Node Index End | 算子释放内存的逻辑时间。显示为4294967295时，表示算子内存申请的时间最大值，即算子内存释放时间在计算图的生命周期结束时间。 |
| Size(KB) | 申请的内存大小，单位KB。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
