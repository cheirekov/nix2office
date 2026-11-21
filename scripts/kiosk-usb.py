"""Mount USB flash volumes for the kiosk and service its Openbox eject menu."""
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import shlex
import signal
import socket
import stat
import subprocess
import sys
from xml.sax.saxutils import escape

ROOT = Path("/run/nix2office-usb")
VOLUMES = ROOT / "volumes"
SOCKET = ROOT / "eject.sock"
ALIAS = re.compile(r"USB-[1-9][0-9]*")
FILESYSTEMS = {"vfat": "vfat", "exfat": "exfat", "ntfs": "ntfs3"}


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=10)


def command(*args):
    result = run(*args)
    if result.returncode:
        raise OSError(result.stderr.strip() or f"{args[0]} exited {result.returncode}")
    return result.stdout


def disk_sequence(name):
    return (Path("/sys/class/block") / name / "diskseq").read_text().strip()


def removable_media():
    columns = "KNAME,PATH,TYPE,TRAN,RM,FSTYPE,MOUNTPOINTS,MAJ:MIN"
    disks = json.loads(command("lsblk", "--json", "--tree", "--output", columns))["blockdevices"]
    for disk in disks:
        if disk["type"] != "disk" or disk["tran"] != "usb" or not disk["rm"]:
            continue
        try:
            sequence = disk_sequence(disk["kname"])
        except FileNotFoundError:
            continue
        yield (disk["kname"], sequence), disk.get("children") or [disk]


def mount_volume(disk, volume, alias, owner):
    path = Path(volume["path"])
    if not stat.S_ISBLK(path.stat().st_mode):
        raise OSError("Not a block device")
    dev = path.stat().st_rdev
    if f"{os.major(dev)}:{os.minor(dev)}" != volume["maj:min"] or disk_sequence(disk[0]) != disk[1]:
        raise OSError("USB device changed during detection")
    dest = VOLUMES / alias
    dest.mkdir()
    options = f"ro,nosuid,nodev,noexec,nosymfollow,uid={owner.pw_uid},gid={owner.pw_gid},umask=077"
    try:
        command("mount", "--internal-only", "-t", FILESYSTEMS[volume["fstype"]],
                "-o", options, str(path), str(dest))
    except (OSError, subprocess.TimeoutExpired):
        # A timeout can occur after the mount syscall completed.
        if os.path.ismount(dest):
            command("umount", "--lazy", str(dest))
        dest.rmdir()
        raise


def remove_volume(alias, detached=False):
    dest = VOLUMES / alias
    if os.path.ismount(dest):
        if detached:
            command("umount", "--lazy", str(dest))
        else:
            command("umount", str(dest))
    dest.rmdir()


def monitor(user):
    import pyudev

    owner = pwd.getpwnam(user)
    VOLUMES.mkdir(mode=0o755, exist_ok=True)
    # Clean up a previous instance that was terminated without running finally.
    for dest in VOLUMES.iterdir():
        if ALIAS.fullmatch(dest.name):
            remove_volume(dest.name, detached=True)
    SOCKET.unlink(missing_ok=True)
    devices = pyudev.Monitor.from_netlink(pyudev.Context())
    devices.filter_by(subsystem="block")
    devices.start()
    mounted = {}  # alias -> (disk identity, partition kernel name)
    ejected = set()
    failed = set()

    def rescan():
        present = dict(removable_media())
        available = {(disk, volume["kname"]) for disk, volumes in present.items() for volume in volumes}
        ejected.intersection_update(present)
        failed.intersection_update(available)
        for alias, identity in list(mounted.items()):
            if identity not in available:
                remove_volume(alias, detached=True)
                del mounted[alias]
        known = set(mounted.values())
        for disk, volumes in present.items():
            if disk in ejected:
                continue
            for volume in volumes:
                identity = (disk, volume["kname"])
                if (
                    identity not in known and identity not in failed
                    and volume["type"] in ("disk", "part")
                    and volume["fstype"] in FILESYSTEMS
                    and not any(volume["mountpoints"] or [])
                ):
                    alias = next(f"USB-{i}" for i in range(1, len(mounted) + 2) if f"USB-{i}" not in mounted)
                    try:
                        mount_volume(disk, volume, alias, owner)
                    except (OSError, subprocess.TimeoutExpired) as error:
                        failed.add(identity)
                        print(f"{alias}: {error}", file=sys.stderr, flush=True)
                        continue
                    mounted[alias] = identity
                    print(f"Mounted {alias} read-only", flush=True)

    def eject(alias):
        if not ALIAS.fullmatch(alias) or alias not in mounted:
            return "Флашката вече не е налична."
        disk = mounted[alias][0]
        # Suppress remount until a physical unplug, including on a partial eject.
        ejected.add(disk)
        for name, (identity, _) in list(mounted.items()):
            if identity == disk:
                try:
                    remove_volume(name)
                except (OSError, subprocess.TimeoutExpired):
                    return "Флашката е заета. Затвори файловете и опитай пак."
                del mounted[name]
        return "Можеш безопасно да извадиш флашката."

    def stop(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as server, selectors.DefaultSelector() as sel:
            old_umask = os.umask(0o077)
            try:
                server.bind(str(SOCKET))
            finally:
                os.umask(old_umask)
            os.chown(SOCKET, owner.pw_uid, owner.pw_gid)
            server.listen(4)
            sel.register(devices, selectors.EVENT_READ)
            sel.register(server, selectors.EVENT_READ)
            rescan()
            while True:
                for key, _ in sel.select():
                    if key.fileobj is devices:
                        if devices.poll(timeout=0) is not None:
                            rescan()
                    else:
                        peer, _ = server.accept()
                        with peer:
                            peer.settimeout(1)
                            try:
                                alias = peer.recv(32).decode("ascii")
                                peer.sendall(eject(alias).encode())
                            except (OSError, UnicodeError):
                                continue
    finally:
        SOCKET.unlink(missing_ok=True)
        for alias in mounted:
            remove_volume(alias, detached=True)


def menu(terminal):
    print("<openbox_pipe_menu>")
    aliases = sorted(
        (path.name for path in VOLUMES.glob("USB-*") if ALIAS.fullmatch(path.name)),
        key=lambda alias: int(alias.split("-")[1]),
    )
    if not aliases:
        print('<separator label="Няма включени флашки" />')
    for alias in aliases:
        action = shlex.join([terminal, "-e", sys.executable, __file__, "eject", alias])
        print(f'<item label="Извади {alias}"><action name="Execute"><command>{escape(action)}</command></action></item>')
    print("</openbox_pipe_menu>")


def request_eject(alias):
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as client:
        client.settimeout(20)
        try:
            client.connect(str(SOCKET))
            client.sendall(alias.encode())
            print(client.recv(1024).decode())
        except OSError:
            print("Киоскът не потвърди изваждането. Остави флашката включена.")
    input("Enter за затваряне.")


if __name__ == "__main__":
    action, value = sys.argv[1:]
    {"monitor": monitor, "menu": menu, "eject": request_eject}[action](value)
