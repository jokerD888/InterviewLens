"""Protect generated credentials/backups on both Unix and Windows."""
import os
from pathlib import Path
import re
import subprocess


def private_file(path: Path):
    os.chmod(path, 0o600)
    _windows_acl(path, directory=False)


def private_directory(path: Path):
    os.chmod(path, 0o700)
    _windows_acl(path, directory=True)


def _windows_acl(path: Path, *, directory: bool):
    if os.name != "nt":
        return
    # chmod on Windows does not restrict the NTFS DACL. Use SID identifiers
    # (locale-independent), without changing owner or requiring SACL privileges.
    identity = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, check=True)
    match = re.search(rb"S-1-(?:\d+-)+\d+", identity.stdout)
    if not match:
        raise RuntimeError("Cannot determine the current Windows account SID")
    sid = match.group().decode("ascii")
    rights = "(OI)(CI)F" if directory else "F"
    result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                             f"*{sid}:{rights}", f"*S-1-5-18:{rights}"], capture_output=True)
    if result.returncode:
        raise RuntimeError("Cannot protect the private file ACL")
