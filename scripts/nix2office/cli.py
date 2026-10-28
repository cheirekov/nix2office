"""CLI entry points shared by the menus and the explicit initializer."""
import argparse
import json
from pathlib import Path
import sys

from .config import ConfigError, load_machine, validate_machine
from .deployment import PreparationError, check_destination, completion, pinned_source, prepare, summary
from .hardware import describe_inventory, probe
from .wizard import Cancelled, load_inventory, wizard


def main(legacy=False):
    parser = argparse.ArgumentParser(description="Prepare a private Nix2office flake. No build, installation or remote changes.")
    parser.add_argument("--config", type=Path, help="Read machine.toml instead of showing menus")
    parser.add_argument("--check", action="store_true", help="Validate --config only; no keys, passwords or files")
    parser.add_argument("--output", type=Path, default=Path(".deployment"))
    parser.add_argument("--source", help="Immutable public project Git URL with a 40-digit revision")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Public Nix2office checkout (must be clean)")
    parser.add_argument("--update", action="store_true", help="Update a managed deployment, preserving keys/passwords; requires --config")
    parser.add_argument("--generate-passwords", action="store_true", help="Use random passwords, saved only in ignored credentials.json")
    parser.add_argument("--probe", action="store_true", help="Print read-only hardware inventory as JSON, then exit")
    parser.add_argument("--recommend", action="store_true", help="Show target hardware and recommendations only; no files, secrets or menus")
    parser.add_argument("--target", help="Probe target through already trusted SSH access")
    parser.add_argument("--ssh-config", type=Path)
    parser.add_argument("--ssh-socket", type=Path)
    parser.add_argument("--hardware-json", type=Path, help="Use saved --probe facts in the menus")
    if legacy:
        parser.add_argument("--hostname", default="office-pc")
        parser.add_argument("--disk")
        parser.add_argument("--admin-network")
        parser.add_argument("--admin-key", type=Path)
    args = parser.parse_args()
    if args.check and not args.config:
        parser.error("--check requires --config")
    if args.update and not args.config:
        parser.error("--update requires --config")
    if args.probe and (args.config or args.update or args.check or args.hardware_json or args.recommend):
        parser.error("--probe cannot be combined with configuration preparation")
    if args.recommend and (args.config or args.update or args.check):
        parser.error("--recommend cannot be combined with configuration preparation")
    if args.hardware_json and args.target is not None:
        parser.error("choose --hardware-json or --target, not both")
    try:
        if args.probe:
            print(json.dumps(probe(args.target, args.ssh_config, args.ssh_socket), ensure_ascii=False, indent=2))
            return 0
        if args.recommend:
            inventory = load_inventory(args.hardware_json) if args.hardware_json else probe(args.target, args.ssh_config, args.ssh_socket)
            describe_inventory(inventory)
            return 0
        if args.config:
            machine = load_machine(args.config)
            generated = args.generate_passwords
            dest = args.output
        elif legacy:
            if not all((args.disk, args.admin_network, args.admin_key)):
                parser.error("use --config, or supply --disk, --admin-network and --admin-key")
            machine = validate_machine({"hostname": args.hostname, "disk": args.disk,
                "admin": {"network": args.admin_network, "ssh_public_key": args.admin_key.expanduser().read_text().strip()}})
            generated, dest = True, args.output
        else:
            # Fail before collecting input if no immutable source/output is available.
            source = pinned_source(args.project, args.source)
            machine, dest, generated = wizard(args)
        if args.check:
            summary(machine)
            print("machine.toml: OK. Няма създадени файлове или тайни.")
            return 0
        source = pinned_source(args.project, args.source)
        dest = check_destination(dest, args.update)
        dest = prepare(machine, dest, source, generated, args.update)
        summary(machine)
        completion(dest, machine, generated, args.update)
        return 0
    except (Cancelled, KeyboardInterrupt):
        print("\nОтказано.", file=sys.stderr)
        return 130
    except (ConfigError, PreparationError, OSError) as e:
        # OSError may include filenames, but never print file contents or child output.
        message = str(e) if isinstance(e, (ConfigError, PreparationError)) else f"File operation failed ({type(e).__name__})."
        print("Error: " + message, file=sys.stderr)
        return 1
