# 采集AI任务运行性能数据

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0011.html

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品 | √ |
| Atlas 训练系列产品 | √ |

#### 功能说明

msprof支持采集AI任务运行时相关的性能数据，并且在采集后可以自动进行性能数据解析和文件落盘。

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

| 参数 | 可选/必选 | 说明 | 产品支持情况 | 性能数据文件 |
| --- | --- | --- | --- | --- |
| <app> | 必选 | （仅方式一支持）待采集性能数据的用户程序，请在msprof命令末尾传入用户程序或执行脚本。  配置示例：  msprof --output=/home/projects/output **python3** **/home/projects/MyApp/out/****sample\_run.py** **parameter1 parameter2**  msprof --output=/home/projects/output **main**  msprof --output=/home/projects/output **/home/projects/MyApp/out/main**  msprof --output=/home/projects/output **/home/projects/MyApp/out/main** **parameter1 parameter2**  msprof --output=/home/projects/output **/home/projects/MyApp/out/****sample\_run.sh** **parameter1 parameter2**  说明：  * 不建议配置其他用户目录或其他用户可写目录下的AI任务，避免提权风险；不建议配置删除文件或目录、修改密码、提权命令等有安全风险的高危操作；应避免使用pmupload作为程序名称。 * 采集全部性能数据、采集AI任务运行时性能数据或采集msproftx数据时，本参数必选。 采集昇腾AI处理器系统数据时，本参数可选。  采集Host侧系统数据时，本参数可选。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --application=<app> | 必选 | （仅方式二支持）待采集性能数据的用户程序，通过该参数可以传入用户程序名和入参。  配置示例：  推理场景：msprof **--application="/home/projects/MyApp/out/main** **parameter1 parameter2 ..."**  训练场景：msprof **--application="/home/projects/mindspore/scripts/run\_standalone\_train.sh** **parameter1 parameter2 ..."**  若parameter中存在异常符号时将无法识别参数，因此推荐使用方式一传入用户程序。  说明：  * 不建议配置其他用户目录或其他用户可写目录下的AI任务，避免提权风险；不建议配置删除文件或目录、修改密码、提权命令等有安全风险的高危操作；应避免使用pmupload作为程序名称。 * 采集全部性能数据、采集AI任务运行时性能数据或采集msproftx数据时，本参数必选。 采集昇腾AI处理器系统数据时，本参数可选。  采集Host侧系统数据时，本参数可选。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --ascendcl=<ascendcl-value> | 可选 | 控制acl接口性能数据采集的开关，可选on或off，默认为on。  可采集acl接口性能数据，包括Host与Device之间、Device间的同步异步内存复制时延等。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [msprof\_\*.json中的CANN\_AscendCL层级和api\_statistic\_\*.csv文件](atlasprofiling_16_0063.html)  [db文件的COMMUNICATION\_TASK\_INFO表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section1656344215167)  [db文件的CANN\_API表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section2740528151615) |
| --model-execution=<model-execution-value> | 可选 | 控制ge model execution性能数据采集开关，可选on或off，默认为off。  说明：  此开关后续版本会废弃，请使用--task-time开关控制相关数据采集。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [fusion\_op\_\*.csv](atlasprofiling_16_0074.html) |
| --runtime-api=<runtime-api-value> | 可选 | 控制runtime API性能数据采集开关，可选on或off，默认为off。可采集runtime API性能数据，包括Host与Device之间、Device间的同步异步内存复制时延等。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [msprof\_\*.json中的CANN\_Runtime层级和api\_statistic\_\*.csv文件](atlasprofiling_16_0063.html)  [db文件的MEMCPY\_INFO表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section190813398529) |
| --hccl=<hccl-value> | 可选 | 控制通信数据采集开关，可选on或off，默认为off。该数据只在多卡、多节点或集群场景下生成。  说明：  此开关后续版本会废弃，请使用--task-time开关控制相关数据采集。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [msprof\_\*.json中的Communication层级和communication\_statistic\_\*.csv文件](atlasprofiling_16_0066.html)  [api\_statistic\_\*.csv](atlasprofiling_16_0063.html)  [db文件的COMMUNICATION\_TASK\_INFO表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section1656344215167)  [db文件的COMMUNICATION\_OP表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section1238183491611) |
| --task-time=<task-time-value> | 可选 | 控制采集算子下发耗时和算子执行耗时的开关。涉及在task\_time、op\_summary、op\_statistic等文件中输出相关耗时数据。配置值：   * l0：采集算子下发耗时、算子执行耗时数据。与l1相比，由于不采集算子基本信息数据，采集时性能开销较小，可更精准统计相关耗时数据。 * l1：采集算子下发耗时、算子执行耗时数据、算子基本信息数据，提供更全面的性能分析数据。该参数支持采集集合通信算子数据。 * on：开启，默认值，和配置为l1的效果一样。 * off：关闭。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [msprof\_\*.json中的CANN层级和api\_statistic\_\*.csv文件](atlasprofiling_16_0063.html)  [msprof\_\*.json中的Ascend Hardware层级和task\_time\_\*.csv文件](atlasprofiling_16_0062.html)  [msprof\_\*.json中的Communication层级和communication\_statistic\_\*.csv文件](atlasprofiling_16_0066.html)  [step\_trace（迭代轨迹数据）](atlasprofiling_16_0064.html)  [op\_summary\_\*.csv](atlasprofiling_16_0067.html)  [op\_statistic\_\*.csv](atlasprofiling_16_0068.html)  [fusion\_op\_\*.csv](atlasprofiling_16_0074.html)  [db文件的TASK表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section16993252171612)  [db文件的COMPUTE\_TASK\_INFO表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section1724311477163)  [db文件的COMMUNICATION\_TASK\_INFO表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section1656344215167)  [db文件的COMMUNICATION\_OP表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section1238183491611) |
| --aicpu=<aicpu-value> | 可选 | 采集AICPU算子的详细信息，如：计算耗时、数据拷贝耗时等。可选on或off，默认值为off。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [aicpu\_\*.csv](atlasprofiling_16_0071.html)  [dp\_\*.csv](atlasprofiling_16_0065.html) |
| --ai-core=<aicore-value> | 可选 | 控制AI Core数据采集的开关。  取值可选on或off，--task-time配置为on、l1时，默认为on；--task-time配置为off、l0时，默认为off。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [op\_summary\_\*.csv](atlasprofiling_16_0067.html)  [db文件的TASK\_PMU\_INFO表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section72694413158) |
| --aic-mode=<aic-mode-value> | 可选 | AI Core硬件的采集类型，可选值task-based或sample-based。该参数配置前提是**--ai-core**参数设置为on。  task-based是以task为粒度进行性能数据采集，sample-based是以固定的时间周期进行性能数据采集，采集AI任务性能数据时建议使用task-based，如果不配置默认为task-based。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --aic-freq=<aic-freq-value> | 可选 | sample-based场景下的采样频率，默认值100，范围1~100，单位Hz。该参数配置前提是**--ai-core**参数设置为on。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --aic-metrics=<aic-metrics-value> | 可选 | AI Core性能指标采集项。该参数配置前提是**--ai-core**参数设置为on。相关采集项介绍请参考[op\_summary\_\*.csv](atlasprofiling_16_0067.html)中的说明。  取值包括：   * Atlas 200I/500 A2 推理产品：ArithmeticUtilization、PipeUtilization、Memory、MemoryL0、MemoryUB、ResourceConflictRatio、L2Cache、PipelineExecuteUtilization（默认值） * Atlas 推理系列产品：ArithmeticUtilization、PipeUtilization（默认值）、Memory、MemoryL0、MemoryUB、ResourceConflictRatio * Atlas 训练系列产品：ArithmeticUtilization、PipeUtilization（默认值）、Memory、MemoryL0、MemoryUB、ResourceConflictRatio * Atlas A2 训练系列产品/Atlas A2 推理系列产品：ArithmeticUtilization、PipeUtilization（默认值）、Memory、MemoryL0、MemoryUB、ResourceConflictRatio、L2Cache、MemoryAccess * Atlas A3 训练系列产品/Atlas A3 推理系列产品：ArithmeticUtilization、PipeUtilization（默认值）、Memory、MemoryL0、MemoryUB、ResourceConflictRatio、L2Cache、MemoryAccess   说明：  支持自定义需要采集的寄存器，例如：--aic-metrics=**Custom:***0x49,0x8,0x15,0x1b,0x64,0x10。*  * Custom字段表示自定义类型，配置为具体的寄存器值，范围[0x1, 0x6E]。 * 配置的寄存器数最多不能超过8个，寄存器通过“,”区分开。 * 寄存器的值支持十六进制或十进制。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [op\_summary\_\*.csv](atlasprofiling_16_0067.html)  [db文件的TASK\_PMU\_INFO表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section72694413158) |
| --sys-hardware-mem=<sys-hardware-mem-value> | 可选 | 任务级别的片上内存采集开关，可选on或off，默认为off。  已知在安装有glibc<2.34的环境上采集memory数据，可能触发glibc的一个已知Bug 19329，通过升级环境的glibc版本可解决此问题。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品  不同产品支持情况不同，请以实际实现为准。 | [msprof\_\*.json中的NPU MEM层级](atlasprofiling_16_0075.html)  [npu\_module\_mem\_\*.csv](atlasprofiling_16_0076.html)  [db文件的NPU\_MODULE\_MEM表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section1612492317150)  [db文件的HBM表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section1045421312151)  [db文件的DDR表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section56231221154) |
| --sys-hardware-mem-freq=<sys-hardware-mem-freq-value> | 可选 | 任务级别的片上内存信息采集频率，范围[1,100]，默认值为50，单位Hz。  设置该参数需要**--sys-hardware-mem**参数设置为on。  说明：  对于以下产品，采集任务结束后，不建议用户增大采集频率，否则可能导致SoC传输带宽数据丢失。  Atlas 200I/500 A2 推理产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --l2=<l2-value> | 可选 | 采集L2 Cache的命中率，可选on或off，默认为off。   * Atlas 200I/500 A2 推理产品：分析AI Core命中L2次数推荐使用--aic-metrics=L2Cache。 * Atlas A2 训练系列产品/Atlas A2 推理系列产品：采集L2 Cache的命中率；分析AI Core命中L2次数推荐使用--aic-metrics=L2Cache。 * Atlas A3 训练系列产品/Atlas A3 推理系列产品：采集L2 Cache的命中率；分析AI Core命中L2次数推荐使用--aic-metrics=L2Cache。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [l2\_cache\_\*.csv](atlasprofiling_16_0073.html) |
| --ge-api=<ge-api-value> | 可选 | 采集动态Shape算子在Host调度阶段的耗时数据。相关数据生成在msprof\_\*.json和api\_statistic\_\*.csv文件中。  取值：   * off：关闭，默认off。 * l0：采集动态Shape算子在Host调度主要阶段的耗时数据，可更精准统计相关耗时数据。 * l1：采集动态Shape算子在Host调度阶段更细粒度的耗时数据，提供更全面的性能分析数据。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [msprof\_\*.json中的CANN层级和api\_statistic\_\*.csv文件](atlasprofiling_16_0063.html) |
| --task-memory=<task-memory-value> | 可选 | CANN算子级内存占用情况采集开关，用于优化内存使用。取值：   * on：开启 * off：关闭，默认为off   图模式单算子场景下，按照GE组件维度和算子维度采集算子内存大小及生命周期信息（单算子API执行场景不采集GE组件内存）；静态图和静态子图场景下，按照算子维度采集算子内存大小及生命周期信息。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | 图模式单算子场景生成：  [memory\_record\_\*.csv](atlasprofiling_16_0077.html)  [operator\_memory\_\*.csv](atlasprofiling_16_0078.html)  静态图和静态子图场景生成：  [static\_op\_mem\_\*.csv](atlasprofiling_16_0079.html)  [db文件的NPU\_OP\_MEM表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section138661911511) |

#### 使用示例（Ascend EP）

1. 登录CANN Toolkit开发套件包和ops算子包所在环境。
2. 在任意路径下执行以下命令，采集性能数据。

   ```
   msprof --output=/home/projects/output --ascendcl=on --runtime-api=on --task-time=on --aicpu=on --ai-core=on /home/projects/MyApp/out/main
   ```
3. 在--output指定的目录下生成PROF*\_*XXX目录，存放自动解析后的性能数据，相关结果文件请参见[表1](#ZH-CN_TOPIC_0000002534478433__table8963644175016)。

#### 使用示例（Ascend RC）

1. 登录运行环境。
2. 进入msprof工具所在目录“/var”，执行以下命令，采集性能数据。

   ```
   ./msprof --output=/home/projects/output --ascendcl=on --runtime-api=on --task-time=on --aicpu=on --ai-core=on /home/projects/MyApp/out/main
   ```
3. 在--output指定的目录下生成PROF*\_*XXX目录，该目录下的文件未经解析无法查看，您需要将PROF*\_*XXX目录上传到安装toolkit包的开发环境进行数据解析，具体操作方法请参见[离线解析](atlasprofiling_16_0018.html)，最终生成的结果文件请参见[表1](#ZH-CN_TOPIC_0000002534478433__table8963644175016)。

**父主题：** [性能数据采集和自动解析](atlasprofiling_16_0009.html)
