{ lib, ... }:
{
  imports = [ ./disk.nix ];
  nix2office.bootMode = lib.mkDefault "bios";
}
