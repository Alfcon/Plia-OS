import subprocess
import pytest
from unittest.mock import patch, MagicMock


# --- read_file ---

def test_read_file_full(tmp_path):
    from modules.file_tools import read_file
    f = tmp_path / "notes.txt"
    f.write_text("line1\nline2\nline3")
    result = read_file(str(f))
    assert "line1" in result
    assert "line3" in result


def test_read_file_line_range(tmp_path):
    from modules.file_tools import read_file
    f = tmp_path / "notes.txt"
    f.write_text("a\nb\nc\nd\ne")
    result = read_file(str(f), start_line=2, end_line=4)
    assert "b" in result
    assert "d" in result
    assert "a" not in result
    assert "e" not in result


def test_read_file_negative_start(tmp_path):
    from modules.file_tools import read_file
    f = tmp_path / "log.txt"
    f.write_text("\n".join(f"line{i}" for i in range(10)))
    result = read_file(str(f), start_line=-3)
    lines = result.strip().splitlines()
    assert len(lines) == 3
    assert "line9" in result


def test_read_file_missing(tmp_path):
    from modules.file_tools import read_file
    result = read_file(str(tmp_path / "nonexistent.txt"))
    assert "not found" in result.lower()


# --- list_directory ---

def test_list_directory_normal(tmp_path):
    from modules.file_tools import list_directory
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "subdir").mkdir()
    result = list_directory(str(tmp_path))
    assert "a.txt" in result
    assert "subdir" in result
    assert "[dir]" in result
    assert "[file]" in result


def test_list_directory_empty(tmp_path):
    from modules.file_tools import list_directory
    empty = tmp_path / "empty"
    empty.mkdir()
    result = list_directory(str(empty))
    assert "empty" in result.lower()


def test_list_directory_missing(tmp_path):
    from modules.file_tools import list_directory
    result = list_directory(str(tmp_path / "no_such_dir"))
    assert "not found" in result.lower()


# --- find_files ---

def test_find_files_match(tmp_path):
    from modules.file_tools import find_files
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    result = find_files("*.py", str(tmp_path))
    assert "a.py" in result
    assert "b.py" in result
    assert "c.txt" not in result


def test_find_files_no_match(tmp_path):
    from modules.file_tools import find_files
    result = find_files("*.xyz", str(tmp_path))
    assert "no files found" in result.lower()


# --- search_in_file ---

def test_search_in_file_match(tmp_path):
    from modules.file_tools import search_in_file
    f = tmp_path / "data.txt"
    f.write_text("hello world\nfoo bar\nhello again")
    result = search_in_file(str(f), "hello")
    assert "1:" in result
    assert "3:" in result
    assert "2:" not in result


def test_search_in_file_no_match(tmp_path):
    from modules.file_tools import search_in_file
    f = tmp_path / "data.txt"
    f.write_text("nothing relevant here")
    result = search_in_file(str(f), "zzznomatch")
    assert "no matches" in result.lower()


# --- write_file ---

def test_write_file_creates(tmp_path):
    from modules.file_tools import write_file
    f = tmp_path / "new.txt"
    result = write_file(str(f), "hello")
    assert f.read_text() == "hello"
    assert "written" in result.lower()


def test_write_file_overwrites(tmp_path):
    from modules.file_tools import write_file
    f = tmp_path / "existing.txt"
    f.write_text("old content")
    write_file(str(f), "new content")
    assert f.read_text() == "new content"


# --- append_to_file ---

def test_append_to_file_creates(tmp_path):
    from modules.file_tools import append_to_file
    f = tmp_path / "new.txt"
    result = append_to_file(str(f), "first line\n")
    assert f.read_text() == "first line\n"
    assert "appended" in result.lower()


def test_append_to_file_appends(tmp_path):
    from modules.file_tools import append_to_file
    f = tmp_path / "existing.txt"
    f.write_text("line1\n")
    append_to_file(str(f), "line2\n")
    assert f.read_text() == "line1\nline2\n"


# --- delete_file ---

def test_delete_file_success(tmp_path):
    from modules.file_tools import delete_file
    f = tmp_path / "to_delete.txt"
    f.write_text("bye")
    result = delete_file(str(f))
    assert not f.exists()
    assert "deleted" in result.lower()


def test_delete_file_missing(tmp_path):
    from modules.file_tools import delete_file
    result = delete_file(str(tmp_path / "nonexistent.txt"))
    assert "not found" in result.lower()


# --- move_file ---

def test_move_file_success(tmp_path):
    from modules.file_tools import move_file
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("content")
    result = move_file(str(src), str(dst))
    assert not src.exists()
    assert dst.read_text() == "content"
    assert "moved" in result.lower()


# --- copy_file ---

def test_copy_file_success(tmp_path):
    from modules.file_tools import copy_file
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("content")
    result = copy_file(str(src), str(dst))
    assert src.exists()
    assert dst.read_text() == "content"
    assert "copied" in result.lower()


# --- run_file ---

def test_run_file_python(tmp_path):
    from modules.file_tools import run_file
    f = tmp_path / "hello.py"
    f.write_text('print("hello from script")')
    mock_result = MagicMock()
    mock_result.stdout = "hello from script\n"
    mock_result.stderr = ""
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result):
        result = run_file(str(f))
    assert "hello from script" in result


def test_run_file_timeout(tmp_path):
    from modules.file_tools import run_file
    f = tmp_path / "slow.py"
    f.write_text("import time; time.sleep(100)")
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=30)):
        result = run_file(str(f))
    assert "timed out" in result.lower()
