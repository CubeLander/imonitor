# msprof采集通用命令

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0009.html

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品 | √ |
| Atlas 训练系列产品 | √ |

#### 功能说明

msprof命令行工具提供了**AI任务运行性能数据**、**昇腾AI处理器系统数据**等性能数据的采集和解析能力。

其中，msprof采集通用命令是性能数据采集的基础，用于提供性能数据采集时的基本信息，包括参数说明、AI任务文件、数据存放路径、自定义环境变量等。

#### 注意事项

* 请确保AI任务能在运行环境中正常运行。
* 请确保完成[使用前准备](atlasprofiling_16_0002.html)。

不支持采集Python调用栈、PyTorch或MindSpore框架层数据，可使用对应框架接口方式采集。

#### 命令格式（Ascend EP）

登录CANN Toolkit开发套件包和ops算子包所在环境，可在任意目录下执行以下命令。

* 方式一（推荐）：在msprof命令末尾，直接传入用户程序或执行脚本。

  ```
  msprof [options] <app>
  ```
* 方式二：通过--application参数传入用户程序或执行脚本。

  ```
  msprof [options] --application=<app>
  ```

#### 命令格式（Ascend RC）

登录运行环境，进入msprof工具所在目录“/var”，执行以下命令。

* 方式一（推荐）：在msprof命令末尾，直接传入用户程序或执行脚本。

  ```
  ./msprof [options] <app>
  ```
* 方式二：通过--application参数传入用户程序或执行脚本。

  ```
  ./msprof [options] --application=<app>
  ```

#### 参数说明

**表1** 参数说明

