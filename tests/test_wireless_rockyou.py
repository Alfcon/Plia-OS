"""rockyou wordlist resolution: multi-location lookup, .gz auto-decompress, download."""
import gzip
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import modules.wireless_tools as wt


@pytest.fixture(autouse=True)
def _isolate_wordlists(monkeypatch, tmp_path):
    """Never touch the real ~/.plia or system wordlist paths during tests."""
    monkeypatch.setattr(wt, "_wordlist_dir", lambda: tmp_path / "wordlists")
    monkeypatch.setattr(wt, "_ROCKYOU_CANDIDATES", ())
    monkeypatch.setattr(wt, "_ROCKYOU_GZ_CANDIDATES", ())


def _write_gz(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# _find_rockyou
# ---------------------------------------------------------------------------

def test_find_rockyou_prefers_system_candidate(monkeypatch, tmp_path):
    wl = tmp_path / "sys" / "rockyou.txt"
    wl.parent.mkdir()
    wl.write_text("123456\npassword\n")
    monkeypatch.setattr(wt, "_ROCKYOU_CANDIDATES", (str(wl),))
    assert wt._find_rockyou() == (str(wl), None)


def test_find_rockyou_uses_cache(tmp_path):
    cache = tmp_path / "wordlists" / "rockyou.txt"
    cache.parent.mkdir()
    cache.write_text("123456\n")
    assert wt._find_rockyou() == (str(cache), None)


def test_find_rockyou_auto_decompresses_gz(monkeypatch, tmp_path):
    gz = _write_gz(tmp_path / "rockyou.txt.gz", "123456\npassword\n")
    monkeypatch.setattr(wt, "_ROCKYOU_GZ_CANDIDATES", (str(gz),))

    path, err = wt._find_rockyou()

    assert err is None
    assert path == str(tmp_path / "wordlists" / "rockyou.txt")
    assert Path(path).read_text() == "123456\npassword\n"


def test_find_rockyou_bad_gz_reports(monkeypatch, tmp_path):
    gz = tmp_path / "rockyou.txt.gz"
    gz.write_text("definitely not gzip")
    monkeypatch.setattr(wt, "_ROCKYOU_GZ_CANDIDATES", (str(gz),))

    path, err = wt._find_rockyou()

    assert path is None
    assert "could not decompress" in err


def test_find_rockyou_missing_explains_all_options():
    path, err = wt._find_rockyou()
    assert path is None
    assert "download_rockyou" in err          # works on any distro
    assert "apt install wordlists" in err     # Kali-only, listed separately
    assert "gitlab.com/kalilinux" in err      # manual fallback


# ---------------------------------------------------------------------------
# crack_handshake_rockyou
# ---------------------------------------------------------------------------

def test_crack_handshake_rockyou_uses_resolved_wordlist(monkeypatch, tmp_path):
    cap = tmp_path / "cap.cap"
    cap.write_text("x")
    wl = tmp_path / "rockyou.txt"
    wl.write_text("123456\n")
    monkeypatch.setattr(wt, "_bin_missing", lambda name: None)
    monkeypatch.setattr(wt, "_find_rockyou", lambda: (str(wl), None))
    calls = {}

    def fake_run(*cmd, timeout=30):
        calls["cmd"] = cmd
        return MagicMock(stdout="KEY FOUND! [ hunter2 ]", stderr="")

    monkeypatch.setattr(wt, "_run", fake_run)

    out = wt.crack_handshake_rockyou(str(cap), "AA:BB:CC:DD:EE:FF")

    assert "KEY FOUND" in out
    assert str(wl) in calls["cmd"]


def test_crack_handshake_rockyou_missing_wordlist_guides_download(monkeypatch, tmp_path):
    cap = tmp_path / "cap.cap"
    cap.write_text("x")
    monkeypatch.setattr(wt, "_bin_missing", lambda name: None)
    monkeypatch.setattr(wt, "_find_rockyou", lambda: (None, "USE download_rockyou"))

    assert wt.crack_handshake_rockyou(str(cap), "AA:BB") == "USE download_rockyou"


def test_crack_with_wordlists_uses_resolved_rockyou(monkeypatch, tmp_path):
    wl = tmp_path / "rockyou.txt"
    wl.write_text("123456\n")
    monkeypatch.setattr(wt, "_find_rockyou", lambda: (str(wl), None))
    seen = {}

    def fake_psk(capture, bssid, wordlist):
        seen["wordlist"] = wordlist
        return "hunter2"

    monkeypatch.setattr(wt, "_aircrack_psk", fake_psk)

    assert wt._crack_with_wordlists("cap.cap", "AA:BB") == "hunter2"
    assert seen["wordlist"] == str(wl)


# ---------------------------------------------------------------------------
# download_rockyou
# ---------------------------------------------------------------------------

def test_download_rockyou_already_present(tmp_path):
    cache = tmp_path / "wordlists" / "rockyou.txt"
    cache.parent.mkdir()
    cache.write_text("123456\n")
    assert "already available" in wt.download_rockyou()


def test_download_rockyou_fetches_and_decompresses(monkeypatch, tmp_path):
    def fake_download(url, dest, timeout=600):
        _write_gz(Path(dest), "123456\npassword\n")
        return None

    monkeypatch.setattr(wt, "_download_file", fake_download)

    msg = wt.download_rockyou()

    assert "ready at" in msg
    assert (tmp_path / "wordlists" / "rockyou.txt").read_text() == "123456\npassword\n"


def test_download_rockyou_reports_download_failure(monkeypatch):
    monkeypatch.setattr(wt, "_download_file", lambda url, dest, timeout=600: "no network")
    msg = wt.download_rockyou()
    assert "Download failed" in msg
    assert "no network" in msg


def test_download_rockyou_rejects_non_gzip(monkeypatch, tmp_path):
    def fake_download(url, dest, timeout=600):
        Path(dest).write_text("not gzip")
        return None

    monkeypatch.setattr(wt, "_download_file", fake_download)

    assert "could not be decompressed" in wt.download_rockyou()


# ---------------------------------------------------------------------------
# install_wireless_tools guidance
# ---------------------------------------------------------------------------

def test_install_wireless_tools_suggests_download_when_no_wordlist(monkeypatch):
    monkeypatch.setattr(wt.subprocess, "run", lambda *a, **k: MagicMock(returncode=0))
    monkeypatch.setattr(wt, "_bin_missing", lambda name: None)
    monkeypatch.setattr(wt, "_find_rockyou", lambda: (None, "help"))

    out = wt.install_wireless_tools()

    assert "download_rockyou" in out
    assert "'wordlists' package is Kali-only" in out
