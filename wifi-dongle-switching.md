# Switching Between Internal Wi-Fi and a USB Wi-Fi Dongle on Linux Mint

**Machine:** Prime-16, Linux Mint 22.3 (Cinnamon, Ubuntu 24.04 "noble" base)
**Kernel:** `7.0.0-31-generic` (HWE kernel, package version `7.0.0-31.31~24.04.1`)
**Internal card:** Intel AX211, driver `iwlwifi` / `iwlmvm`, interface `wlp0s20f3`
**Dongle:** Realtek RTL8812AU (USB ID `0bda:8812`), in-kernel driver `rtw88_8812au`, interface `wlx8c882b000d0f`

There are two ways to disable the internal card:

| Method | What it does | Good for freeze testing? |
|---|---|---|
| Quick (NetworkManager) | Stops using the card, but the driver stays loaded | No |
| Full (blacklist driver) | Stops the driver from loading at all | Yes |

If you're testing whether `iwlwifi` is causing system freezes, use the **full method**.

---

## Part 1: Disable Internal Wi-Fi and Use the Dongle

### Step 1: Kernel modules (no install needed)

On the 7.0 HWE kernel there is no `linux-modules-extra` package (`apt` reports
"Unable to locate package"). The drivers that used to live there are now in
`linux-modules-7.0.0-31-generic`, which is already installed. The RTL8812AU
driver (`rtw88_8812au`) is included and needs no DKMS package.

Ubuntu now ships a few hardware-specific groups as separate optional packages.
They're only needed for that specific hardware:

| Package (`…-$(uname -r)`) | For |
|---|---|
| `linux-modules-iwlwifi` | Newer Intel Wi-Fi driver builds |
| `linux-modules-ipu6` / `ipu7` / `usbio` / `vision` | Intel MIPI laptop webcams |
| `linux-modules-evdi` | DisplayLink USB docks/monitors |
| `linux-modules-nvidia-*` | Prebuilt signed NVIDIA drivers |

To check what's installed:

```bash
dpkg -l | grep "$(uname -r)"
```

### Step 2: Plug in the dongle and confirm it's detected ✅ Confirmed working

```bash
lsusb          # the dongle should be listed
nmcli device   # look for a new wifi device, usually wlx<mac>
```

Confirmed output:

```
Bus 001 Device 010: ID 0bda:8812 Realtek Semiconductor Corp. RTL8812AU 802.11a/b/g/n/ac 2T2R DB WLAN Adapter

wlp0s20f3          wifi      connected               Alf&Leisa50
wlx8c882b000d0f    wifi      disconnected            --
```

Check which driver the dongle uses. It must **not** be `iwlwifi`:

```bash
basename $(readlink /sys/class/net/wlx*/device/driver)   # expect: rtw88_8812au
```

To see whether the driver loaded properly, check `dmesg`:

```bash
sudo dmesg | grep -iE 'rtw88|wlx'
```

A healthy plug-in looks like this:

```
rtw88_8812au 1-2:1.0: Firmware version 52.14.0, H2C version 0
usb 1-2: USB disconnect, device number 9          <- normal: re-enumerates once after firmware load
rtw88_8812au 1-2:1.0: Firmware version 52.14.0, H2C version 0
rtw88_8812au 1-2:1.0 wlx8c882b000d0f: renamed from wlan0
```

The one disconnect/reconnect right after the first firmware load is expected and isn't a fault.

If no `wlx…` device appears, the dongle needs a driver. Look up its USB ID from `lsusb`.

### Step 3a: Quick method (driver stays loaded)

```bash
nmcli device set wlp0s20f3 managed no
```

To undo it:

```bash
nmcli device set wlp0s20f3 managed yes
```

### Step 3b: Full method (driver never loads)

```bash
sudo tee /etc/modprobe.d/disable-internal-wifi.conf > /dev/null <<'CONF'
blacklist iwlmvm
blacklist iwlwifi
install iwlwifi /bin/false
CONF
sudo update-initramfs -u
sudo reboot
```

- The `install iwlwifi /bin/false` line blocks the driver even if something else tries to load it.
- Bluetooth uses a separate driver and keeps working.

### Step 4: Verify and connect with the dongle

```bash
lsmod | grep iwl   # should print nothing
nmcli device       # only wlx8c882b000d0f should appear as a wifi device
```

Connect using the network applet in the panel, or run:

```bash
nmcli device wifi connect "Alf&Leisa50" ifname wlx8c882b000d0f --ask
```

(`--ask` prompts for the password so it doesn't end up in your shell history.)

### Optional: One-off test without changing any files

1. At the GRUB menu, highlight the Linux Mint entry and press `e`.
2. Find the line starting with `linux` and add this to the end of it:
   ```
   module_blacklist=iwlmvm,iwlwifi
   ```
3. Press `Ctrl+X` to boot.

This only lasts for that one boot. It's handy for repeating the recovery-mode "enable networking" test.

---

## Part 2: Disable the Dongle and Re-enable Internal Wi-Fi

### Step 1: Remove the blacklist

```bash
sudo rm /etc/modprobe.d/disable-internal-wifi.conf
sudo update-initramfs -u
```

### Step 2: Load the internal Wi-Fi driver

Either load it right away:

```bash
sudo modprobe iwlwifi   # loads iwlmvm automatically
```

...or reboot.

If you used the **quick method** instead, run this:

```bash
nmcli device set wlp0s20f3 managed yes
```

### Step 3: Stop using the dongle

The simplest option is to **unplug it**. To leave it plugged in but idle:

```bash
nmcli device disconnect wlx8c882b000d0f
nmcli device set wlx8c882b000d0f autoconnect no
```

To let it auto-connect again later:

```bash
nmcli device set wlx8c882b000d0f autoconnect yes
```

### Step 4: Verify

```bash
lsmod | grep iwl   # iwlwifi and iwlmvm should be listed
nmcli device       # wlp0s20f3 should show as connected or ready
```

---

## Harmless `dmesg` messages (not related to the dongle or freezes)

- `warning: 'Socket Thread' uses wireless extensions which will stop working for Wi-Fi 7 hardware` comes from an app (usually the browser) using the old Wi-Fi API.
- `SGI XFS…`, `JFS…`, `QNX4 filesystem…` appear when something (the Disks app, GParted) probes for filesystems.
- `sd 0:0:0:0: [sda] … Attached SCSI removable disk` followed by `capacity change … to 0` is a USB drive being plugged in and removed.

---

## Interpreting Freeze Test Results

- **Stable for several days on the dongle with `iwlwifi` blacklisted:** strong evidence the internal Wi-Fi driver is causing the freezes.
- **Still freezing:** points more toward RAM/CPU instability. Run memtest86+ next:
  ```bash
  sudo apt install memtest86+
  sudo update-grub
  ```
  Then choose memtest86+ from the GRUB menu and let it run overnight.