| 参数 | 可选/必选 | 说明 | 产品支持情况 |
| --- | --- | --- | --- |
| <app> | 采用方式一，且采集全部性能数据、采集AI任务运行时性能数据或采集msproftx数据时，该参数必选 | （仅方式一支持）待采集性能数据的用户程序，请在msprof命令末尾传入用户程序或执行脚本。  配置示例：   * 举例1（msprof传入Python执行脚本和脚本参数）：msprof --output=/home/projects/output **python3 /home/projects/MyApp/out/sample\_run.py parameter1 parameter2** * 举例2（msprof传入main二进制执行程序）：msprof --output=/home/projects/output **main** * 举例3（msprof传入main二进制执行程序）：msprof --output=/home/projects/output **/home/projects/MyApp/out/main** * 举例4（在msprof传入main二进制执行程序和程序参数）：msprof --output=/home/projects/output **/home/projects/MyApp/out/main** **parameter1 parameter2** * 举例5（msprof传入sh执行脚本和脚本参数）：msprof --output=/home/projects/output **/home/projects/MyApp/out/****sample\_run.sh parameter1 parameter2**   说明：  * 若配置的用户程序命令中，存在配置参数值需要加引号的情况，请将命令写入Shell脚本后，通过执行Shell脚本的方式在msprof命令上添加用户程序命令。 * 不建议配置其他用户目录或其他用户可写目录下的AI任务，避免提权风险；不建议配置删除文件或目录、修改密码、提权命令等有安全风险的高危操作；应避免使用pmupload作为程序名称。 * 采集全部性能数据、采集AI任务运行时性能数据或采集msproftx数据时，本参数必选。 采集昇腾AI处理器系统数据时，本参数可选。  采集Host侧系统数据时，本参数可选。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 |
| --application=<app> | 采用方式二，且采集全部性能数据、采集AI任务运行时性能数据或采集msproftx数据时，该参数必选 | （仅方式二支持）待采集性能数据的用户程序，通过该参数可以传入用户程序名和入参。  配置示例：   * 使用msprof的--application参数传入main二进制执行程序和程序参数： msprof **--application="/home/projects/main** **parameter1 parameter2 ..."** * 使用msprof的--application参数传入sh执行脚本和脚本参数： 训练场景：msprof **--application="/home/projects/run.sh** **parameter1 parameter2 ..."**   若parameter中存在异常符号时将无法识别参数，因此推荐使用方式一传入用户程序。  说明：  * 不建议配置其他用户目录或其他用户可写目录下的AI任务，避免提权风险；不建议配置删除文件或目录、修改密码、提权命令等有安全风险的高危操作；应避免使用pmupload作为程序名称。 * 采集全部性能数据、采集AI任务运行时性能数据或采集msproftx数据时，本参数必选。 采集昇腾AI处理器系统数据时，本参数可选。  采集Host侧系统数据时，本参数可选。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 |
| --output=<path> | 可选 | 收集到的性能数据的存放路径。   * 采集**全部性能数据**或**采集AI任务运行时性能数据**时，本参数可选。 * **仅采集昇腾AI处理器系统数据**时，本参数必选。   该参数优先级高于ASCEND\_WORK\_PATH，具体请参见《环境变量参考》。  路径中不能包含特殊字符："\n", "\\n", "\f", "\\f", "\r", "\\r", "\b", "\\b", "\t", "\\t", "\v", "\\v", "\u007F", "\\u007F", "\"", "\\\"", "'", "\'", "\\", "\\\\", "%", "\\%", ">", "\\>", "<", "\\<", "|", "\\|", "&", "\\&", "$", "\\$", ";", "\\;", "`", "\\`"。  在msprof命令末尾添加AI任务执行命令来传入用户程序或执行脚本时，未配置--output的性能数据默认落盘在当前目录。  配置--application参数添加AI任务执行命令来传入用户程序或执行脚本时，未配置--output的性能数据默认落盘在AI任务文件所在目录。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 |
| --type=<type> | 可选 | 设置性能数据解析结果文件格式，即可以选择msprof命令行执行采集后自动解析的结果文件格式，取值为：   * text：表示解析为.json、.csv格式的文件和.db格式文件（msprof\_时间戳.db）。 * db：仅解析为一个汇总所有性能数据的.db格式文件（msprof\_时间戳.db），使用MindStudio Insight工具展示。   默认为text。  说明：  导出的.json、.csv格式的文件和.db格式文件详细内容请参见[性能数据文件参考](atlasprofiling_16_0056.html)。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 |
| --environment=<env> | 可选 | 执行采集时运行环境上需要的自定义环境变量。  不建议使用其他用户的目录覆盖原有环境变量，避免提权风险。  配置格式为**--****environment=**"${envKey}=${envValue}"或**--environment=**"${envKey1}=${envValue1};${envKey2}=${envValue2}"。例如：**--environment**="LD\_LIBRARY\_PATH=/home/xxx/Ascend/nnrt/latest;/home/xxx/Ascend/nnae/latest/lib64"。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 |
| --storage-limit=<limit-value> | 可选 | 指定落盘目录允许存放的最大文件容量。当性能数据文件在磁盘中即将占满本参数设置的最大存储空间或剩余磁盘总空间即将被占满时（总空间剩余<=20MB），则将磁盘内最早的文件进行老化删除处理。  范围[200, 4294967295]，单位为MB，例如**--storage****-limit**=200MB，默认未配置本参数。  未配置本参数时，默认取值为性能数据文件存放目录所在磁盘可用空间的90%。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 |
| --python-path=<python-path> | 可选 | 指定解析使用的Python解释器路径，要求Python 3.7.5及以上版本。  如果是高权限用户执行则禁止指定低权限路径。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 |
| --help | 可选 | 帮助提示参数。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 |

#### 使用示例（Ascend EP）

1. 登录CANN Toolkit开发套件包和ops算子包所在环境。
2. 在任意路径下执行以下命令，采集性能数据。

   ```
   msprof --output=/home/projects/output /home/projects/MyApp/out/main
   ```

   msprof命令执行完成后，会自动解析并导出性能数据结果文件，详细内容请参见[性能数据文件参考](atlasprofiling_16_0056.html)。

#### 使用示例（Ascend RC）

1. 登录运行环境。
2. 进入msprof工具所在目录“/var”，执行以下命令，采集性能数据。

   ```
   ./msprof --output=/home/projects/output /home/projects/MyApp/out/main
   ```

   msprof命令执行完成后，会自动解析并导出性能数据结果文件，详细内容请参见[性能数据文件参考](atlasprofiling_16_0056.html)。

**父主题：** [性能数据采集和自动解析](atlasprofiling_16_0009.html)
