"""Live PC stats for the dashboard. Every source is optional: missing ones return None.

- CPU load, RAM use: psutil
- GPU temperature / load / VRAM / power / fan: NVIDIA's NVML (pip package nvidia-ml-py), NVIDIA cards only
CPU temperature and fan speeds need a hardware driver on Windows; not supported yet.
"""
import time
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


_cpu_last = (0.0, None)          # (time, per-core percents)


def _cpu_sample():
    """Per-core load since the previous sample. psutil measures "since the last call", so a
    second call right after the first would cover almost no time and read ~0: samples less
    than half a second apart reuse the last one."""
    global _cpu_last
    now = time.monotonic()
    if _cpu_last[1] is None or now - _cpu_last[0] >= 0.5:
        _cpu_last = (now, psutil.cpu_percent(interval=None, percpu=True))
    return _cpu_last[1]


def cpu_load():
    """Total CPU load, percent (the number Task Manager shows)."""
    if not psutil:
        return None
    cores = _cpu_sample()
    return sum(cores) / len(cores) if cores else None


def cpu_peak():
    """Load of the busiest core, percent. Games often max out one or two cores while the
    total stays low."""
    if not psutil:
        return None
    cores = _cpu_sample()
    return max(cores) if cores else None


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


def _frac(pct):
    return None if pct is None else pct / 100


TEMP_LO, TEMP_HI = 30, 90       # temperature meter scale, Celsius

# meter choice -> (label on the panel, function giving 0..1 or None)
CPU_METERS = {
    "load": ("CPU", lambda: _frac(cpu_load())),
    "peak": ("CPU", lambda: _frac(cpu_peak())),
    "ram": ("RAM", lambda: None if ram_used() is None else ram_used() / 100),
}
GPU_METERS = {
    "temp": ("GPU", lambda: None if gpu_temp() is None else (gpu_temp() - TEMP_LO) / (TEMP_HI - TEMP_LO)),
    "load": ("GPU", lambda: None if gpu_load() is None else gpu_load() / 100),
    "vram": ("GPU", lambda: None if gpu_vram() is None else gpu_vram() / 100),
    "power": ("GPU", lambda: None if gpu_power() is None else gpu_power() / 100),
    "fan": ("GPU", lambda: None if gpu_fan() is None else gpu_fan() / 100),
}
