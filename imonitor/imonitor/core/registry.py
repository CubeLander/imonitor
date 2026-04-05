from __future__ import annotations

from imonitor.config import MonitorConfig
from imonitor.sensors.base import Sensor
from imonitor.sensors.cpu_procfs import CPUProcfsSensor
from imonitor.sensors.gpu_nvml import GPUNvmlSensor
from imonitor.sensors.io_procfs import IOProcfsSensor
from imonitor.sensors.mem_procfs import MemoryProcfsSensor
from imonitor.sensors.net_procfs import NetProcfsSensor
from imonitor.sensors.proc_tree import ProcTreeSensor


def build_sensors(cfg: MonitorConfig) -> list[Sensor]:
    sensors: list[Sensor] = [
        ProcTreeSensor(),
        CPUProcfsSensor(),
        MemoryProcfsSensor(),
        IOProcfsSensor(),
    ]

    if cfg.enable_net:
        sensors.append(NetProcfsSensor())

    if cfg.enable_gpu:
        gpu = GPUNvmlSensor.create()
        if gpu is not None:
            sensors.append(gpu)
        else:
            print("[imonitor] gpu sensor disabled: pynvml/NVML unavailable")

    return sensors
