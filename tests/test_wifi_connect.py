from unittest.mock import MagicMock, patch

from modules.network_tools import connect_wifi, list_saved_wifi


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


def _scan(networks):
    return patch("modules.network_tools._scan_wifi_networks", return_value=networks)


def _profiles(names):
    return patch("modules.network_tools._nmcli_wifi_profiles", return_value=names)


def test_connect_wifi_explicit_ssid_reuses_saved_no_password():
    with _scan([("Home", 90, "WPA2")]), \
         _profiles(["Home"]), \
         patch("modules.network_tools._run_timed", return_value=_ok()) as run:
        out = connect_wifi("home")
    assert "Connected to 'Home'" in out
    assert run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "Home"]


def test_connect_wifi_with_password_and_interface():
    with _scan([("Cafe", 80, "WPA2")]), \
         _profiles([]), \
         patch("modules.network_tools._run_timed", return_value=_ok()) as run:
        out = connect_wifi("Cafe", "wlan0", "hunter2")
    assert "Connected to 'Cafe'" in out
    assert run.call_args.args[0] == [
        "nmcli", "device", "wifi", "connect", "Cafe",
        "password", "hunter2", "ifname", "wlan0",
    ]


def test_connect_wifi_auto_picks_strongest_saved_in_range():
    available = [("Neighbor", 95, "WPA2"), ("Home", 70, "WPA2"), ("Cafe", 60, "open")]
    with _scan(available), \
         _profiles(["Home", "Cafe"]), \
         patch("modules.network_tools._run_timed", return_value=_ok()) as run:
        out = connect_wifi()
    # Neighbor is strongest but not saved; Home (70) beats Cafe (60)
    assert "Connected to 'Home'" in out
    assert run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "Home"]


def test_connect_wifi_single_saved_profile_not_in_range_uses_connection_up():
    with _scan([("Neighbor", 95, "WPA2")]), \
         _profiles(["MyHiddenNet"]), \
         patch("modules.network_tools._run_timed", return_value=_ok()) as run:
        out = connect_wifi()
    assert "Connected to 'MyHiddenNet'" in out
    assert run.call_args.args[0] == ["nmcli", "connection", "up", "MyHiddenNet"]


def test_connect_wifi_no_saved_networks_reports():
    with _scan([("Neighbor", 95, "open")]), \
         _profiles([]), \
         patch("modules.network_tools._run_timed") as run:
        out = connect_wifi()
    run.assert_not_called()
    assert "No saved WiFi network" in out


def test_connect_wifi_secrets_required_escalates_to_recovery():
    with _scan([("Cafe", 80, "WPA2")]), \
         _profiles([]), \
         patch("modules.network_tools._run_timed",
               return_value=_fail("Error: secrets were required, but not provided")) as run, \
         patch("modules.network_tools._try_gain_access",
               return_value="Recovered the key for 'Cafe' via WPS.") as recover:
        out = connect_wifi("Cafe")
    assert "password" in out.lower()
    assert run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "Cafe"]
    recover.assert_called_once_with("Cafe", "")
    assert "Recovered the key" in out


def test_try_gain_access_delegates_to_wireless_tools():
    from modules.network_tools import _try_gain_access
    with patch("modules.wireless_tools.gain_wifi_access", return_value="got it") as g:
        out = _try_gain_access("Cafe", "wlan0")
    g.assert_called_once_with("Cafe", "wlan0")
    assert out == "got it"


def test_try_gain_access_exception_returns_hint():
    from modules.network_tools import _try_gain_access
    with patch("modules.wireless_tools.gain_wifi_access", side_effect=RuntimeError("boom")):
        out = _try_gain_access("Cafe", "")
    assert "not available" in out
    assert "password" in out.lower()


def test_connect_wifi_prefers_saved_profile_on_ambiguous_name():
    available = [("Home Network 5G", 88, "WPA2"), ("Home Network", 70, "WPA2")]
    with _scan(available), \
         _profiles(["Home Network"]), \
         patch("modules.network_tools._run_timed", return_value=_ok()) as run:
        out = connect_wifi("home")
    assert run.call_args.args[0][3] == "Home Network"


def test_list_saved_wifi_formats_profiles():
    with _profiles(["Home", "Cafe 5G"]):
        out = list_saved_wifi()
    assert "Home" in out
    assert "Cafe 5G" in out


def test_list_saved_wifi_empty():
    with _profiles([]):
        assert list_saved_wifi() == "No saved WiFi networks found."
