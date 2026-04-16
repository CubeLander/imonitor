# 采集昇腾AI处理器系统数据

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0012.html

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品 | √ |
| Atlas 训练系列产品 | √ |

#### 功能说明

msprof支持采集昇腾AI处理器的系统数据，并且在采集后可以自动进行性能数据解析和文件落盘。

#### 注意事项

* 请确保AI任务能在运行环境中正常运行。
* 请确保完成[使用前准备](atlasprofiling_16_0002.html)。

不支持采集Python调用栈、PyTorch或MindSpore框架层数据，可使用对应框架接口方式采集。

#### 命令示例（Ascend EP）

登录CANN Toolkit开发套件包和ops算子包所在环境，执行以下命令采集性能数据。命令示例如下：

```
msprof --output=/home/projects/output --sys-devices=<ID> --sys-period=<period> --ai-core=on --sys-hardware-mem=on --sys-cpu-profiling=on --sys-profiling=on --sys-pid-profiling=on --dvpp-profiling=on
```

命令支持的参数请参考[表1](#ZH-CN_TOPIC_0000002534478455__table1030212294288)。

采集昇腾AI处理器系统数据时：

* 不传入用户程序，表示仅采集昇腾AI处理器系统数据，此时**--output、****--sys-period、--sys-devices**参数必选。
* 若同时传入用户程序及昇腾AI处理器系统数据参数，此时**--sys-period**和**--sys-devices**参数不生效。

* Ascend EP场景下，使用msprof命令行方式采集整网推理Profiling数据时，如果通过配置**--llc-profiling**、**--sys-cpu-profiling**、**--sys-profiling**和**--sys-pid-profiling**采集项采集相应数据，采集完成后，除**--sys-cpu-profiling**采集项仅生成TS CPU数据外，其余采集项均不会生成数据；但在不传入用户程序时，配置上述几个采集项均会有数据生成。
* 对于Atlas A2 训练系列产品/Atlas A2 推理系列产品，--instr-profiling开关与--ascendcl、--model-execution、--runtime-api、--hccl、--task-time、--aicpu、--ai-core、--aic-mode、--aic-freq、--aic-metrics、--l2互斥，无法同时执行。
* 对于Atlas A3 训练系列产品/Atlas A3 推理系列产品，--instr-profiling开关与--ascendcl、--model-execution、--runtime-api、--hccl、--task-time、--aicpu、--ai-core、--aic-mode、--aic-freq、--aic-metrics、--l2互斥，无法同时执行。
* 对于以下产品，--sys-profiling、--sys-pid-profiling、--sys-cpu-profiling参数不支持同时采集共用OS的两个Device。例如：该产品的Device为[0,7]，但0和1、2和3、4和5、6和7分别共用OS，那么此时--sys-devices则不能同时配置0和1、2和3、4和5、6和7，可以配置0、2、4、6或1、3、5、7。
  + Atlas A3 训练系列产品/Atlas A3 推理系列产品

命令执行完成后，在--output指定的目录下生成PROF*\_*XXX目录，存放自动解析后的性能数据，相关结果文件请参见[表1](#ZH-CN_TOPIC_0000002534478455__table1030212294288)。

#### 命令示例（Ascend RC）

登录运行环境，进入msprof工具所在目录“/var”，执行以下命令采集性能数据。命令示例如下：

```
./msprof --output=/home/projects/output --sys-devices=<ID> --sys-period=<period> --ai-core=on --sys-hardware-mem=on --sys-cpu-profiling=on --sys-profiling=on --sys-pid-profiling=on
```

命令支持的参数请参考[表1](#ZH-CN_TOPIC_0000002534478455__table1030212294288)。

采集昇腾AI处理器系统数据时：

* 不传入用户程序，表示仅采集昇腾AI处理器系统数据，此时**--output、****--sys-period、--sys-devices**参数必选。
* 若同时传入用户程序及昇腾AI处理器系统数据参数，此时**--sys-period**和**--sys-devices**参数不生效。

命令执行完成后，在--output指定的目录下生成PROF*\_*XXX目录，该目录下的文件未经解析无法查看，您需要将PROF*\_*XXX目录上传到安装toolkit包的开发环境进行数据解析，具体操作方法请参见[离线解析](atlasprofiling_16_0018.html)，最终生成的结果文件请参见[表1](#ZH-CN_TOPIC_0000002534478455__table1030212294288)。

#### 参数说明

**表1** 参数说明

| 参数 | 说明 | 产品支持情况 | 性能数据文件 |
| --- | --- | --- | --- |
| --sys-period | 系统的采样时长，取值范围大于0，上限为30\*24\*3600，单位s。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --sys-devices | 设备ID。可以为all或多个设备ID（以逗号分隔）。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --ai-core | 控制AI Core、AI Vector Core数据采集的开关，可选on或off，默认值为off。相关采集项介绍请参考[op\_summary\_\*.csv](atlasprofiling_16_0067.html)中的说明。   * Atlas 200I/500 A2 推理产品：控制AI Core和AI Vector Core采集 * Atlas 推理系列产品：控制AI Core采集 * Atlas 训练系列产品：控制AI Core采集 * Atlas A2 训练系列产品/Atlas A2 推理系列产品：控制AI Core和AI Vector Core采集 * Atlas A3 训练系列产品/Atlas A3 推理系列产品：控制AI Core和AI Vector Core采集 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --aic-mode | AI Core、AI Vector Core硬件的采集类型，可选值task-based或sample-based。该参数配置前提是**--ai-core**参数设置为on。  task-based是以task为粒度进行性能数据采集，sample-based是以固定的时间周期进行性能数据采集。  采集昇腾AI处理器系统数据时建议使用sample-based，如果不配置默认为sample-based。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [msprof\_\*.json中的AI Core Utilization层级和ai\_core\_utilization\_\*.csv文件](atlasprofiling_16_0069.html)  [ai\_vector\_core\_utilization\_\*.csv](atlasprofiling_16_0070.html)  [db文件的SAMPLE\_PMU\_TIMELINE表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section166020382157)  [db文件的SAMPLE\_PMU\_SUMMARY表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section233113319159) |
| --aic-freq | sample-based场景下的采样频率，默认值100，范围1~100，单位Hz。该参数配置前提是**--****ai-core**参数设置为on。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --aic-metrics | AI Core、AI Vector Core性能指标采集项。该参数配置前提是**--ai-core**参数设置为on。  取值包括：   * Atlas 200I/500 A2 推理产品：ArithmeticUtilization、PipeUtilization、Memory、MemoryL0、MemoryUB、ResourceConflictRatio、L2Cache、PipelineExecuteUtilization（默认值） * Atlas 推理系列产品：ArithmeticUtilization、PipeUtilization（默认值）、Memory、MemoryL0、MemoryUB、ResourceConflictRatio * Atlas 训练系列产品：ArithmeticUtilization、PipeUtilization（默认值）、Memory、MemoryL0、MemoryUB、ResourceConflictRatio * Atlas A2 训练系列产品/Atlas A2 推理系列产品：ArithmeticUtilization、PipeUtilization（默认值）、Memory、MemoryL0、MemoryUB、ResourceConflictRatio、L2Cache、MemoryAccess * Atlas A3 训练系列产品/Atlas A3 推理系列产品：ArithmeticUtilization、PipeUtilization（默认值）、Memory、MemoryL0、MemoryUB、ResourceConflictRatio、L2Cache、MemoryAccess   说明：  支持自定义需要采集的寄存器，例如：--aic-metrics=**Custom:***0x49,0x8,0x15,0x1b,0x64,0x10。*  * Custom字段表示自定义类型，配置为具体的寄存器值，范围[0x1, 0x6E]。 * 配置的寄存器数最多不能超过8个，寄存器通过“,”区分开。 * 寄存器的值支持十六进制或十进制。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [msprof\_\*.json中的AI Core Utilization层级和ai\_core\_utilization\_\*.csv文件](atlasprofiling_16_0069.html)  [ai\_vector\_core\_utilization\_\*.csv](atlasprofiling_16_0070.html)  [db文件的SAMPLE\_PMU\_TIMELINE表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section166020382157)  [db文件的SAMPLE\_PMU\_SUMMARY表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section233113319159) |
| --sys-hardware-mem | 片上内存读写速率、QoS传输带宽、LLC读写速率/使用量/带宽（建议配合--llc-profiling使用）、Acc PMU数据和SoC传输带宽、组件内存占用等的采集开关，可选on或off，默认为off。  采集组件内存数据需要在采集AI任务性能数据（即传入用户程序）时才能采集到具体性能数据。  已知在安装有glibc<2.34的环境上采集memory数据，可能触发glibc的一个已知Bug 19329，通过升级环境的glibc版本可解决此问题。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品  不同产品支持情况不同，请以实际实现为准。 | [片上内存读写速率文件](atlasprofiling_16_0084.html)  [msprof\_\*.json中的LLC层级和llc\_read\_write\_\*.csv文件](atlasprofiling_16_0094.html)  [msprof\_\*.json中的acc\_pmu层级](atlasprofiling_16_0091.html)  [msprof\_\*.json中的Stars Soc Info层级](atlasprofiling_16_0092.html)  [msprof\_\*.json中的NPU MEM层级和npu\_mem\_\*.csv文件](atlasprofiling_16_0075.html)  [msprof\_\*.json中的QoS层级](atlasprofiling_16_0059.html#ZH-CN_TOPIC_0000002534478467__section7237154131716)  [npu\_module\_mem\_\*.csv](atlasprofiling_16_0076.html)（需传入用户程序）  [db文件的QOS表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section74321720145411)  [db文件的ACC\_PMU表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section68271524191613)  [db文件的SOC\_BANDWIDTH\_LEVEL表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section14551151619160)  [db文件的LLC表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section119051348181519)  [db文件的NPU\_MEM表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section29991927141518)  [db文件的NPU\_MODULE\_MEM表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section1612492317150)  [db文件的HBM表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section1045421312151)  [db文件的DDR表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section56231221154) |
| --sys-hardware-mem-freq | --sys-hardware-mem的采集频率，范围[1,100]，默认值为50，单位Hz。  设置该参数需要**--****sys-hardware-mem**参数设置为on。  说明：  对于以下产品，采集任务结束后，不建议用户增大采集频率，否则可能导致SoC传输带宽数据丢失。  Atlas 200I/500 A2 推理产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --llc-profiling | LLC Profiling采集事件，需要**--sys-hardware-mem**设置为on。取值包括：   * Atlas 200I/500 A2 推理产品：   + read：读事件，三级缓存读速率。   + write：写事件，三级缓存写速率。默认为read。 * Atlas 推理系列产品：   + read：读事件，三级缓存读速率。   + write：写事件，三级缓存写速率。默认为read。 * Atlas 训练系列产品：   + read：读事件，三级缓存读速率。   + write：写事件，三级缓存写速率。默认为read。 * Atlas A2 训练系列产品/Atlas A2 推理系列产品：   + read：读事件，三级缓存读速率。   + write：写事件，三级缓存写速率。默认为read。 * Atlas A3 训练系列产品/Atlas A3 推理系列产品：   + read：读事件，三级缓存读速率。   + write：写事件，三级缓存写速率。默认为read。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --sys-cpu-profiling | CPU（AI CPU、Ctrl CPU、TS CPU）采集开关。可选on或off，默认值为off。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [ai\_cpu\_top\_function\_\*.csv](atlasprofiling_16_0099.html)  [ai\_cpu\_pmu\_events\_\*.csv](atlasprofiling_16_0100.html)  [ctrl\_cpu\_top\_function\_\*.csv](atlasprofiling_16_0101.html)  [ctrl\_cpu\_pmu\_events\_\*.csv](atlasprofiling_16_0102.html)  [ts\_cpu\_top\_function\_\*.csv](atlasprofiling_16_0103.html)  [ts\_cpu\_pmu\_events\_\*.csv](atlasprofiling_16_0104.html) |
| --sys-cpu-freq | CPU采集频率，范围[1,50]，默认值为50，单位Hz。  设置该参数需要**--sys-cpu-profiling**参数设置为on。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --sys-profiling | 系统CPU usage及System memory采集开关。可选on或off，默认值为off。  说明：  使用该命令后，Profiling工具会调用Device侧的Perf工具，Perf仅执行相关性能数据采集，无法获取其他运行态信息，实际风险小。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [cpu\_usage\_\*.csv](atlasprofiling_16_0082.html)  [sys\_mem\_\*.csv](atlasprofiling_16_0080.html) |
| --sys-sampling-freq | 系统CPU usage及System memory采集频率，范围[1,10]，默认值为10，单位Hz。  设置该参数需要**--sys-profiling**参数设置为on。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --sys-pid-profiling | 所有进程的CPU usage及所有进程的memory采集开关。可选on或off，默认值为off。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [process\_cpu\_usage\_\*.csv](atlasprofiling_16_0083.html)  [process\_mem\_\*.csv](atlasprofiling_16_0081.html) |
| --sys-pid-sampling-freq | 所有进程的CPU usage及所有进程的memory采集频率，范围[1,10]，默认值为10，单位Hz。  设置该参数需要**--****sys-pid-profiling**参数设置为on。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --sys-io-profiling | NIC、ROCE、MAC采集开关。可选on或off，默认值为off。   * Atlas 200I/500 A2 推理产品：仅RC场景支持采集NIC，容器场景参数不生效 * Atlas 训练系列产品：支持采集NIC和ROCE * Atlas A2 训练系列产品/Atlas A2 推理系列产品：支持采集NIC、ROCE和MAC * Atlas A3 训练系列产品/Atlas A3 推理系列产品：支持采集NIC、ROCE和MAC | Atlas 200I/500 A2 推理产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [msprof\_\*.json中的NIC层级和nic\_\*.csv文件](atlasprofiling_16_0087.html)  [msprof\_\*.json中的RoCE层级和roce\_\*.csv文件](atlasprofiling_16_0088.html)  [db文件的NIC表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section65681562168)  [db文件的ROCE表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section1246285716152)  [db文件的NETDEV\_STATS表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section7238121863614) |
| --sys-io-sampling-freq | NIC、ROCE、MAC采集频率，范围[1,100]，默认值为100，单位Hz。  设置该参数需要**--sys-io-profiling**参数设置为on。 | Atlas 200I/500 A2 推理产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --sys-interconnection-profiling | 集合通信带宽数据（HCCS）、PCIe数据采集开关、片间传输带宽信息采集开关、SIO数据采集开关。可选on或off，默认值为off。   * Atlas 推理系列产品：支持采集PCIe数据 * Atlas 训练系列产品：支持采集HCCS、PCIe数据 * Atlas A2 训练系列产品/Atlas A2 推理系列产品：支持采集HCCS、PCIe数据、片间传输带宽信息 * Atlas A3 训练系列产品/Atlas A3 推理系列产品：支持采集HCCS、PCIe数据、片间传输带宽信息、SIO数据。 | Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [msprof\_\*.json中的PCIe层级和pcie\_\*.csv文件](atlasprofiling_16_0089.html)  [msprof\_\*.json中的HCCS层级和hccs\_\*.csv文件](atlasprofiling_16_0086.html)  [msprof\_\*.json中的Stars Chip Trans层级](atlasprofiling_16_0093.html)  [msprof\_\*.json中的SIO层级](atlasprofiling_16_0059.html#ZH-CN_TOPIC_0000002534478467__section18441122912161)  [db文件的HCCS表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section81241447141420)  [db文件的PCIE表](atlasprofiling_16_1144.html#ZH-CN_TOPIC_0000002534398437__section760424014146) |
| --sys-interconnection-freq | 集合通信带宽数据（HCCS）、PCIe数据采集频率、片间传输带宽信息采集频率、SIO数据采集频率，范围[1,50]，默认值为50，单位Hz。  设置该参数需要**--****sys-interconnection-profiling**参数设置为on。 | Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --dvpp-profiling | DVPP采集开关，可选on或off，默认值为off。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | Atlas 推理系列产品不支持解析该性能数据  [dvpp\_\*.csv](atlasprofiling_16_0098.html) |
| --dvpp-freq | DVPP采集频率，范围[1,100]，默认值为50，单位Hz。  设置该参数需要**--****dvpp-profiling**参数设置为on。 | Atlas 200I/500 A2 推理产品  Atlas 推理系列产品  Atlas 训练系列产品  Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |
| --instr-profiling | AI Core（包括AIC和AIV核）的带宽和时延采集开关，可选on或off，默认值为off。  需要在单算子场景下采集AI任务性能数据（即传入用户程序）时才能采集到具体性能数据。  Atlas A2 训练系列产品/Atlas A2 推理系列产品：仅单算子场景支持  Atlas A3 训练系列产品/Atlas A3 推理系列产品：仅单算子场景支持 | Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | [msprof\_\*.json中的biu\_group、aic\_core\_group、aiv\_core\_group层级](atlasprofiling_16_0090.html) |
| --instr-profiling-freq | AI Core（包括AIC和AIV核）的带宽和时延采样间隔，范围[300,30000]，默认值为1000，单位cycle。系统对AI Core带宽和延时的真实采集频率=处理器的运行频率/该参数取值，假设AI Core运行频率为5000Hz，该参数取值为1000，则最终采集频率为5Hz，即每秒钟采集5次。  该参数使用前需要**--instr-profiling**设置为on。 | Atlas A2 训练系列产品/Atlas A2 推理系列产品  Atlas A3 训练系列产品/Atlas A3 推理系列产品 | - |

**父主题：** [性能数据采集和自动解析](atlasprofiling_16_0009.html)
