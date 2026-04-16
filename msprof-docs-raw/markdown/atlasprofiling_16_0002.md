# 使用前准备

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0002.html

#### 使用约束

使用该工具前，请了解相关使用约束：

* 权限约束
  + 用户须自行保证使用最小权限原则（如禁止other用户可写，常见如禁止666、777）。
  + 使用性能分析工具前请确保执行用户的umask值大于等于0027，否则会导致获取的性能数据所在目录和文件权限过大。
  + 出于安全性及权限最小化角度考虑，本工具不应使用root等高权限账户，建议使用普通用户权限执行。
  + 本工具为开发调测工具，不建议在生产环境使用。
  + 本工具依赖CANN和对应驱动软件包，使用本工具前，请先安装CANN和对应驱动软件包，并使用**source**命令执行CANN的set\_env.sh环境变量文件，为保证安全，source后请勿擅自修改set\_env.sh中涉及的环境变量。
  + 请确保性能数据保存在不含软链接的当前用户目录下，否则可能引起安全问题。
* 执行约束
  + 不支持在同一个Device同时拉起多个采集任务。也不可同时开启两种及以上性能数据采集工具。
  + 不建议性能数据的采集功能与Dump功能同时使用。Dump操作会影响系统性能，如果同时开启采集功能与Dump功能，会造成采集的性能数据指标不准确，启动采集前请关闭数据Dump。
* 数据落盘约束
  + 性能数据采集时间建议在5min以内，并且预留至少20倍于性能原始数据大小的内存和磁盘空间。原始数据大小指采集落盘后的data目录下数据总大小。
  + 执行单个采集任务采集性能数据并落盘时，在打开所有采集项的情况下，需要保证磁盘读写速度，具体规格如下：
    - 仅使用单Device进行推理时，磁盘读写速度不低于50MB/s。
    - 仅使用单个Device进行训练时，磁盘读写速度不低于60MB/s。
    - 多个Device场景下，磁盘读写速度不低于：单个Device磁盘读写速度规格 \* Device数。
  + 采集性能数据过程中如果配置的落盘路径磁盘空间已满，会出现性能数据无法落盘情况，须保证足够的磁盘空间。落盘的性能原始数据可以通过配置--storage-limit参数来预防磁盘空间被占满。
  + 解析性能数据过程中如果配置的落盘路径磁盘或用户目录空间已满，会出现解析失败或文件无法落盘的情况，须自行清理磁盘或用户目录空间。
* 兼容性和场景约束
  + 工具要求Python 3.7.5及以上版本。
  + 应用工程开发务必遵循《应用开发指南 (C&C++)》手册，调用**aclInit()**接口完成初始化和调用**aclFinalize****()**接口完成去初始化，才能获取到完整的性能数据。

    如果应用程序已调用**aclInit()**接口而未调用**aclFinalize****()**接口导致工具采集流程未正常结束，采集数据会不完整。最后1秒内已采集的数据可能因未及时落盘而丢失，但丢失的数据不大于2M，不影响已落盘的性能数据分析。
  + 使用pyACL API开发的应用工程在通过msprof命令行方式采集性能数据时，不支持在工程Python脚本中打开相对路径文件。Python脚本中包含打开相对路径文件的操作会导致采集性能数据报错。
  + 昇腾虚拟化实例场景，支持的性能数据采集开关请参见[昇腾虚拟化实例场景性能数据采集开关支持情况](atlasprofiling_16_0003.html)。

#### 环境准备

1. 根据实际用户场景选择CANN相关软件包并安装，具体请参见《CANN 软件安装指南》。

   Ascend EP场景下msprof工具路径为：${INSTALL\_DIR}/tools/profiler/bin，${INSTALL\_DIR}请替换为CANN软件安装后文件存储路径。若安装的Ascend-cann-toolkit软件包，以root安装举例，则安装后文件存储路径为：/usr/local/Ascend/ascend-toolkit/latest。

   Ascend RC场景下msprof工具路径为：/var

   如果运行环境仅安装了Ascend-cann-nnae深度学习引擎包或Ascend-cann-nnrt离线推理引擎包，则需要[使用acl C&C++接口采集性能数据](atlasprofiling_16_0041.html)，然后将采集后的结果上传到安装Ascend-cann-toolkit开发套件包的开发环境，并参考[解析并导出性能数据](atlasprofiling_16_0021.html)执行解析和导出操作。
2. 设置公共环境变量。

   安装CANN软件后，使用CANN运行用户进行编译、运行时，需要以CANN运行用户登录环境，执行**source $*{install\_path}*/set\_env.sh**命令设置环境变量。其中${install\_path}为CANN软件的安装目录，例如：/usr/local/Ascend/ascend-toolkit。
3. 设置Python相关环境变量。

   存在多个Python3版本时，以指定python3.7.5为例，请根据实际修改。

   ```
   export PATH=/usr/local/python3.7.5/bin:$PATH
   #设置python3.7.5库文件路径
   export LD_LIBRARY_PATH=/usr/local/python3.7.5/lib:$LD_LIBRARY_PATH
   ```

上述环境变量只在当前窗口生效，用户可以将上述命令写入~/.bashrc文件，使其永久生效，操作如下：

1. 以安装用户在任意目录下执行**vi ~/.bashrc**，在该文件最后添加上述内容。
2. 执行**:wq!**命令保存文件并退出。
3. 执行**source ~/.bashrc**使环境变量生效。
