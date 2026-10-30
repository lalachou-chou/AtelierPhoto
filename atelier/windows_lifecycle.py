"""Tell the Windows installer that this application is still running."""
import sys

APP_MUTEX = "AtelierPhoto.Application.03D9A7F4"
_mutex = None


def mark_running():
    """Keep the named handle alive until process exit, including worker shutdown."""
    global _mutex
    if sys.platform != "win32" or _mutex is not None:
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel.CreateMutexW(None, False, APP_MUTEX)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    # Windows closes this handle on process termination. Closing it earlier
    # would allow uninstall while DLLs or child processes are still in use.
    _mutex = handle
