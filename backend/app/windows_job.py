"""Windows Job Object containment for Automaton child processes.

Applies process-tree lifetime, memory and active-process limits. This is NOT an
AppContainer/restricted-token boundary: children retain the user's filesystem
and network permissions.
"""
import ctypes
import os
from ctypes import wintypes

CREATE_SUSPENDED = 0x00000004
JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
ERROR_ACCESS_DENIED = 5

class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]

class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def create_job_for_suspended_process(process, memory_bytes=512 * 1024 * 1024,
                                     cpu_seconds=30, max_processes=32):
    """Assign a CREATE_SUSPENDED Popen child before its first instruction."""
    if os.name != "nt":
        return None
    kernel32 = _kernel32()
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
            JOB_OBJECT_LIMIT_PROCESS_MEMORY |
            JOB_OBJECT_LIMIT_JOB_MEMORY |
            JOB_OBJECT_LIMIT_ACTIVE_PROCESS |
            JOB_OBJECT_LIMIT_PROCESS_TIME
        )
        info.BasicLimitInformation.ActiveProcessLimit = max_processes
        info.BasicLimitInformation.PerProcessUserTimeLimit = int(cpu_seconds * 10_000_000)
        info.ProcessMemoryLimit = memory_bytes
        info.JobMemoryLimit = memory_bytes
        if not kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
            raise ctypes.WinError(ctypes.get_last_error())
        # Popen closes the primary thread handle right after CreateProcess, so resume
        # via the process handle it keeps (PROCESS_ALL_ACCESS includes SUSPEND_RESUME).
        status = _ntdll().NtResumeProcess(wintypes.HANDLE(int(process._handle)))
        if status != 0:
            raise OSError(f"NtResumeProcess a échoué (NTSTATUS 0x{status & 0xFFFFFFFF:08X})")
        return job
    except Exception:
        kernel32.TerminateJobObject(job, 1)
        kernel32.CloseHandle(job)
        raise


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _ntdll():
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    ntdll.NtResumeProcess.restype = ctypes.c_long
    return ntdll


def terminate_job(job, exit_code=1):
    if job:
        kernel32 = _kernel32()
        if not kernel32.TerminateJobObject(job, exit_code):
            error = ctypes.get_last_error()
            if error != ERROR_ACCESS_DENIED:
                raise ctypes.WinError(error)


def close_job(job):
    if job:
        _kernel32().CloseHandle(job)
