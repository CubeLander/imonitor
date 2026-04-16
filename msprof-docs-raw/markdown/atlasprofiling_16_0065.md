# dp（数据增强信息）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0065.html

数据增强数据仅在训练场景下生成且仅生成summary数据dp\_\*.csv。

在TensorFlow训练场景开启数据预处理下沉（即enable\_data\_pre\_proc开关配置为True）时可生成dp\_\*.csv文件。详情请参见《TensorFlow 1.15模型迁移指南》中的“训练迭代循环下沉”章节。

#### 支持的型号

Atlas 训练系列产品

#### dp\_\*.csv文件说明

数据增强数据dp\_\*.csv文件内容格式示例如下：

**图1** dp\_\*.csv

**表1** 字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。 |
| Timestamp(us) | 事件的时间戳，单位us。 |
| Action | 事件的执行动作。 |
| Source | 事件的来源。 |
| Cached Buffer Size | 事件占用的Cached Buffer大小。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
