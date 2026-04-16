# 解析性能数据

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0018.html

以下产品不支持在设备上直接解析，需要将采集到的PROF\_XXX目录拷贝到安装了CANN Toolkit开发套件包和ops算子包的环境下进行解析：

* Atlas 200I/500 A2 推理产品的Ascend RC场景

* 该功能只会进行性能数据解析，不会导出性能数据文件，导出性能数据文件功能请参见[解析并导出性能数据](atlasprofiling_16_0021.html)。
* 一般情况下，解析性能数据功能不需要单独使用，主要有如下两种使用场景：
  + 对于性能数据文件解析失败的场景（例如：当存在首次解析由于某些原因导致解析失败，残留文件时），可以使用**msprof** **--parse**功能重新解析后，再次执行**msprof --export**。
  + 对于需要指定**--iteration-id**和**--model-id**参数进行**msprof --export**导出时，可以先执行**msprof** **--parse**解析并打印迭代（Iteration ID）/模型（Model ID）后，选择需要的Iteration ID和Model ID进行导出。

#### 前提条件

* 请确保完成[使用前准备](atlasprofiling_16_0002.html)。
* 完成性能数据采集。

#### 操作步骤

执行解析命令，命令示例如下：

```
msprof --parse=on --output=<dir>
```

**表1** 参数说明

| 参数 | 说明 | **可选/必选** |
| --- | --- | --- |
| --parse | 解析原始性能数据文件。可选on或off，默认值为off。 | 必选 |
| --output | 原始性能数据文件目录。须指定为PROF*\_*XXX目录或PROF*\_*XXX目录的父目录，例如：/home/HwHiAiUser/profiler\_data/PROF\_XXX。  路径中不能包含特殊字符："\n", "\\n", "\f", "\\f", "\r", "\\r", "\b", "\\b", "\t", "\\t", "\v", "\\v", "\u007F", "\\u007F", "\"", "\\\"", "'", "\'", "\\", "\\\\", "%", "\\%", ">", "\\>", "<", "\\<", "|", "\\|", "&", "\\&", "$", "\\$", ";", "\\;", "`", "\\`"。 | 必选 |
| --python-path | 指定解析使用的Python解释器路径，要求Python 3.7.5及以上版本。 | 可选 |

执行完上述命令，会打印展示性能数据文件信息并在PROF\_XXX的device*\_{**id**}*和host目录下生成sqlite目录，sqlite目录下会有.db文件生成。

**父主题：** [离线解析](atlasprofiling_16_0018.html)
