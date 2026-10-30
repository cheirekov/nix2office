database:
{
  config,
  lib,
  pkgs,
  ...
}:
{
  options.nix2office.tools.comma.enable =
    lib.mkEnableOption "comma with a prebuilt small index and matching separate nixpkgs pin";
  config.environment.systemPackages = lib.mkIf config.nix2office.tools.comma.enable [
    (import ../packages/comma.nix { inherit pkgs database; })
  ];
}
