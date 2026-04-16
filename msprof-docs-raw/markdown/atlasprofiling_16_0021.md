# 解析并导出性能数据

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0021.html

以下产品不支持在设备上直接解析，需要将采集到的PROF\_XXX目录拷贝到安装了CANN Toolkit开发套件包和ops算子包的环境下进行解析并导出：

* Atlas 200I/500 A2 推理产品的Ascend RC场景

#### 前提条件

* 请确保完成[使用前准备](atlasprofiling_16_0002.html)。
* 完成性能数据采集。

#### 操作步骤

执行导出命令。

命令示例如下：

```
msprof --export=on --output=<dir> [--type=<type>] [--reports=<reports_sample_config.json>] [--iteration-id=<number>] [--model-id=<number>] [--summary-format=<csv/json>] [--clear=on]
```

**表1** 参数说明

| 参数 | 说明 | **可选/必选** |
| --- | --- | --- |
| --export | 解析并导出性能数据。可选on或off，默认值为off。  若需导出个别模型（Model ID）/迭代（Iteration ID）的数据，可在msprof采集命令执行完成后重新执行msprof --export命令配置--model-id、--iteration-id参数。  对于未解析的PROF*\_*XXX文件，自动解析后再导出。  示例：msprof --export=on --output=/home/HwHiAiUser | 必选 |
| --output | 性能数据文件目录。须指定为PROF*\_*XXX目录或PROF*\_*XXX目录的父目录，例如：/home/HwHiAiUser/profiler\_data/PROF\_XXX。  路径中不能包含特殊字符："\n", "\\n", "\f", "\\f", "\r", "\\r", "\b", "\\b", "\t", "\\t", "\v", "\\v", "\u007F", "\\u007F", "\"", "\\\"", "'", "\'", "\\", "\\\\", "%", "\\%", ">", "\\>", "<", "\\<", "|", "\\|", "&", "\\&", "$", "\\$", ";", "\\;", "`", "\\`"。 | 必选 |
| --type | 设置性能数据解析结果文件格式，即可以选择msprof命令行执行采集后自动解析的结果文件格式，取值为：   * text：表示解析为.json和.csv格式的timeline和summary文件和.db格式文件（msprof\_时间戳.db），详见[性能数据文件参考](atlasprofiling_16_0056.html)。支持CANN 7.0.RC1和7.0.0及以上版本的性能数据解析。 * db：仅解析为一个汇总所有性能数据的.db格式文件（msprof\_时间戳.db），使用MindStudio Insight工具展示。当前该格式数据与text参数解析的数据信息量存在差异，建议使用text方式采集。配置db时，仅支持**msprof** **--export**命令的**--output**参数，不支持**msprof** **--export**命令的其他参数。   默认为text。 | 可选 |
| --reports | 传入用户自定义的reports\_sample\_config.json配置文件，会根据配置文件中指定的范围导出相应的性能数据。详见[--reports参数使用介绍](#ZH-CN_TOPIC_0000002502558624__section1128153151819)。 | 可选 |
| --iteration-id | 迭代ID。需配置为正整数。默认值为1。与--model-id必须同时配置。   * 对于Atlas A2 训练系列产品/Atlas A2 推理系列产品，支持--model-id=4294967295，表示指定以Step为粒度统计的迭代ID（每执行完成一个Step，Iteration ID加1）。仅支持解析MindSpore（版本号大于等于2.3）框架的性能数据。 * 对于Atlas A3 训练系列产品/Atlas A3 推理系列产品，支持--model-id=4294967295，表示指定以Step为粒度统计的迭代ID（每执行完成一个Step，Iteration ID加1）。仅支持解析MindSpore（版本号大于等于2.3）框架的性能数据。 * --model-id配置为其他值时，指定以Graph为粒度统计的迭代ID（每个Graph执行一次，Iteration ID加1，当一个脚本被编译为多个Graph时，该ID与脚本层面的Step ID不一致）。 | 可选 |
| --model-id | 模型ID。需配置为正整数。与--iteration-id必须同时配置。   * 对于Atlas A2 训练系列产品/Atlas A2 推理系列产品，支持--model-id=4294967295，为Step模式，即--iteration-id配置的值以Step为粒度解析。仅支持解析MindSpore（版本号大于等于2.3）框架的性能数据。 * 对于Atlas A3 训练系列产品/Atlas A3 推理系列产品，支持--model-id=4294967295，为Step模式，即--iteration-id配置的值以Step为粒度解析。仅支持解析MindSpore（版本号大于等于2.3）框架的性能数据。 * --model-id配置为其他值时，为Graph模式，即--iteration-id配置的值以Graph为粒度解析。 | 可选 |
| --summary-format | summary数据文件的导出格式，取值为：   * json：解析出的summary数据文件为json格式。 * csv：解析出的summary数据文件为csv，默认值。   仅--type=text时支持。 | 可选 |
| --python-path | 指定解析使用的Python解释器路径，要求Python 3.7.5及以上版本。 | 可选 |
| --clear | 数据精简模式，开启后将在导出性能数据后删除PROF\_XXX/device\_{id}下的sqlite目录，以节省存储空间。可选on或off，默认值为off。 | 可选 |
| 注1：默认情况下，导出所有性能数据。  注2：单算子场景和仅执行[采集昇腾AI处理器系统数据](atlasprofiling_16_0012.html)场景，不支持--iteration-id和--model-id参数。 | | |

执行完上述命令后，会在--output目录下的PROF\_XXX目录下生成mindstudio\_profiler\_output目录。

生成的性能数据目录结构如下所示。

* 单采集进程

  |  |  |
  | --- | --- |
  | ```  1  2  3  4  5  6  7  8  9 10 11 12 13 14 ``` | ``` └── PROF_XXX       ├── device_0       │    └── data       ├── device_1       │    └── data       ├── host       │    └── data       ├── msprof_*.db       └── mindstudio_profiler_output             ├── msprof_{timestamp}.json             ├── step_trace_{timestamp}.json             ├── xx_*.csv              ...             └── README.txt ``` |
* 多采集进程

  |  |  |
  | --- | --- |
  | ```  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 ``` | ``` └── PROF_XXX1       ├── device_0       │    └── data       ├── host       │    └── data       ├── msprof_*.db       └── mindstudio_profiler_output             ├── msprof_{timestamp}.json             ├── step_trace_{timestamp}.json             ├── xx_*.csv              ...             └── README.txt └── PROF_XXX2       ├── device_1       │    └── data       ├── host       │    └── data       ├── msprof_*.db       └── mindstudio_profiler_output             ├── msprof_{timestamp}.json             ├── step_trace_{timestamp}.json             ├── xx_*.csv              ...             └── README.txt ``` |

* msprof\_\*.db为汇总所有性能数据的db格式文件。mindstudio\_profiler\_output目录下的json文件为timeline信息文件，主要收集算子、任务等运行耗时，以色块形式展示；csv文件为summary信息文件，主要以表格形式汇总运行耗时。性能数据详细介绍请参见[性能数据文件参考](atlasprofiling_16_0056.html)。
* 多Device场景下，若启动单采集进程，则仅生成一个PROF\_XXX目录，若启动多采集进程则生成多个PROF\_XXX目录，其中device目录在PROF\_XXX目录下生成，每个PROF\_XXX目录下生成多少个device目录与用户实际操作有关，不影响性能数据分析。
* mindstudio\_profiler\_output目录中的文件是根据采集的实际性能数据进行生成，如果实际的性能数据没有相关的数据文件，就不会导出对应的timeline和summary数据。
* 对于被强制中断的msprof采集进程，工具会保存已采集的原始性能数据，**msprof** **--parse**功能重新解析后，再次执行**msprof --export**。

#### --reports参数使用介绍

命令示例：

```
msprof --export=on --output=./ --reports=${INSTALL_DIR}/tools/profiler/profiler_tool/analysis/msconfig/reports_sample_config.json
```

${INSTALL\_DIR}请替换为CANN软件安装后文件存储路径。若安装的Ascend-cann-toolkit软件包，以root安装举例，则安装后文件存储路径为：/usr/local/Ascend/ascend-toolkit/latest。

路径中不能包含特殊字符："\n", "\\n", "\f", "\\f", "\r", "\\r", "\b", "\\b", "\t", "\\t", "\v", "\\v", "\u007F", "\\u007F", "\"", "\\\"", "'", "\'", "\\", "\\\\", "%", "\\%", ">", "\\>", "<", "\\<", "|", "\\|", "&", "\\&", "$", "\\$", ";", "\\;", "`", "\\`"。

* --reports参数指定的是reports\_sample\_config.json文件。需要与--export同时配置，仅支持--type=text，且仅支持对json文件的timeline数据进行控制，csv文件的summary数据依然为全量导出。
* 不支持软链接，文件大小最大阈值为64M，文件路径加上文件名长度最大阈值为1024字符。

reports\_sample\_config.json文件默认保存在${INSTALL\_DIR}/tools/profiler/profiler\_tool/analysis/msconfig/目录下，内容如下：

支持在任意有读写权限的目录下自行创建reports\_sample\_config.json文件。

```
{
	"json_process": {
		"ascend": true,
		"acc_pmu": true,
		"cann": true,
		"ddr": true,
		"stars_chip_trans": true,
		"hbm": true,
		"communication": true,
		"hccs": true,
		"os_runtime_api": true,
		"network_usage": true,
		"disk_usage": true,
		"memory_usage": true,
		"cpu_usage": true,
		"msproftx": true,
		"npu_mem": true,
		"overlap_analyse": true,
		"pcie": true,
		"sio": true,
		"stars_soc": true,
		"step_trace": true,
		"freq": true,
		"llc": true,
		"nic": true,
		"roce": true,
		"qos": true,
		"device_tx": true
	}
}
```

以上为控制相应性能数据的开关，可配置开启（true）或关闭（false或删除字段）。控制的性能数据包括msprof\_\*.json文件的timeline数据层级（包括CANN，Ascend Hardware、AI Core Freq、片上内存、Communication、Overlap Analysis、NPU\_MEM层级等）。

* 导出以上数据的前提是原始性能数据中已存在相应数据，即相应数据已采集。
* 需确保reports\_sample\_config.json文件格式正确，否则可能导致如下情况：
  + 文件内容错误，如拼写错误，--reports参数不生效，导出全量性能数据。
  + 文件读取失败，如权限问题、文件不存在等，导致--reports无法读取配置文件，则会中断导出进程并报错。

**父主题：** [离线解析](atlasprofiling_16_0018.html)
