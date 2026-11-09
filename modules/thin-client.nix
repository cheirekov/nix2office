{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nix2office;
  thin = cfg.thinClient;
  enabled = cfg.role != "office";
  thinOnly = cfg.role == "thin";
  configJson = pkgs.writeText "rdp-config.json" (
    builtins.toJSON {
      credentials = thin.credentials;
      redirect = thin.redirect;
      home = "/home/${cfg.user.name}";
      profiles = map (p: {
        name = p.name;
        host = p.host;
        user = p.user;
        port = p.port;
        remote_apps = p.remoteApps;
      }) thin.profiles;
    }
  );
  launcher = pkgs.writeShellScript "nix2office-rdp-launch" ''
    exec ${pkgs.python3}/bin/python ${../scripts/rdp-launch.py} \
      --config ${configJson} \
      --password-file ${lib.escapeShellArg thin.passwordFile} "$@"
  '';
  entry = name: comment: exec: {
    inherit name comment exec;
    icon = "preferences-desktop-remote-desktop";
    terminal = false;
    categories = [
      "Network"
      "RemoteAccess"
    ];
    settings."X-Nix2office-Managed" = "true";
  };
  entries =
    let
      full = lib.imap1 (
        i: p:
        lib.nameValuePair "rdp-full-${toString i}" (
          entry "RDP — ${p.name}" "Пълна отдалечена сесия" ''${launcher} --profile "${p.name}"''
        )
      ) thin.profiles;
      apps = lib.concatMap (
        p:
        lib.imap1 (
          j: app:
          lib.nameValuePair "rdp-app-${p.name}-${toString j}" (
            entry app app ''${launcher} --profile "${p.name}" --app "${app}"''
          )
        ) p.remoteApps
      ) thin.profiles;
    in
    lib.listToAttrs (full ++ apps);
in
{
  config = lib.mkIf enabled {
    assertions = [
      {
        assertion = thin.profiles != [ ];
        message = "The RDP thin client requires at least one profile.";
      }
    ];
    environment.systemPackages = [ pkgs.freerdp ];
    services.xserver.windowManager.openbox.enable = thinOnly;
    services.displayManager.autoLogin = lib.mkIf thinOnly {
      enable = true;
      user = cfg.user.name;
    };
    home-manager.users.${cfg.user.name} = {
      xdg.desktopEntries = entries;
      xdg.configFile."openbox/autostart" = lib.mkIf thinOnly {
        text = ''
          ${launcher} --profile "${(lib.head thin.profiles).name}" &
        '';
        executable = true;
      };
    };
  };
}
