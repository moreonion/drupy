"""Utility functions."""

import os
import os.path


def get_umask():
    """Read the umask currently set for this process."""
    # The umask can’t be read without writing it so set it and reset it immediately.
    umask = os.umask(0)
    os.umask(umask)
    return umask


def normalize_permissions(path):
    """Recursively set the permissions on files and directories based on the current umask."""
    umask = get_umask()
    dir_perm = 0o777 & ~umask
    file_perm = 0o666 & ~umask

    for root, dirs, files in os.walk(path):
        for dir_ in dirs:
            os.chmod(os.path.join(root, dir_), dir_perm)
        for file in files:
            os.chmod(os.path.join(root, file), file_perm)
