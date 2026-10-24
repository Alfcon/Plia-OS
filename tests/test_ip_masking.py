import ipaddress
import json
from unittest.mock import MagicMock, patch

import modules.network_tools as nt


def _cp(stdout="", stderr="", rc=0):
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = rc
    return r


def test_get_ipv4_parses():
    data = json.dumps([{"ifname": "eth0", "addr_info": [
        {"family": "inet6", "local": "fe80::1"},
        {"family": "inet", "local": "192.168.1.42", "prefixlen": 24},
    ]}])
    with patch("subprocess.run", return_value=_cp(stdout=data)):
        assert nt._get_ipv4("eth0") == "192.168.1.42/24"


def test_get_ipv4_none_when_no_inet():
    data = json.dumps([{"ifname": "eth0", "addr_info": []}])
    with patch("subprocess.run", return_value=_cp(stdout=data)):
        assert nt._get_ipv4("eth0") is None


def test_random_host_in_subnet_stays_in_range_and_skips():
    cur = "192.168.1.42/24"
    new = nt._random_host_in_subnet(cur, avoid={"192.168.1.42"})
    addr, prefix = new.split("/")
    assert prefix == "24"
    net = ipaddress.ip_network("192.168.1.0/24")
    assert ipaddress.ip_address(addr) in net
    assert addr not in {"192.168.1.0", "192.168.1.255", "192.168.1.1", "192.168.1.42"}


def test_random_subnet_too_small():
    import pytest
    with pytest.raises(ValueError):
        nt._random_host_in_subnet("10.0.0.1/31", avoid=set())


def test_show_ip():
    with patch.object(nt, "_resolve_ip_iface", return_value="eth0"), \
         patch.object(nt, "_get_ipv4", return_value="192.168.1.42/24"):
        assert nt.show_ip() == "eth0: 192.168.1.42/24"


def test_show_ip_no_ipv4():
    with patch.object(nt, "_resolve_ip_iface", return_value="eth0"), \
         patch.object(nt, "_get_ipv4", return_value=None):
        assert "no ipv4" in nt.show_ip().lower()


def test_randomize_local_ip_saves_original_and_changes():
    store = MagicMock()
    store.get_fact.return_value = None
    with patch.object(nt, "_resolve_ip_iface", return_value="eth0"), \
         patch.object(nt, "_get_ipv4", return_value="192.168.1.42/24"), \
         patch.object(nt, "_apply_ip", return_value=None), \
         patch.object(nt, "get_memory_store", return_value=store):
        res = nt.randomize_local_ip()
    assert "→" in res
    store.remember.assert_called_once()
    key, val = store.remember.call_args.args
    assert key == "original_ip_eth0" and val == "192.168.1.42/24"


def test_randomize_local_ip_apply_error():
    store = MagicMock(); store.get_fact.return_value = None
    with patch.object(nt, "_resolve_ip_iface", return_value="eth0"), \
         patch.object(nt, "_get_ipv4", return_value="192.168.1.42/24"), \
         patch.object(nt, "_apply_ip", return_value="permission denied"), \
         patch.object(nt, "get_memory_store", return_value=store):
        assert "failed" in nt.randomize_local_ip().lower()


def test_set_local_ip_validates():
    assert "invalid" in nt.set_local_ip("eth0", "not-an-ip").lower()
    assert "invalid" in nt.set_local_ip("eth0", "192.168.1.5").lower()   # no prefix


def test_set_local_ip_applies():
    store = MagicMock(); store.get_fact.return_value = None
    with patch.object(nt, "_resolve_ip_iface", return_value="eth0"), \
         patch.object(nt, "_get_ipv4", return_value="192.168.1.42/24"), \
         patch.object(nt, "_apply_ip", return_value=None), \
         patch.object(nt, "get_memory_store", return_value=store):
        res = nt.set_local_ip("eth0", "192.168.1.77/24")
    assert "192.168.1.77/24" in res
    store.remember.assert_called_once()


