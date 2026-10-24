import importlib
from unittest.mock import MagicMock, patch


def _nt():
    """The *current* modules.network_tools object.

    core/loader.py execs every modules/*.py into a fresh module object and
    assigns sys.modules[...] directly, so the module is replaced whenever
    create_app() runs (the autouse reset_registry fixture clears the registry,
    which defeats the loader's "already registered" shortcut). Two consequences:

      * a module-level ``from modules.network_tools import connect_wifi`` binds
        an object that goes stale mid-session, and
      * a string target such as ``patch("modules.network_tools._run_timed")``
        can resolve to a *different* copy than the one the test calls.

    When that happens the patch silently misses and the real nmcli runs — these
    tests then fail with live system data. Resolving the module at call time and
    patching attributes on that same object keeps patch and call on one copy.
    """
    return importlib.import_module("modules.network_tools")


def _wt():
    """The current modules.wireless_tools object (see _nt)."""
    return importlib.import_module("modules.wireless_tools")


def _ok(stdout=""):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = ""
    return m


def _fail(stderr="boom"):
    m = MagicMock()
    m.returncode = 1
    m.stdout = ""
    m.stderr = stderr
    return m


def _connection_show(stdout):
    return _ok(stdout=stdout)


def _scan(networks):
    return patch.object(_nt(), "_scan_wifi_networks", return_value=networks)


def _profiles(names):
    return patch.object(_nt(), "_nmcli_wifi_profiles", return_value=names)


def test_connect_wifi_explicit_ssid_reuses_saved_no_password():
    with _scan([("Home", 90, "WPA2")]), \
         _profiles(["Home"]), \
         patch.object(_nt(), "_run_timed", return_value=_ok()) as run:
        out = _nt().connect_wifi("home")
    assert "Connected to 'Home'" in out
    assert run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "Home"]


def test_connect_wifi_with_password_and_interface():
    with _scan([("Cafe", 80, "WPA2")]), \
         _profiles([]), \
         patch.object(_nt(), "_run_timed", return_value=_ok()) as run:
        out = _nt().connect_wifi("Cafe", "wlan0", "hunter2")
    assert "Connected to 'Cafe'" in out
    assert run.call_args.args[0] == [
        "nmcli", "device", "wifi", "connect", "Cafe",
        "password", "hunter2", "ifname", "wlan0",
    ]


def test_connect_wifi_auto_picks_strongest_saved_in_range():
    available = [("Neighbor", 95, "WPA2"), ("Home", 70, "WPA2"), ("Cafe", 60, "open")]
    with _scan(available), \
         _profiles(["Home", "Cafe"]), \
         patch.object(_nt(), "_run_timed", return_value=_ok()) as run:
        out = _nt().connect_wifi()
    # Neighbor is strongest but not saved; Home (70) beats Cafe (60)
    assert "Connected to 'Home'" in out
    assert run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "Home"]


def test_connect_wifi_single_saved_profile_not_in_range_uses_connection_up():
    with _scan([("Neighbor", 95, "WPA2")]), \
         _profiles(["MyHiddenNet"]), \
         patch.object(_nt(), "_run_timed", return_value=_ok()) as run:
        out = _nt().connect_wifi()
    assert "Connected to 'MyHiddenNet'" in out
    assert run.call_args.args[0] == ["nmcli", "connection", "up", "MyHiddenNet"]


def test_connect_wifi_no_saved_networks_reports():
    with _scan([("Neighbor", 95, "open")]), \
         _profiles([]), \
         patch.object(_nt(), "_run_timed") as run:
        out = _nt().connect_wifi()
    run.assert_not_called()
    assert "No saved WiFi network" in out


