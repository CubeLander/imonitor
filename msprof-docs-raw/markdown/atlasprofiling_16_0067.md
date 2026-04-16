# op\_summary（算子详细信息）

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0067.html

AI Core、AI Vector Core和AI CPU算子汇总信息无timeline信息，summary信息在op\_summary\_\*.csv文件汇总，用于统计算子的具体信息和耗时情况。

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

#### op\_summary\_\*.csv文件说明

op\_summary\_\*.csv文件内容格式示例如下：

**图1** op\_summary（仅为示例）

Task Duration字段为算子耗时信息，可以按照Task Duration排序，找出高耗时算子；也可以按照Task Type排序，查看AI Core或AI CPU上运行的高耗时算子。

* 下文字段说明中，不同产品支持的字段略有不同，请以实际结果文件呈现字段为准。
* task\_time配置为l0或off时，op\_summary\_\*.csv不呈现AI Core、AI Vector Core的PMU数据。
* Atlas A2 训练系列产品
  /
  Atlas A2 推理系列产品
  ：MatMul算子的输入a、b矩阵满足：内轴大于1000，MAC理论计算耗时大于50us，内轴大小非516B对齐时，MatMul会转化为MIX算子，此时op\_summary.csv中的MatMul算子数量减少且Task Type由原来的AI\_Core转变为MIX\_AIC。
* Atlas A3 训练系列产品
  /
  Atlas A3 推理系列产品
  ：MatMul算子的输入a、b矩阵满足：内轴大于1000，MAC理论计算耗时大于50us，内轴大小非516B对齐时，MatMul会转化为MIX算子，此时op\_summary.csv中的MatMul算子数量减少且Task Type由原来的AI\_Core转变为MIX\_AIC。
* 对于部分算子，执行时间过长，导致metric相关数据失准，不再具有参考意义，此类数据统一置为N/A，不做相关呈现。
* 由于Task Type为communication类型的算子通常包含一系列通信任务，每个通信任务均有独立的Task ID和Stream ID等标识，此处不作展示，因此该类算子的Task ID和Stream ID为N/A。
* 算子的输入维度Input Shapes取值为空，即表示为“; ; ; ;”格式时，表示当前输入的为标量，其中“;”为每个维度的分隔符。算子的输出维度同理。
* 工具会检测算子溢出情况，若发现算子溢出，则提示如下告警，此时该算子的计算结果不可信。

  **图2** 算子溢出告警

op\_summary\_\*.csv文件根据参数取值不同，文件呈现结果不同。完整字段如下。

**表1** 公共字段说明

