from __future__ import annotations

from modern_opalx_regsuite.runner.pipeline import (
    build_cmake_command,
    merge_cmake_args,
    normalize_custom_cmake_args,
)


def test_normalize_custom_cmake_args_drops_blank_and_comment_lines() -> None:
    assert normalize_custom_cmake_args(
        ["", "  # note", " -DIPPL_GIT_TAG=master ", "\t"]
    ) == ["-DIPPL_GIT_TAG=master"]


def test_custom_cmake_args_replace_configured_define_keys() -> None:
    merged = merge_cmake_args(
        [
            "-DBUILD_TYPE=Debug",
            "-DIPPL_GIT_TAG=stable",
            "-DKokkos_VERSION=git.4.6.00",
            "-DHeffte_VERSION=git.v2.3.0",
            "-DPLATFORMS=SERIAL",
        ],
        [
            "-DIPPL_GIT_TAG=master",
            "-DHeffte_VERSION=git.v2.4.1",
            "-DKokkos_VERSION=git.4.7.01",
        ],
    )

    assert merged == [
        "-DBUILD_TYPE=Debug",
        "-DPLATFORMS=SERIAL",
        "-DIPPL_GIT_TAG=master",
        "-DHeffte_VERSION=git.v2.4.1",
        "-DKokkos_VERSION=git.4.7.01",
    ]


def test_custom_cmake_arg_type_suffix_replaces_same_key() -> None:
    assert merge_cmake_args(
        ["-DFOO:STRING=old", "-DBAR=keep"],
        ["-DFOO=override"],
    ) == ["-DBAR=keep", "-DFOO=override"]


def test_duplicate_custom_cmake_define_keeps_last_value() -> None:
    assert merge_cmake_args(
        ["-DIPPL_GIT_TAG=stable"],
        ["-DIPPL_GIT_TAG=feature", "--fresh", "-DIPPL_GIT_TAG=master"],
    ) == ["--fresh", "-DIPPL_GIT_TAG=master"]


def test_build_cmake_command_quotes_args_and_source_path() -> None:
    cmd = build_cmake_command(
        ["-DCMAKE_TEST_LAUNCHER=srun;-n;1;--overlap", "-DNAME=with space"],
        "/tmp/opalx src",
    )

    assert cmd == (
        "cmake '-DCMAKE_TEST_LAUNCHER=srun;-n;1;--overlap' "
        "'-DNAME=with space' '/tmp/opalx src'"
    )
