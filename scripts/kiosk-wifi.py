"""A Wi-Fi picker for the kiosk. NetworkManager owns activation and profiles."""

import argparse
from contextlib import contextmanager
import os
import subprocess

import gi

gi.require_version("NM", "1.0")
from gi.repository import Gio, GLib, NM


AP_FLAGS = getattr(NM, "80211ApFlags")
SECURITY_FLAGS = getattr(NM, "80211ApSecurityFlags")


def call_nm(start, finish, *args):
    """Wait for a libnm async reply while keeping its D-Bus context running."""
    loop = GLib.MainLoop()
    cancellable = Gio.Cancellable()
    results = []

    def completed(_object, result):
        results.append(result)
        loop.quit()

    def cancel(*_args):
        cancellable.cancel()
        return GLib.SOURCE_REMOVE

    timer = GLib.timeout_source_new_seconds(12)
    timer.set_callback(cancel)
    timer.attach()
    try:
        start(*args, cancellable, completed)
        loop.run()
        return finish(results[0])
    finally:
        timer.destroy()


def wait_until(ready, seconds):
    if ready():
        return True
    loop = GLib.MainLoop()

    def check(*_args):
        if ready():
            loop.quit()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def timed_out(*_args):
        loop.quit()
        return GLib.SOURCE_REMOVE

    check_timer = GLib.timeout_source_new(200)
    check_timer.set_callback(check)
    deadline = GLib.timeout_source_new_seconds(seconds)
    deadline.set_callback(timed_out)
    for timer in (check_timer, deadline):
        timer.attach()
    try:
        loop.run()
    finally:
        check_timer.destroy()
        deadline.destroy()
    return ready()


def key_management(ap):
    flags = ap.get_wpa_flags() | ap.get_rsn_flags()
    if flags & SECURITY_FLAGS.KEY_MGMT_PSK:
        return "wpa-psk"
    if flags & SECURITY_FLAGS.KEY_MGMT_SAE:
        return "sae"
    if flags or ap.get_flags() & AP_FLAGS.PRIVACY:
        return "advanced"
    return None


def wifi_devices(client):
    return [device for device in client.get_devices()
            if isinstance(device, NM.DeviceWifi) and device.get_managed()]


def is_connected(device, ap):
    return device.get_state() == NM.DeviceState.ACTIVATED and ap == device.get_active_access_point()


def scan(devices):
    scans = []
    for device in devices:
        if device.get_state() < NM.DeviceState.DISCONNECTED:
            continue
        before = device.get_last_scan()
        try:
            call_nm(device.request_scan_async, device.request_scan_finish)
        except GLib.Error:
            continue  # A rate-limited scan can still have usable cached results.
        scans.append((device, before))
    if scans:
        wait_until(lambda: all(device.get_last_scan() != before for device, before in scans), 5)


def access_points(devices):
    candidates = []
    for device in devices:
        for ap in device.get_access_points():
            ssid = ap.get_ssid()
            if ssid is not None and ssid.get_size():
                candidates.append((bytes(ssid.get_data()), key_management(ap), device, ap))
    candidates.sort(key=lambda row: (is_connected(row[2], row[3]), row[3].get_strength()),
                    reverse=True)
    unique = {}
    for ssid, key_mgmt, device, ap in candidates:
        unique.setdefault((ssid, key_mgmt), (ssid, key_mgmt, device, ap))
    return list(unique.values())


