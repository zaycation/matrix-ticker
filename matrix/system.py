"""Live PC stats for the dashboard. Every source is optional: missing ones return None.

- CPU load, RAM use: psutil
- GPU temperature / load / VRAM / power / fan: NVIDIA's NVML (pip package nvidia-ml-py), NVIDIA cards only
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


def _nv(fn):
    g = _gpu()
    if not g:
        return None
    try:
        return fn(*g)
    except Exception:
        return None


def gpu_vram():
    """Video memory used, percent."""
    def f(nv, h):
        m = nv.nvmlDeviceGetMemoryInfo(h)
        return 100 * m.used / m.total
    return _nv(f)


def gpu_power():
    """Power draw as a percent of the card's power limit."""
    return _nv(lambda nv, h: 100 * nv.nvmlDeviceGetPowerUsage(h) / nv.nvmlDeviceGetEnforcedPowerLimit(h))


def gpu_fan():
    """Fan speed, percent of max (0 when the fans are stopped at idle)."""
    return _nv(lambda nv, h: nv.nvmlDeviceGetFanSpeed(h))


TEMP_LO, TEMP_HI = 30, 90       # temperature meter scale, Celsius

# meter choice -> (label on the panel, function giving 0..1 or None)
CPU_METERS = {
    "load": ("CPU", lambda: None if cpu_load() is None else cpu_load() / 100),
    "ram": ("RAM", lambda: None if ram_used() is None else ram_used() / 100),
}
GPU_METERS = {
    "temp": ("GPU", lambda: None if gpu_temp() is None else (gpu_temp() - TEMP_LO) / (TEMP_HI - TEMP_LO)),
    "load": ("GPU", lambda: None if gpu_load() is None else gpu_load() / 100),
    "vram": ("GPU", lambda: None if gpu_vram() is None else gpu_vram() / 100),
    "power": ("GPU", lambda: None if gpu_power() is None else gpu_power() / 100),
    "fan": ("GPU", lambda: None if gpu_fan() is None else gpu_fan() / 100),
}