| 字段名 | 字段含义 |
| --- | --- |
| Device\_id | 设备ID。 |
| Model Name | 模型名称。如果Model Name值为空，则可能由于获取的数据中该值为空。（默认情况下或单算子场景不显示该字段） |
| Model ID | 模型ID。 |
| Task ID | Task任务的ID。 |
| Stream ID | 该Task所处的Stream ID。 |
| Infer ID | 标识第几轮推理数据。（默认情况下或单算子场景不显示该字段） |
| Op Name | 算子名称。 |
| OP Type | 算子类型。task\_time为l0时，不采集该字段，显示为N/A。 |
| OP State | 算子的动静态信息，dynamic表示动态算子，static表示静态算子，通信算子无该状态显示为N/A，该字段仅在--task-time=l1情况下上报，--task-time=l0时显示为N/A。 |
| Task Type | 执行该Task的加速器类型，包含AI\_CORE、AI\_VECTOR\_CORE、AI\_CPU等。task\_time为l0时，不采集该字段，显示为N/A。 |
| Task Start Time(us) | Task开始时间，单位us。 |
| Task Duration(us) | Task耗时，包含调度到加速器的时间、加速器上的执行时间以及结束响应时间，单位us。 |
| Task Wait Time(us) | 上一个Task的结束时间与当前Task的开始时间间隔，单位us。 |
| Block Dim | Task运行切分数量，对应Task运行时核数。task\_time为l0时，不采集该字段，显示为0。 |
| HF32 Eligible | 标识是否使用HF32精度标记，YES表示使用，NO表示未使用，该字段仅在--task-time=l1情况下上报，--task-time=l0时显示为N/A。 |
| Mix Block Dim | 部分算子同时在AI Core和Vector Core上执行，主加速器的Block Dim在Block Dim字段描述，从加速器的Block Dim在本字段描述。task\_time为l0时，不采集该字段，显示为N/A。（ Atlas 200I/500 A2 推理产品 ）（ Atlas A2 训练系列产品 / Atlas A2 推理系列产品 ）（ Atlas A3 训练系列产品 / Atlas A3 推理系列产品 ） |
| Input Shapes | 算子的输入维度。task\_time为l0时，不采集该字段，显示为N/A。 |
| Input Data Types | 算子输入数据类型。task\_time为l0时，不采集该字段，显示为N/A。 |
| Input Formats | 算子输入数据格式。task\_time为l0时，不采集该字段，显示为N/A。 |
| Output Shapes | 算子的输出维度。task\_time为l0时，不采集该字段，显示为N/A。 |
| Output Data Types | 算子输出数据类型。task\_time为l0时，不采集该字段，显示为N/A。 |
| Output Formats | 算子输出数据格式。task\_time为l0时，不采集该字段，显示为N/A。 |
| Context ID | Context ID，用于标识Sub Task粒度的小算子，不存在小算子时显示为N/A。（ Atlas 200I/500 A2 推理产品 ）（ Atlas A2 训练系列产品 / Atlas A2 推理系列产品 ）（ Atlas A3 训练系列产品 / Atlas A3 推理系列产品 ） |
| aiv\_time(us) | 当所有的Block被同时调度，且每个Block的执行时长相等时，该Task在AI Vector Core上的理论执行时间，单位us。通常情况下，不同的Block开始调度时间略有差距，故该字段值略小于Task在AI Vector Core上的实际执行时间。（ Atlas A2 训练系列产品 / Atlas A2 推理系列产品 ）（ Atlas A3 训练系列产品 / Atlas A3 推理系列产品 ）  --task-time=l1、--aic-mode=task-based时生成。 |
| aicore\_time(us) | 当所有的Block被同时调度，且每个Block的执行时长相等时，该Task在AI Core上的理论执行时间，单位us。通常情况下，不同的Block开始调度时间略有差距，故该字段值略小于Task在AI Core上的实际执行时间。  当AI Core频率变化（比如进行手动调频、功耗超出阈值时动态调频以及Atlas 300V/Atlas 300I Pro产品）时该数据不准确，不建议参考。  Atlas 200I/500 A2 推理产品 ：具体频率变化点请参考[查看AI Core频率](atlasprofiling_16_0059.html#ZH-CN_TOPIC_0000002534478467__section9194165318231)。  Atlas A2 训练系列产品 / Atlas A2 推理系列产品 ：具体频率变化点请参考[查看AI Core频率](atlasprofiling_16_0059.html#ZH-CN_TOPIC_0000002534478467__section9194165318231)。  Atlas A3 训练系列产品 / Atlas A3 推理系列产品 ：具体频率变化点请参考[查看AI Core频率](atlasprofiling_16_0059.html#ZH-CN_TOPIC_0000002534478467__section9194165318231)。  --task-time=l1、--aic-mode=task-based时生成。 |
| total\_cycles | 该Task在AI Core上执行的cycle总数，由所有的Block的执行cycle数累加而成。  --task-time=l1、--aic-mode=task-based时生成。  对于 Atlas 200I/500 A2 推理产品 拆分为aic\_total\_cycles（该Task在AI Cube Core上执行的cycle总数）和aiv\_total\_cycles（该Task在AI Vector Core上执行的cycle总数）。  对于 Atlas A2 训练系列产品 / Atlas A2 推理系列产品 拆分为aic\_total\_cycles（该Task在AI Cube Core上执行的cycle总数）和aiv\_total\_cycles（该Task在AI Vector Core上执行的cycle总数）。  对于 Atlas A3 训练系列产品 / Atlas A3 推理系列产品 拆分为aic\_total\_cycles（该Task在AI Cube Core上执行的cycle总数）和aiv\_total\_cycles（该Task在AI Vector Core上执行的cycle总数）。 |
| 寄存器值 | 自定义采集的寄存器的数值。由--aic-metrics配置自定义寄存器控制。 |

下列字段均在--task-time=l1、--aic-mode=task-based时生成，--task-time为l0时，不采集该字段，显示为N/A。生成的数据由aic\_metrics参数取值控制。

**表2** 字段说明（PipeUtilization）

| 字段名 | 字段含义 |
| --- | --- |
| \*\_vec\_time(us) | vec类型指令（向量类运算指令）耗时，单位us。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| \*\_vec\_ratio | vec类型指令（向量类运算指令）的cycle数在total cycle数中的占用比。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| \*\_mac\_time(us) | cube类型指令（矩阵类运算指令）耗时，单位us。 |
| \*\_mac\_ratio | cube类型指令（矩阵类运算指令）的cycle数在total cycle数中的占用比。 |
| \*\_scalar\_time(us) | scalar类型指令（标量类运算指令）耗时，单位us。 |
| \*\_scalar\_ratio | scalar类型指令（标量类运算指令）的cycle数在total cycle数中的占用比。 |
| aic\_fixpipe\_time(us) | fixpipe类型指令（L0C->OUT/L1搬运类指令）耗时，单位us。 |
| aic\_fixpipe\_ratio | fixpipe类型指令（L0C->OUT/L1搬运类指令）的cycle数在total cycle数中的占用比。 |
| \*\_mte1\_time(us) | mte1类型指令（L1->L0A/L0B搬运类指令）耗时，单位us。 |
| \*\_mte1\_ratio | mte1类型指令（L1->L0A/L0B搬运类指令）的cycle数在total cycle数中的占用比。 |
| \*\_mte2\_time(us) | mte2类型指令（DDR->AICORE搬运类指令）耗时，单位us。 |
| \*\_mte2\_ratio | mte2类型指令（DDR->AICORE搬运类指令）的cycle数在total cycle数中的占用比。 |
| \*\_mte3\_time(us) | mte3类型指令（AICORE->DDR搬运类指令）耗时，单位us。 |
| \*\_mte3\_ratio | mte3类型指令（AICORE->DDR搬运类指令）的cycle数在total cycle数中的占用比。 |
| \*\_icache\_miss\_rate | icache是为instruction预留的L2 Cache，icache\_miss\_rate数值高代表AI Core读取指令的效率低。 |
| memory\_bound | 用于识别AICore执行算子计算过程是否存在Memory瓶颈，由mte2\_ratio/max(mac\_ratio, vec\_ratio)计算得出。计算结果小于1，表示没有Memory瓶颈；计算结果大于1则表示AI Core在执行Task过程中大部分时间都在做内存搬运而不是计算，且数值越大Memory瓶颈越严重。 |
| cube\_utilization(%) | cube算子利用率，查看cube算子在单位时间内的运算次数是否达到理论上限，越接近于100%则表示越接近理论上限。计算公式：cube\_utilization=total\_cycles / (freq \* core\_num \* task\_duration)。 |
| 注：对于部分产品，部分字段在该表中使用\*前缀指代aic或aiv，表示该数据是在Cube Core或Vector Core上执行的结果。 | |

**表3** 字段说明（ArithmeticUtilization）

| 字段名 | 字段含义 |
| --- | --- |
| \*\_mac\_fp16\_ratio | cube fp16类型指令的cycle数在total cycle数中的占用比。 |
| \*\_mac\_int8\_ratio | cube int8类型指令的cycle数在total cycle数中的占用比。 |
| \*\_vec\_fp32\_ratio | vec fp32类型指令的cycle数在total cycle数中的占用比。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| \*\_vec\_fp16\_ratio | vec fp16类型指令的cycle数在total cycle数中的占用比。 |
| \*\_vec\_int32\_ratio | vec int32类型指令的cycle数在total cycle数中的占用比。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| \*\_vec\_misc\_ratio | vec misc类型指令的cycle数在total cycle数中的占用比。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| \*\_cube\_fops | cube类型的浮点运算数，即计算量，可用于衡量算法/模型的复杂度，其中fops表示floating point operations，缩写为FLOPs。 |
| \*\_vector\_fops | vector类型浮点运算数，即计算量，可用于衡量算法/模型的复杂度，其中fops表示floating point operations，缩写为FLOPs。 |
| 注：对于部分产品，部分字段在该表中使用\*前缀指代aic或aiv，表示该数据是在Cube Core或Vector Core上执行的结果。 | |

**表4** 字段说明（Memory）

| 字段名 | 字段含义 |
| --- | --- |
| \*\_ub\_read\_bw(GB/s) | ub读带宽速率，单位GB/s。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| \*\_ub\_write\_bw(GB/s) | ub写带宽速率，单位GB/s。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| \*\_l1\_read\_bw(GB/s) | l1读带宽速率，单位GB/s。 |
| \*\_l1\_write\_bw(GB/s) | l1写带宽速率，单位GB/s。 |
| \*\_l2\_read\_bw | l2读带宽速率，单位GB/s。 |
| \*\_l2\_write\_bw | l2写带宽速率，单位GB/s。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| \*\_main\_mem\_read\_bw(GB/s) | 主存储器读带宽速率，单位GB/s。 |
| \*\_main\_mem\_write\_bw(GB/s) | 主存储器写带宽速率，单位GB/s。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| 注：对于部分产品，部分字段在该表中使用\*前缀指代aic或aiv，表示该数据是在Cube Core或Vector Core上执行的结果。 | |

**表5** 字段说明（MemoryL0）

| 字段名 | 字段含义 |
| --- | --- |
| \*\_l0a\_read\_bw(GB/s) | l0a读带宽速率，单位GB/s。 |
| \*\_l0a\_write\_bw(GB/s) | l0a写带宽速率，单位GB/s。 |
| \*\_l0b\_read\_bw(GB/s) | l0b读带宽速率，单位GB/s。 |
| \*\_l0b\_write\_bw(GB/s) | l0b写带宽速率，单位GB/s。 |
| \*\_l0c\_read\_bw(GB/s) | vector从l0c读带宽速率，单位GB/s。 |
| \*\_l0c\_write\_bw(GB/s) | vector向l0c写带宽速率，单位GB/s。 |
| \*\_l0c\_read\_bw\_cube(GB/s) | cube从l0c读带宽速率，单位GB/s。 |
| \*\_l0c\_write\_bw\_cube(GB/s) | cube向l0c写带宽速率，单位GB/s。 |
| 注：采集AI Vector Core的MemoryL0性能指标时，采集到的数据都为0。  注：对于部分产品，部分字段在该表中使用\*前缀指代aic或aiv，表示该数据是在Cube Core或Vector Core上执行的结果。 | |

**表6** 字段说明（MemoryUB）

| 字段名 | 字段含义 |
| --- | --- |
| \*\_ub\_read\_bw\_vector(GB/s) | vector从ub读带宽速率，单位GB/s。 |
| \*\_ub\_write\_bw\_vector(GB/s) | vector向ub写带宽速率，单位GB/s。 |
| \*\_ub\_read\_bw\_scalar(GB/s) | scalar从ub读带宽速率，单位GB/s。 |
| \*\_ub\_write\_bw\_scalar(GB/s) | scalar向ub写带宽速率，单位GB/s。 |
| 注：对于部分产品，部分字段在该表中使用\*前缀指代aic或aiv，表示该数据是在Cube Core或Vector Core上执行的结果。 | |

**表7** 字段说明（ResourceConflictRatio）

| 字段名 | 字段含义 |
| --- | --- |
| \*\_vec\_bankgroup\_cflt\_ratio | vec\_bankgroup\_stall\_cycles类型指令执行cycle数在total cycle数中的占用比。由于vector指令的block stride的值设置不合理，造成bankgroup冲突。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| \*\_vec\_bank\_cflt\_ratio | vec\_bank\_stall\_cycles类型指令执行cycle数在total cycle数中的占用比。由于vector指令操作数的读写指针地址不合理，造成bank冲突。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| \*\_vec\_resc\_cflt\_ratio | vec\_resc\_cflt\_ratio类型指令执行cycle数在total cycle数中的占用比。当算子中涉及多个计算单元，应该尽量保证多个单元并发调度。当某个计算单元正在执行计算，但算子逻辑仍然往该单元下发指令，就会造成整体的算力没有得到充分应用。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| 注：对于部分产品，部分字段在该表中使用\*前缀指代aic或aiv，表示该数据是在Cube Core或Vector Core上执行的结果。 | |

**表8** 字段说明（MemoryAccess）

| 字段名 | 字段含义 |
| --- | --- |
| \*\_read\_main\_memory\_datas(KB) | 对片上内存读的数据量，单位KB。 |
| \*\_write\_main\_memory\_datas(KB) | 对片上内存写的数据量，单位KB。 |
| \*\_GM\_to\_L1\_datas(KB) | GM到L1的数据搬运量，单位KB。 |
| \*\_L0C\_to\_L1\_datas(KB) | L0C到L1的数据搬运量，单位KB。 |
| \*\_L0C\_to\_GM\_datas(KB) | L0C到GM的数据搬运量，单位KB。 |
| \*\_GM\_to\_UB\_datas(KB) | GM到UB的数据搬运量，单位KB。 |
| \*\_UB\_to\_GM\_datas(KB) | UB到GM的数据搬运量，单位KB。 |
| 注：上表中字段的\*前缀，指代aic或aiv，表示该数据是在Cube Core或Vector Core上执行的结果。  仅支持产品：  Atlas A2 训练系列产品 / Atlas A2 推理系列产品  Atlas A3 训练系列产品 / Atlas A3 推理系列产品 | |

**表9** 字段说明（L2Cache）

| 字段名 | 字段含义 |
| --- | --- |
| \*\_write\_cache\_hit | 写cache命中的次数。 |
| \*\_write\_cache\_miss\_allocate | 写cache缺失后重新分配缓存的次数。 |
| \*\_r\*\_read\_cache\_hit | 读r\*通道cache命中次数。 |
| \*\_r\*\_read\_cache\_miss\_allocate | 读r\*通道cache缺失后重新分配的次数。 |
| 注：对于部分产品，部分字段在该表中使用\*前缀指代aic或aiv，表示该数据是在Cube Core或Vector Core上执行的结果。  仅支持产品：  Atlas A2 训练系列产品 / Atlas A2 推理系列产品  Atlas A3 训练系列产品 / Atlas A3 推理系列产品  Atlas 200I/500 A2 推理产品 | |

**表10** 字段说明（PipelineExecuteUtilization）

| 字段名 | 字段含义 |
| --- | --- |
| vec\_exe\_time(us) | vec类型指令（向量类运算指令）耗时，单位us。 |
| vec\_exe\_ratio | vec类型指令（向量类运算指令）的cycle数在total cycle数中的占用比。 Atlas 200I/500 A2 推理产品 不支持该字段，给予默认值N/A。 |
| mac\_exe\_time(us) | cube类型指令（fp16及s16矩阵类运算指令）耗时，单位us。 |
| mac\_exe\_ratio | cube类型指令（fp16及s16矩阵类运算指令）的cycle数在total cycle数中的占用比。 |
| scalar\_exe\_time(us) | scalar类型指令（标量类运算指令）耗时，单位us。 |
| scalar\_exe\_ratio | scalar类型指令（标量类运算指令）的cycle数在total cycle数中的占用比。 |
| mte1\_exe\_time(us) | mte1类型指令（L1->L0A/L0B搬运类指令）耗时，单位us。 |
| mte1\_exe\_ratio | mte1类型指令（L1->L0A/L0B搬运类指令）的cycle数在total cycle数中的占用比。 |
| mte2\_exe\_time(us) | mte2类型指令（DDR->AICORE搬运类指令）耗时，单位us。 |
| mte2\_exe\_ratio | mte2类型指令（DDR->AICORE搬运类指令）的cycle数在total cycle数中的占用比。 |
| mte3\_exe\_time(us) | mte3类型指令（AICORE->DDR搬运类指令）耗时，单位us。 |
| mte3\_exe\_ratio | mte3类型指令（AICORE->DDR搬运类指令）的cycle数在total cycle数中的占用比。 |
| fixpipe\_exe\_time(us) | fixpipe类型指令（L0C->OUT/L1搬运类指令）耗时，单位us。 |
| fixpipe\_exe\_ratio | fixpipe类型指令（L0C->OUT/L1搬运类指令）的cycle数在total cycle数中的占用比。 |
| memory\_bound | 用于识别AICore执行算子计算过程是否存在Memory瓶颈，由mte2\_ratio/max(mac\_ratio, vec\_ratio)计算得出。计算结果小于1，表示没有Memory瓶颈；计算结果大于1则表示AI Core在执行Task过程中大部分时间都在做内存搬运而不是计算，且数值越大Memory瓶颈越严重。 |
| cube\_utilization(%) | cube算子利用率，查看cube算子在单位时间内的运算次数是否达到理论上限，越接近于100%则表示越接近理论上限。计算公式：cube\_utilization=total\_cycles / (freq \* core\_num \* task\_duration)。 |

**父主题：** [性能数据文件参考](atlasprofiling_16_0056.html)