class Picker:
    def __init__(self, zenity, editor, client):
        self.zenity = zenity
        self.editor = editor
        self.client = client
        self.env = {**os.environ, "GSK_RENDERER": "cairo"}

    def dialog(self, *options):
        result = subprocess.run([self.zenity, *options], capture_output=True, text=True, env=self.env)
        # --extra-button outputs its label and uses the cancel exit status.
        value = result.stdout.removesuffix("\n")
        return value if result.returncode == 0 or value in ("Обнови", "Разширени") else None

    @contextmanager
    def working(self, text):
        with subprocess.Popen([
            self.zenity, "--progress", "--pulsate", "--no-cancel", "--title=Wi-Fi", f"--text={text}",
        ], stdin=subprocess.PIPE, env=self.env) as progress:
            try:
                yield
            finally:
                if progress.poll() is None:
                    progress.terminate()

    def connect(self, key_mgmt, device, ap, password, saved):
        path = ap.get_path()
        if saved:
            active = call_nm(self.client.activate_connection_async, self.client.activate_connection_finish,
                             saved, device, path)
        else:
            connection = NM.SimpleConnection.new()
            if key_mgmt:
                security = NM.SettingWirelessSecurity.new()
                security.set_property("key-mgmt", key_mgmt)
                security.set_property("psk", password)
                connection.add_setting(security)
            options = GLib.Variant("a{sv}", {"persist": GLib.Variant("s", "volatile")})
            active, _ = call_nm(self.client.add_and_activate_connection2,
                                self.client.add_and_activate_connection2_finish,
                                connection, device, path, options)

        finished = (NM.ActiveConnectionState.ACTIVATED, NM.ActiveConnectionState.DEACTIVATED)
        if not wait_until(lambda: active.get_state() in finished, 35):
            call_nm(self.client.deactivate_connection_async, self.client.deactivate_connection_finish, active)
            return None
        if active.get_state() != NM.ActiveConnectionState.ACTIVATED:
            return None
        if saved:
            return "Свързано."
        try:
            profile = active.get_connection()
            if profile and call_nm(profile.save_async, profile.save_finish):
                return "Свързано. Мрежата е запазена."
        except GLib.Error:
            pass
        return "Свързано. Профилът не можа да се запази."

    def run(self):
        refresh = True
        context = GLib.MainContext.default()
        while True:
            # Catch up with hotplug and NetworkManager changes while Zenity was open.
            while context.pending():
                context.iteration(False)
            devices = wifi_devices(self.client)
            enabled = self.client.wireless_get_enabled()
            if refresh and devices and enabled:
                with self.working("Търсене на безжични мрежи…"):
                    scan(devices)
            refresh = False
            networks = access_points(devices) if enabled else []
            if not devices:
                text = "Няма открит Wi-Fi адаптер. Включи го и натисни „Обнови“."
            elif not enabled:
                text = "Wi-Fi е изключен."
            else:
                text = "Избери мрежа." if networks else "Няма намерени мрежи."
            rows = []
            labels = {None: "Отворена", "wpa-psk": "WPA/WPA2", "sae": "WPA3", "advanced": "Разширена"}
            for i, (ssid, key_mgmt, device, ap) in enumerate(networks):
                name = "".join(c if c.isprintable() else "�" for c in ssid.decode("utf-8", "replace"))
                state = "Свързано" if is_connected(device, ap) else f"{ap.get_strength()}%"
                rows.extend([str(i), name, state, labels[key_mgmt]])
            selected = self.dialog(
                "--list", "--title=Wi-Fi", f"--text={text}", "--width=560", "--height=540",
                "--ok-label=Свържи", "--cancel-label=Към връзките",
                "--extra-button=Обнови", "--extra-button=Разширени", "--hide-column=1", "--print-column=1",
                "--column=ID", "--column=Мрежа", "--column=Сигнал", "--column=Защита", "--", *rows,
            )
            if selected == "Обнови":
                refresh = True
                continue
            if selected == "Разширени":
                subprocess.run([self.editor], check=False)
                return
            if not selected or not selected.isdecimal() or int(selected) >= len(networks):
                return
            _, key_mgmt, device, ap = networks[int(selected)]
            if is_connected(device, ap):
                return
            saved = next((profile for profile in device.get_available_connections()
                          if ap.connection_valid(profile)), None)
            if key_mgmt == "advanced" and not saved:
                self.dialog("--info", "--title=Wi-Fi", "--ok-label=Назад",
                            "--text=За тази мрежа използвай „Разширени“.")
                continue
            password = None
            if key_mgmt and not saved:
                password = self.dialog("--password", "--title=Парола за Wi-Fi",
                                       "--ok-label=Свържи", "--cancel-label=Назад")
                if password is None:
                    continue
            try:
                with self.working("Свързване към Wi-Fi…"):
                    message = self.connect(key_mgmt, device, ap, password, saved)
            except GLib.Error:
                message = None
            finally:
                del password
            if message:
                self.dialog("--info", "--title=Wi-Fi", "--ok-label=Към връзките", f"--text={message}")
                return
            if saved:
                error = "Запазеният профил не се свърза. Провери го от „Разширени“."
            else:
                error = "Свързването не успя. Провери паролата или избери друга мрежа."
            self.dialog("--error", "--title=Wi-Fi", "--ok-label=Назад", f"--text={error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zenity")
    parser.add_argument("editor")
    args = parser.parse_args()
    Picker(args.zenity, args.editor, NM.Client.new(None)).run()


if __name__ == "__main__":
    main()
