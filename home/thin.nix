{
  config,
  lib,
  ...
}:
{
  options.nix2office = import ../lib/desktop-options.nix { inherit lib; };
  config = {
    home.stateVersion = "26.05";
    programs.home-manager.enable = true;
    xdg.enable = true;
    xdg.configFile."nix2office/user.json".text = builtins.toJSON config.nix2office.user;
  };
}
