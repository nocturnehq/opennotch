"""Launch the Linux recorder with a signal if its creating process exits."""
import ctypes
import os
import signal
import sys

PR_SET_PDEATHSIG = 1


def main():
    parent_pid = int(sys.argv[1])
    command = sys.argv[2:]
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong)
    prctl.restype = ctypes.c_int
    if prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Could not protect the recorder from parent exit")
    if os.getppid() != parent_pid:
        return 1
    os.execv(command[0], command)


if __name__ == "__main__":
    sys.exit(main())
