from __future__ import annotations
import pytest
from core.shell_guard import check_command, ShellBlockedError


def _ok(cmd):
    check_command(cmd)  # must not raise


def _blocked(cmd):
    with pytest.raises(ShellBlockedError):
        check_command(cmd)


def test_safe_ls():
    _ok("ls -la /home/user")


def test_safe_grep():
    _ok("grep -r 'hello' /var/log")


def test_safe_find():
    _ok("find /tmp -name '*.log' -mtime +7")


def test_fork_bomb_blocked():
    _blocked(":(){ :|:& };:")


def test_fork_bomb_variant_blocked():
    _blocked(":() { : | : ; }")


def test_dd_to_sda_blocked():
    _blocked("dd if=/dev/zero of=/dev/sda")


def test_dd_to_nvme_blocked():
    _blocked("dd if=backup.img of=/dev/nvme0n1 bs=4M")


def test_mkfs_blocked():
    _blocked("mkfs.ext4 /dev/sdb1")


def test_mkfs_any_blocked():
    _blocked("mkfs /dev/sda1")


def test_write_redirect_to_sda_blocked():
    _blocked("cat evil.img >> /dev/sda")


def test_shred_device_blocked():
    _blocked("shred -z /dev/sda")


def test_safe_dd_to_file():
    _ok("dd if=/dev/zero of=testfile bs=1M count=10")


def test_safe_rm_subdir():
    _ok("rm -rf /home/user/old_project")


def test_rm_root_blocked():
    _blocked("rm -rf / --no-preserve-root")
