"""``run_analysis`` sandbox (decision #19): a separate Python process with
- no network (Linux as root: ``os.unshare(CLONE_NEWNET)`` before dropping to ``nobody``; otherwise refused),
- no writes (RLIMIT_FSIZE=0, empty temp cwd, runs as ``nobody`` when started as root),
- CPU-time / address-space / open-files / process (RLIMIT_NPROC) limits, wall-clock timeout that kills the whole
  process group, truncated output.
Disabled unless ``UHD_AGENT_SANDBOX_ENABLED=1``. Inputs (reports) are passed via stdin as JSON.
"""

from __future__ import annotations

import json
import os
import resource
import signal
import subprocess
import sys
import tempfile

from uhd.config import get_settings
from uhd.errors import APIError

MAX_OUTPUT = 20_000
_PRELUDE = r"""
import json, sys, os
REPORTS = json.loads(sys.stdin.read() or "[]")
LANDSAT_DIR = os.environ.get("LANDSAT_DIR", "")
del json, sys
"""


NPROC_LIMIT = 16


def isolation_available() -> bool:
    """A fresh network namespace needs Linux, root (CAP_SYS_ADMIN) and ``os.unshare`` (Python ≥ 3.12)."""
    return sys.platform.startswith("linux") and os.geteuid() == 0 and hasattr(os, "unshare")


def _preexec(mem_mb: int, cpu_s: int, isolate: bool):
    """Runs in the child before exec: new session, *then* a new empty network namespace (still root), rlimits, and only
    then drop to ``nobody`` — unsharing after setuid fails with EPERM (REVIEW M6)."""

    def apply():
        os.setsid()
        if isolate:
            os.unshare(os.CLONE_NEWNET)  # only a down loopback inside: no network at all
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 2**20, mem_mb * 2**20))
        except (ValueError, OSError):  # not supported on macOS
            pass
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if os.geteuid() == 0:
            import pwd

            nobody = pwd.getpwnam("nobody")
            # RLIMIT_NPROC counts all processes of the *user*; set it before setuid so it applies to nobody
            resource.setrlimit(resource.RLIMIT_NPROC, (NPROC_LIMIT, NPROC_LIMIT))
            os.setgroups([])
            os.setgid(nobody.pw_gid)
            os.setuid(nobody.pw_uid)

    return apply


def _kill_group(p: subprocess.Popen) -> None:
    try:
        os.killpg(p.pid, signal.SIGKILL)  # child did setsid(): pgid == pid, so forked grandchildren die too
    except (ProcessLookupError, PermissionError):
        pass


def run(code: str, reports: list[dict], *, force: bool = False, require_isolation: bool = True) -> dict:
    s = get_settings()
    if not (s.agent_sandbox_enabled or force):
        raise APIError(403, "sandbox_disabled", "the analysis sandbox is disabled on this server")
    isolated = isolation_available()
    if require_isolation and not isolated:
        raise APIError(503, "sandbox_unavailable", "network isolation (root on Linux with unshare) is not available")
    cmd = [s.agent_sandbox_python or sys.executable, "-I", "-c", _PRELUDE + "\n" + code]
    with tempfile.TemporaryDirectory(prefix="uhd-sbx-") as wd:
        os.chmod(wd, 0o555)
        env = {"PATH": "/usr/bin:/bin", "LANDSAT_DIR": str(s.landsat_dir), "HOME": wd, "OPENBLAS_NUM_THREADS": "1",
               "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, cwd=wd, env=env,
                                 preexec_fn=_preexec(s.agent_sandbox_memory_mb, int(s.agent_sandbox_timeout_s) + 1,
                                                     isolated))
        except OSError as e:  # e.g. nobody cannot execute the interpreter → set UHD_AGENT_SANDBOX_PYTHON
            raise APIError(503, "sandbox_unavailable", f"cannot start the sandbox interpreter: {e.strerror}") from e
        try:
            out, err = p.communicate(json.dumps(reports, ensure_ascii=False), timeout=s.agent_sandbox_timeout_s)
        except subprocess.TimeoutExpired:
            _kill_group(p)
            p.communicate()
            return {"ok": False, "error": "timeout", "timeout_s": s.agent_sandbox_timeout_s}
        finally:
            _kill_group(p)  # reap any background grandchildren left in the session
    return {"ok": p.returncode == 0, "returncode": p.returncode, "isolated_network": isolated,
            "stdout": out[:MAX_OUTPUT], "stderr": err[-4000:], "truncated": len(out) > MAX_OUTPUT}
