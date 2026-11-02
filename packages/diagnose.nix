{ pkgs }:
pkgs.writeShellApplication {
  name = "nix2office-diagnose";
  runtimeInputs = with pkgs; [
    python3
    kmod
    pciutils
    util-linux
    iproute2
    systemd
    bluez
    pulseaudio
    mesa-demos
    libva-utils
  ];
  text = ''
    exec ${pkgs.python3}/bin/python ${../scripts}/diagnose.py "$@"
  '';
  meta.description = "Read-only hardware and desktop diagnostics for Nix2office";
}
