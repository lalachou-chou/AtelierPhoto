"""How much of the computer an import or a training may use.

The three loads only change speed, never results: photos are prepared in
parallel threads, but stored in their original order with the same model.
"""
import ctypes
import os
import sys
from dataclasses import dataclass

MODES = {
    "fast": "Rapide",
    "balanced": "Équilibrée",
    "light": "Discrète",
}
DEFAULT_MODE = "fast"
DESCRIPTIONS = {
    "fast": "Utilise presque tout le processeur, en laissant la priorité à vos autres applications.",
    "balanced": "Utilise environ la moitié du processeur : l’ordinateur reste confortable pour travailler à côté.",
    "light": "Une photo à la fois, en arrière-plan : plus lent, mais presque imperceptible.",
}
# Measured plateau: beyond eight photos in parallel the DINOv3 encoder and the
# decoders compete for memory bandwidth and the gain disappears.
MAX_WORKERS = 8
# Peak memory of one photo being prepared (24–45 Mpx RAW developed at half size,
# rendered XMP references), with a margin.
WORKER_MEMORY = 600 * 1024 ** 2
# Never let prepared photos take more than this share of the installed memory.
MEMORY_SHARE = .3
LOW_CORES = 4
LOW_MEMORY = 8 * 1024 ** 3


@dataclass(frozen=True)
class Plan:
    mode: str
    workers: int  # photos prepared at the same time
    threads: int  # DINOv3 threads per photo
    modest: bool  # less powerful computer: limits already reduced

    def summary(self):
        photos = "1 photo à la fois" if self.workers == 1 else f"{self.workers} photos en parallèle"
        return photos + (" (ordinateur modeste : charge limitée)" if self.modest else "")


def cores():
    count = os.process_cpu_count() if hasattr(os, "process_cpu_count") else os.cpu_count()
    return max(1, count or 1)


def memory():
    """Installed memory in bytes, or None when the system does not say."""
    try:
        if sys.platform == "win32":
            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                            ("page_total", ctypes.c_ulonglong), ("page_available", ctypes.c_ulonglong),
                            ("virtual_total", ctypes.c_ulonglong), ("virtual_available", ctypes.c_ulonglong),
                            ("extended", ctypes.c_ulonglong)]
            status = Status()
            status.length = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total)
            return None
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None


def normalize(mode):
    return mode if mode in MODES else DEFAULT_MODE


def plan(mode=DEFAULT_MODE, cpu_count=None, memory_bytes=None):
    """Parallelism for a load, checked against this computer's cores and memory."""
    mode = normalize(mode)
    cpu_count = cores() if cpu_count is None else max(1, cpu_count)
    memory_bytes = memory() if memory_bytes is None else memory_bytes
    # One logical core always stays free for the interface.
    budget = {"fast": cpu_count - 1, "balanced": cpu_count // 2, "light": 1}[mode]
    budget = max(1, budget)
    # Two DINOv3 threads per photo is the measured sweet spot; on small
    # budgets favour more photos with one thread each.
    workers = max(1, min(MAX_WORKERS, budget // 2 if budget >= 4 else budget))
    if mode == "light":
        workers = 1
    modest = cpu_count <= LOW_CORES or (memory_bytes is not None and memory_bytes < LOW_MEMORY)
    if memory_bytes is not None:
        workers = max(1, min(workers, int(memory_bytes * MEMORY_SHARE // WORKER_MEMORY)))
    if cpu_count <= 2:
        workers = 1
    threads = max(1, min(2, budget // workers))
    return Plan(mode, workers, threads, modest)


def default_mode():
    """A less powerful computer starts balanced so it stays usable during a task."""
    return "balanced" if plan("fast").modest else DEFAULT_MODE


def lower_priority(mode):
    """Let the user's other applications go first; work still runs at full speed when idle.

    Only this job process is affected. On macOS and Linux a niceness can only grow
    without administrator rights, so switching back to a faster load keeps the
    lowest priority reached until the next task.
    """
    mode = normalize(mode)
    try:
        if sys.platform == "win32":
            below_normal, idle = 0x4000, 0x40
            kernel = ctypes.windll.kernel32
            kernel.SetPriorityClass(kernel.GetCurrentProcess(), idle if mode == "light" else below_normal)
        else:
            target = {"fast": 5, "balanced": 10, "light": 19}[mode]
            current = os.getpriority(os.PRIO_PROCESS, 0)
            if target > current:
                os.setpriority(os.PRIO_PROCESS, 0, target)
    except (AttributeError, OSError):
        pass


def priority_note(platform=None):
    """Tooltip line for systems where a lowered priority cannot be raised again."""
    if (platform or sys.platform) == "win32":
        return ""
    return ("Sur Mac, une charge plus basse choisie pendant une tâche y reste jusqu’à la fin : repasser "
            "en Rapide ou Équilibrée augmente le nombre de photos traitées en parallèle, mais la priorité "
            "ne remonte qu’à la tâche suivante.")


def read_mode(load):
    """``load`` is a mode name, a shared ``multiprocessing.Value`` index, or None."""
    if load is None or isinstance(load, str):
        return normalize(load)
    index = load.value
    names = list(MODES)
    return names[index] if 0 <= index < len(names) else DEFAULT_MODE
