{ pkgs, database }:
let
  indexed = import (database.outPath + "/default.nix") { inherit pkgs; };
  # Keep the OS stable. Temporary commands use the index producer's exact pin.
  source = "github:NixOS/nixpkgs/${database.inputs.nixpkgs.rev}";
  launcher = pkgs.writeShellScriptBin "comma" ''
    unset NIX_PATH
    export COMMA_NIXPKGS_FLAKE=${pkgs.lib.escapeShellArg source}
    # Cache choices, but re-resolve store paths after a database/pin update.
    export COMMA_CACHING=1
    exec ${indexed.comma-with-db}/bin/comma "$@"
  '';
in
pkgs.symlinkJoin {
  name = "nix2office-comma-small-db";
  paths = [ launcher ];
  postBuild = ''ln -s comma "$out/bin/,"'';
  meta.mainProgram = "comma";
  passthru = {
    smallDatabase = indexed.nix-index-small-database;
    nixpkgsRevision = database.inputs.nixpkgs.rev;
    locator = indexed.nix-index-with-small-db;
  };
}
