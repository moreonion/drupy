"""Tests for the utility functions."""

import os
import pathlib

from drupy import utils


def test_normalize_permissions(temp_dir):
    """Test normalizing the permissions of a folder."""
    original_chmod = os.umask(0o0)
    root = pathlib.Path(temp_dir)
    root.joinpath("dir", "sub").mkdir(mode=0o700, parents=True)
    root.joinpath("file").touch(mode=0o600)
    root.joinpath("dir", "sub", "file").touch(mode=0o666)

    os.umask(0o22)
    utils.normalize_permissions(temp_dir)
    os.umask(original_chmod)
    assert root.joinpath("dir").stat().st_mode & 0o777 == 0o755
    assert root.joinpath("dir", "sub").stat().st_mode & 0o777 == 0o755
    assert root.joinpath("file").stat().st_mode & 0o777 == 0o644
    assert root.joinpath("dir", "sub", "file").stat().st_mode & 0o777 == 0o644
