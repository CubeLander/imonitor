# 总体说明

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0056.html
Back to Top

采集性能原始数据，并解析导出成可视化的性能数据文件后，文件目录结构及主要文件如下。

#### 目录结构及文件说明

性能数据目录结构示例如下（仅展示性能数据）：

|  |  |
| --- | --- |
| ```  1  2  3  4  5  6  7  8  9 10 11 12 13 ``` | ``` ├── msprof_*.db ├── mindstudio_profiler_output │    ├── msprof_*.json │    ├── step_trace_*.json │    ├── xx_*.csv ... │    └── README.txt  ├── device_{id} ... │    └── data ├── host ...       └── data ``` |

\*表示{timestamp}时间戳。

* mindstudio\_profiler\_output目录保存Host和各个Device的性能数据汇总（性能数据分析推荐查看该目录下文件），目录下的结果文件命名格式为：“模块名\_{timestamp}.{json/csv}”。
* device\_*{id}*目录主要保存各个Device运行昇腾AI应用的性能原始数据和昇腾AI处理器系统原始数据。
* host目录主要保存上层应用接口（msproftx）的昇腾AI应用运行性能原始数据和Host系统原始数据。

默认采集的性能数据文件如[表1](#ZH-CN_TOPIC_0000002502558594__table775514312190)所示。

**表1** msprof默认配置采集的性能数据文件

| 文件名 | 说明 |
| --- | --- |
| msprof\_\*.db | 汇总所有性能数据的db格式文件。 |
| msprof\_\*.json | timeline数据总表。 |
| step\_trace\_\*.json | 迭代轨迹数据，每轮迭代的耗时。单算子场景（如PyTorch场景）下无此性能数据文件。 |
| op\_summary\_\*.csv | AI Core和AI CPU算子数据。 |
| op\_statistic\_\*.csv | AI Core和AI CPU算子调用次数及耗时统计。 |
| step\_trace\_\*.csv | 迭代轨迹数据。单算子场景（如PyTorch场景）下无此性能数据文件。 |
| task\_time\_\*.csv | Task Scheduler任务调度信息。 |
| fusion\_op\_\*.csv | 模型中算子融合前后信息。单算子场景（如PyTorch场景）下无此性能数据文件。 |
| api\_statistic\_\*.csv | 用于统计CANN层的API执行耗时信息。 |
| 注：表中的json文件为timeline信息文件，主要收集算子、任务等运行耗时，以色块形式展示；csv文件为summary信息文件，主要以表格形式汇总运行耗时。 | |

#### 查看整体性能数据

msprof\_\*.db为汇总整体性能数据的文件，mindstudio\_profiler\_output目录下的timeline和summary文件则是将各类性能数据拆分成多个文件，以上两类文件均可以使用MindStudio Insight工具导入后进行整体数据的可视化展示，详细操作请参见《MindStudio Insight工具用户指南》。

#### 查看timeline文件

使用Perfetto UI打开：在Chrome浏览器中输入“https://ui.perfetto.dev/”地址，将.json文件拖到空白处打开，通过键盘上的快捷键（w：放大，s：缩小，a：左移，d：右移）进行查看。

使用tracing打开：在Chrome浏览器中输入“chrome://tracing”地址，将.json文件拖到空白处打开，通过键盘上的快捷键（w：放大，s：缩小，a：左移，d：右移）进行查看。

超大文件推荐使用Perfetto UI打开。

#### summary文件说明

* 生成的summary数据文件使用Excel打开时，可能会出现字段值为科学计数的情况，例如“1.00159E+12”。此时可选中该单元格，然后“右键>设置单元格格式”，在弹出的对话框中“数字”标签下选择“数值”，单击“确定”就能正常显示。
* 生成的summary数据文件中某些字段值为“N/A”时，表示此时该值不存在。

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
