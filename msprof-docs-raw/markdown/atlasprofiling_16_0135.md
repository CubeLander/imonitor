# 安装perf、iotop、ltrace工具

- Source: https://www.hiascend.com/document/detail/zh/canncommercial/850/devaids/Profiling/atlasprofiling_16_0135.html

perf、iotop、ltrace为第三方工具，以下安装方式仅为示例，请用户根据实际环境自行适配。

* Ubuntu 20.04操作系统，执行以下命令安装。
  + iotop工具安装方法：

    ```
    apt-get install iotop
    ```
  + perf工具安装方法：

    ```
    apt-get install linux-tools-common
    ```

    安装完成后执行perf命令，根据系统提示继续使用apt-get install安装linux-tools-x和linux-cloud-x。
  + ltrace工具安装方法：

    ```
    apt-get install ltrace
    ```
* Ubuntu 18.04操作系统，执行以下命令安装。
  + iotop工具安装方法：

    此处以python3为例进行介绍，若用户使用其他版本Python，请自行适配。

    ```
    wget http://guichaz.free.fr/iotop/files/iotop-0.6.tar.bz2
    tar -xvf iotop-0.6.tar.bz2
    cd iotop-0.6
    sed -i 's/itervalues/values/g' setup.py
    python3 setup.py build
    python3 setup.py install
    ln -s /usr/local/python3/sbin/iotop /usr/sbin/iotop
    ln -s /usr/local/python3/bin/iotop /usr/bin/iotop
    ```
  + perf工具安装方法：

    ```
    apt-get install linux-tools-common
    ```

    安装完成后执行perf命令，根据系统提示继续使用apt-get install安装linux-tools-x和linux-cloud-x。
  + ltrace工具安装方法：

    ```
    apt-get install ltrace
    ```
* CentOS 7.6、EulerOS、OpenEuler20.03、OpenEuler22.03和x86\_64架构的KylinV10SP1操作系统，执行以下命令安装。

  ```
  yum install perf iotop ltrace
  ```

* ARM架构的KylinV10SP1操作系统仅需要安装iotop工具，执行以下命令安装。

  ```
  yum install iotop
  ```

* 以上命令以root用户为例，非root用户请在命令行前加**sudo**。
* iotop工具不支持在容器内使用。
* 完成安装perf、iotop、ltrace工具后，需要[配置用户权限](atlasprofiling_16_0137.html)。

**父主题：** [附录](atlasprofiling_16_0135.html)
