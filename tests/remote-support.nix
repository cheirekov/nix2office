# Pure evaluation shared by the Python integration test and flake checks.
{ flake }:
let
  f = flake;
  lib = f.inputs.nixpkgs.lib;
  check =
    mode:
    let
      c =
        (f.nixosConfigurations.office-example.extendModules {
          modules = [
            {
              nix2office.remoteSupport = {
                inherit mode;
                idServer = "example.org";
                relayServer = "example.org";
                publicKey = "test";
              };
            }
          ];
        }).config;
      active = mode != "off";
      unit = c.systemd.services.rustdesk or { };
    in
    {
      inherit mode;
      assertions = builtins.all (x: x.assertion) c.assertions;
      service = builtins.hasAttr "rustdesk" c.systemd.services;
      userService = builtins.hasAttr "nix2office-rustdesk" c.home-manager.users.office.systemd.user.services;
      package = builtins.elem "rustdesk" (map lib.getName c.environment.systemPackages);
      config = if active then unit.serviceConfig else { };
      wantedBy = unit.wantedBy or [ ];
      lightdm = c.services.xserver.displayManager.lightdm.extraConfig;
    };
in
map check [
  "off"
  "consent"
  "unattended"
]