def test_connect_wifi_secrets_required_escalates_to_recovery():
    with _scan([("Cafe", 80, "WPA2")]), \
         _profiles([]), \
         patch.object(_nt(), "_run_timed",
                      return_value=_fail("Error: secrets were required, but not provided")) as run, \
         patch.object(_nt(), "_try_gain_access",
                      return_value="Recovered the key for 'Cafe' via WPS.") as recover:
        out = _nt().connect_wifi("Cafe")
    assert "password" in out.lower()
    assert run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "Cafe"]
    recover.assert_called_once_with("Cafe", "")
    assert "Recovered the key" in out


def test_try_gain_access_delegates_to_wireless_tools():
    # _try_gain_access imports gain_wifi_access lazily, so the stub has to live on
    # the copy importlib resolves — the same object _wt() returns.
    with patch.object(_wt(), "gain_wifi_access", return_value="got it") as g:
        out = _nt()._try_gain_access("Cafe", "wlan0")
    g.assert_called_once_with("Cafe", "wlan0")
    assert out == "got it"


def test_try_gain_access_exception_returns_hint():
    with patch.object(_wt(), "gain_wifi_access", side_effect=RuntimeError("boom")):
        out = _nt()._try_gain_access("Cafe", "")
    assert "not available" in out
    assert "password" in out.lower()


def test_connect_wifi_prefers_saved_profile_on_ambiguous_name():
    available = [("Home Network 5G", 88, "WPA2"), ("Home Network", 70, "WPA2")]
    with _scan(available), \
         _profiles(["Home Network"]), \
         patch.object(_nt(), "_run_timed", return_value=_ok()) as run:
        out = _nt().connect_wifi("home")
    # cmd is ["nmcli", "device", "wifi", "connect", <target>] — the target is index 4.
    assert run.call_args.args[0][4] == "Home Network"


def test_list_saved_wifi_formats_profiles():
    with _profiles(["Home", "Cafe 5G"]):
        out = _nt().list_saved_wifi()
    assert "Home" in out
    assert "Cafe 5G" in out


def test_list_saved_wifi_empty():
    with _profiles([]):
        assert _nt().list_saved_wifi() == "No saved WiFi networks found."


# --- saved profiles: NetworkManager repeats a name once per BSSID -------------

def test_nmcli_wifi_profiles_collapses_repeated_names():
    # One wireless profile per saved network *per BSSID*, plus a wired profile
    # and an unnamed one, which are not WiFi networks at all.
    out = (
        "Auto Home:802-11-wireless\n"
        "Home:802-11-wireless\n"
        "Auto Home:802-11-wireless\n"
        "Cafe 5G:802-11-wireless\n"
        "Auto Home:802-11-wireless\n"
        "Wired 1:802-3-ethernet\n"
        ":802-11-wireless\n"
    )
    with patch("subprocess.run", return_value=_connection_show(out)):
        assert _nt()._nmcli_wifi_profiles() == ["Auto Home", "Home", "Cafe 5G"]


def test_list_saved_wifi_reports_each_network_once():
    out = "Home:802-11-wireless\nHome:802-11-wireless\nCafe:802-11-wireless\n"
    with patch("subprocess.run", return_value=_connection_show(out)):
        result = _nt().list_saved_wifi()
    assert result.count("- Home") == 1
    assert result.count("- Cafe") == 1


def test_connect_wifi_treats_repeated_profile_as_one_saved_network():
    # Three profiles for the same network must not defeat the "only one saved
    # network" shortcut that brings a hidden SSID up directly.
    out = "MyHiddenNet:802-11-wireless\n" * 3
    conn = _connection_show(out)

    def fake_run_timed(cmd, timeout=None, **kwargs):
        # _nmcli_wifi_profiles reads the profile list through _run_timed as well.
        if list(cmd)[:4] == ["nmcli", "-t", "-f", "NAME,TYPE"]:
            return conn
        return _ok()

    with _scan([("Neighbor", 95, "WPA2")]), \
         patch.object(_nt(), "_run_timed", side_effect=fake_run_timed) as run:
        result = _nt().connect_wifi()
    assert "Connected to 'MyHiddenNet'" in result
    assert run.call_args.args[0] == ["nmcli", "connection", "up", "MyHiddenNet"]
