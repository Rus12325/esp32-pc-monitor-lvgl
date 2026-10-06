"""Чтение телеметрии ПК.

Основной источник — LibreHardwareMonitorLib.dll через pythonnet (netfx):
  полный набор (CPU/GPU/SSD/HDD/кулера) БЕЗ GUI LHM, WMI и прав администратора.
Если DLL не найдена/не загрузилась — откат на WMI-namespace LHM, затем на psutil.

Где лежит DLL: по умолчанию C:\\LHM, можно переопределить переменной окружения LHM_DIR.
"""
from __future__ import annotations
import os
import shutil
import subprocess

LHM_DIR = os.environ.get("LHM_DIR", r"C:\LHM")
_lib = None            # загруженный Computer-объект (singleton)
_lib_failed = False


# ================================================================== pythonnet
def _init_lib():
    global _lib, _lib_failed
    if _lib is not None or _lib_failed:
        return _lib
    dll = os.path.join(LHM_DIR, "LibreHardwareMonitorLib.dll")
    if not os.path.isfile(dll):
        _lib_failed = True
        return None
    try:
        import sys
        import pythonnet
        pythonnet.Runtime = "netfx"
        if LHM_DIR not in sys.path:
            sys.path.append(LHM_DIR)
        import clr
        from System.Reflection import Assembly
        Assembly.LoadFrom(dll)
        clr.AddReference("LibreHardwareMonitorLib")
        from LibreHardwareMonitor.Hardware import Computer
        c = Computer()
        c.IsCpuEnabled = True
        c.IsGpuEnabled = True
        c.IsStorageEnabled = True
        c.IsMotherboardEnabled = True
        c.IsControllerEnabled = True
        c.Open()
        _lib = c
    except Exception as e:
        print("LHM-lib недоступен:", e)
        _lib_failed = True
        _lib = None
    return _lib


def _read_lib() -> dict | None:
    c = _init_lib()
    if c is None:
        return None
    try:
        from LibreHardwareMonitor.Hardware import HardwareType  # noqa
    except Exception:
        pass
    data: dict = {"storage": [], "fans": []}

    def update_all():
        for hw in c.Hardware:
            hw.Update()
            for sub in hw.SubHardware:
                sub.Update()

    update_all()

    cpu_t = cpu_t_alt = cpu_load = None
    gpu_t = gpu_load = None

    for hw in c.Hardware:
        htype = str(hw.HardwareType)   # Cpu/GpuNvidia/GpuAmd/PersistentStorage/Motherboard/...
        hname = hw.Name
        for s in hw.Sensors:
            st = str(s.SensorType)     # Temperature/Load/Fan
            nm = (s.Name or "").lower()
            val = s.Value
            if val is None:
                continue
            val = float(val)

            if htype == "Cpu":
                if st == "Temperature":
                    if "package" in nm or "tdie" in nm or "tctl" in nm:
                        cpu_t = val if cpu_t is None else cpu_t
                    elif cpu_t_alt is None:
                        cpu_t_alt = val
                elif st == "Load" and "total" in nm:
                    cpu_load = val
            elif htype in ("GpuNvidia", "GpuAmd", "GpuIntel"):
                if st == "Temperature" and ("core" in nm or gpu_t is None):
                    gpu_t = val
                elif st == "Load" and gpu_load is None and ("core" in nm or "d3d" in nm):
                    gpu_load = val
                elif st == "Fan":
                    data["fans"].append({"name": "GPU", "rpm": int(val)})
            elif htype in ("PersistentStorage", "ExternalStorage", "Memory"):
                if st == "Temperature" and "temperature" in nm:
                    data["storage"].append({"name": (hname or "Disk")[:8], "t": round(val, 1)})
            else:  # Motherboard / Controller — корпусные кулеры
                if st == "Fan" and "gpu" not in nm:
                    data["fans"].append({"name": (s.Name or "Fan")[:8], "rpm": int(val)})

    if cpu_t is None and cpu_t_alt is not None:
        cpu_t = cpu_t_alt
    if cpu_t is None and cpu_load is None and gpu_t is None and not data["storage"]:
        return None

    if cpu_load is not None and cpu_t is None:
        data["cpu"] = {"t": 0.0, "load": round(cpu_load, 1)}
    elif cpu_t is not None:
        data["cpu"] = {"t": round(cpu_t, 1), "load": round(cpu_load or 0.0, 1)}
    if gpu_t is not None:
        data["gpu"] = {"t": round(gpu_t, 1), "load": round(gpu_load or 0.0, 1)}
    return data


# ================================================================== WMI fallback
def _read_lhm_wmi() -> dict | None:
    try:
        import wmi
        c = wmi.WMI(namespace="root/LibreHardwareMonitor")
        sensors = c.Sensor()
    except Exception:
        return None
    data: dict = {"storage": [], "fans": []}
    cpu_t = cpu_load = gpu_t = gpu_load = None
    for s in sensors:
        st = getattr(s, "SensorType", ""); ident = (getattr(s, "Identifier", "") or "").lower()
        nm = (getattr(s, "Name", "") or "").lower(); val = getattr(s, "Value", None)
        if val is None: continue
        val = float(val)
        if st == "Temperature":
            if "cpu" in ident and (cpu_t is None or "package" in nm): cpu_t = val
            elif "gpu" in ident and "core" in nm: gpu_t = val
            elif any(k in ident for k in ("hdd","ssd","nvme")) and "temperature" in nm:
                data["storage"].append({"name": nm[:8], "t": round(val,1)})
        elif st == "Load" and "cpu" in ident and "total" in nm: cpu_load = val
        elif st == "Load" and "gpu" in ident and "core" in nm: gpu_load = val
        elif st == "Fan":
            data["fans"].append({"name": (getattr(s,'Name',None) or 'Fan')[:8], "rpm": int(val)})
    if cpu_t is None and gpu_t is None and not data["storage"]:
        return None
    if cpu_t is not None: data["cpu"] = {"t": round(cpu_t,1), "load": round(cpu_load or 0,1)}
    if gpu_t is not None: data["gpu"] = {"t": round(gpu_t,1), "load": round(gpu_load or 0,1)}
    return data


# ================================================================== psutil fallback
def _read_psutil() -> dict:
    import psutil
    data: dict = {"storage": [], "fans": [], "cpu": {"t": 0.0, "load": round(psutil.cpu_percent(), 1)}}
    try:
        exe = shutil.which("nvidia-smi")
        if exe:
            out = subprocess.check_output([exe, "--query-gpu=temperature.gpu,utilization.gpu",
                                           "--format=csv,noheader,nounits"], timeout=3, text=True).strip()
            t, u = out.split(",")
            data["gpu"] = {"t": float(t), "load": float(u)}
    except Exception:
        pass
    return data


def read_telemetry() -> dict:
    d = _read_lib()
    if d: return d
    d = _read_lhm_wmi()
    if d: return d
    return _read_psutil()


if __name__ == "__main__":
    import json, time
    for _ in range(5):
        print(json.dumps(read_telemetry(), ensure_ascii=False))
        time.sleep(1)
