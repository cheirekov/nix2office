{ pkgs }:
pkgs.writeShellApplication {
  name = "nix2office-measure";
  runtimeInputs = with pkgs; [
    python3
    libva-utils
    ffmpeg-full
  ];
  text = ''
    exec ${pkgs.python3}/bin/python ${../scripts}/measure.py "$@"
  '';
  meta.description = "Short, read-only Nix2office performance measurements";
}