def test_restore_ip_no_saved():
    store = MagicMock(); store.get_fact.return_value = None
    with patch.object(nt, "_resolve_ip_iface", return_value="eth0"), \
         patch.object(nt, "get_memory_store", return_value=store):
        assert "no original" in nt.restore_ip().lower()


def test_restore_ip_applies_saved():
    store = MagicMock(); store.get_fact.return_value = "192.168.1.42/24"
    with patch.object(nt, "_resolve_ip_iface", return_value="eth0"), \
         patch.object(nt, "_get_ipv4", return_value="192.168.1.99/24"), \
         patch.object(nt, "_apply_ip", return_value=None), \
         patch.object(nt, "get_memory_store", return_value=store):
        res = nt.restore_ip()
    assert "restored" in res.lower() and "192.168.1.42/24" in res


def test_apply_ip_permission_gate():
    with patch.object(nt, "_has_ip_admin", return_value=False), \
         patch("subprocess.run") as run:
        msg = nt._apply_ip("eth0", "192.168.1.7/24", "192.168.1.42/24")
    assert "permission" in msg.lower()
    run.assert_not_called()


def test_resolve_ip_iface_named_found():
    data = json.dumps([{"ifname": "eth0"}, {"ifname": "wlan0"}])
    with patch("subprocess.run", return_value=_cp(stdout=data)):
        assert nt._resolve_ip_iface("wlan0") == "wlan0"


def test_resolve_ip_iface_named_not_found():
    import pytest
    data = json.dumps([{"ifname": "eth0"}])
    with patch("subprocess.run", return_value=_cp(stdout=data)):
        with pytest.raises(ValueError):
            nt._resolve_ip_iface("wlan9")


def test_resolve_ip_iface_default_route():
    ifaces = json.dumps([{"ifname": "eth0"}, {"ifname": "lo"}])
    route = json.dumps([{"dst": "default", "dev": "eth0"}])
    with patch("subprocess.run", side_effect=[_cp(stdout=ifaces), _cp(stdout=route)]):
        assert nt._resolve_ip_iface("") == "eth0"


def test_resolve_ip_iface_never_raises_on_oserror():
    import pytest
    with patch("subprocess.run", side_effect=OSError("no ip binary")):
        with pytest.raises(ValueError):   # OSError swallowed -> ValueError (caught by tools)
            nt._resolve_ip_iface("")


def test_apply_ip_add_before_del_order():
    calls = []
    def _rec(cmd, *a, **k):
        calls.append(cmd)
        return _cp(rc=0)
    with patch.object(nt, "_has_ip_admin", return_value=True), \
         patch("subprocess.run", side_effect=_rec):
        assert nt._apply_ip("eth0", "192.168.1.7/24", "192.168.1.42/24") is None
    # first ip call adds the new addr, a later call deletes the old
    joined = [" ".join(c) for c in calls]
    add_i = next(i for i, s in enumerate(joined) if "addr add 192.168.1.7/24" in s)
    del_i = next(i for i, s in enumerate(joined) if "addr del 192.168.1.42/24" in s)
    assert add_i < del_i


def test_apply_ip_add_exists_is_tolerated():
    def _run(cmd, *a, **k):
        if "add" in cmd:
            return _cp(stderr="RTNETLINK answers: File exists", rc=2)
        return _cp(rc=0)
    with patch.object(nt, "_has_ip_admin", return_value=True), \
         patch("subprocess.run", side_effect=_run):
        assert nt._apply_ip("eth0", "192.168.1.7/24", "192.168.1.42/24") is None


def test_apply_ip_add_real_error():
    with patch.object(nt, "_has_ip_admin", return_value=True), \
         patch("subprocess.run", return_value=_cp(stderr="permission denied", rc=2)):
        msg = nt._apply_ip("eth0", "192.168.1.7/24", None)
    assert "permission denied" in msg.lower()


def test_apply_ip_oserror_never_raises():
    with patch.object(nt, "_has_ip_admin", return_value=True), \
         patch("subprocess.run", side_effect=OSError("boom")):
        msg = nt._apply_ip("eth0", "192.168.1.7/24", None)
    assert "failed" in msg.lower()
