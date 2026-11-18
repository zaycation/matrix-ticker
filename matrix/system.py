"""Live PC stats for the dashboard. Every source is optional: missing ones return None.

- CPU load, RAM use: psutil
- GPU temperature / load / clock: NVIDIA's NVML (pip package nvidia-ml-py), NVIDIA cards only
CPU temperature and fan speeds need a hardware driver on Windows; not supported yet.
"""
try:
    import psutil
    psutil.cpu_percent(interval=None)        # first call primes the counter
except Exception:
    psutil = None

_nvml = None


def _gpu():
    global _nvml
    if _nvml is None:
        try:
            import pynvml
            pynvml.nvmlInit()
            _nvml = (pynvml, pynvml.nvmlDeviceGetHandleByIndex(0))
        except Exception:
            _nvml = False
    return _nvml or None


def cpu_load():
    return psutil.cpu_percent(interval=None) if psutil else None


def ram_used():
    return psutil.virtual_memory().percent if psutil else None


def gpu_temp():
    g = _gpu()
    if not g:
        return None
    try:
        nv, h = g
        return nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU)
    except Exception:
        return None


def gpu_load():
    g = _gpu()
    if not g:
        return None
    try:
        nv, h = g
        return nv.nvmlDeviceGetUtilizationRates(h).gpu
    except Exception:
        return None
