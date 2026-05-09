from __future__ import annotations

import shlex
from typing import Optional


def _cmake_define_key(arg: str) -> Optional[str]:
    """Return the CMake ``-D`` variable key for ``-DKEY=`` or ``-DKEY:type=``."""
    if not arg.startswith("-D"):
        return None
    body = arg[2:]
    if "=" not in body:
        return None
    key_part = body.split("=", 1)[0]
    key = key_part.split(":", 1)[0]
    return key or None


def normalize_custom_cmake_args(args: Optional[list[str]]) -> list[str]:
    """Trim custom CMake args and drop blank/comment lines from the trigger UI."""
    return [
        arg.strip()
        for arg in (args or [])
        if arg.strip() and not arg.strip().startswith("#")
    ]


def merge_cmake_args(base_args: list[str], custom_args: list[str]) -> list[str]:
    """Merge run-level custom CMake args over configured base args."""
    custom_args = normalize_custom_cmake_args(custom_args)
    last_custom_index_by_key: dict[str, int] = {}
    for idx, arg in enumerate(custom_args):
        key = _cmake_define_key(arg)
        if key is not None:
            last_custom_index_by_key[key] = idx

    custom_keys = set(last_custom_index_by_key)
    merged = [
        arg for arg in base_args if (_cmake_define_key(arg) not in custom_keys)
    ]
    for idx, arg in enumerate(custom_args):
        key = _cmake_define_key(arg)
        if key is None or last_custom_index_by_key[key] == idx:
            merged.append(arg)
    return merged


def build_cmake_command(cmake_args: list[str], source_dir: str) -> str:
    """Build a shell-safe CMake command string for local and remote executors."""
    return " ".join(
        ["cmake", *(shlex.quote(a) for a in cmake_args), shlex.quote(source_dir)]
    )
