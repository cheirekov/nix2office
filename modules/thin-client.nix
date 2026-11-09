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
  smartcard = builtins.elem "smartcard" thin.redirect;
  xml = s: builtins.replaceStrings [ "&" "<" ">" ] [ "&amp;" "&lt;" "&gt;" ] s;
  appLabel =
    app:
    let
      base = lib.last (lib.splitString "\\" app);
      trimmed = lib.removeSuffix ".exe" base;
    in
    if trimmed == "" then app else trimmed;
  configJson = pkgs.writeText "rdp-config.json" (
    builtins.toJSON {
      credentials = thin.credentials;
      redirect = thin.redirect;
      fullscreen = thin.fullscreen;
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
    exec ${pkgs.python3}/bin/python ${../scripts/rdp-launch.py} --config ${configJson} --password-file ${lib.escapeShellArg thin.passwordFile} "$@"
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
            entry (appLabel app) app ''${launcher} --profile "${p.name}" --app "${app}"''
          )
        ) p.remoteApps
      ) thin.profiles;
    in
    lib.listToAttrs (full ++ apps);
  menuEntry = label: command: ''
    <item label="${xml label}">
      <action name="Execute"><command>${xml command}</command></action>
    </item>'';
  fullItems = lib.concatMapStringsSep "\n" (
    p: menuEntry "RDP — ${p.name}" "${launcher} --profile ${lib.escapeShellArg p.name}"
  ) thin.profiles;
  appItems = lib.concatMapStringsSep "\n" (
    p:
    lib.concatMapStringsSep "\n" (
      app:
      menuEntry "${appLabel app} (${p.name})" "${launcher} --profile ${lib.escapeShellArg p.name} --app ${lib.escapeShellArg app}"
    ) p.remoteApps
  ) thin.profiles;
  menuXml = ''
    <?xml version="1.0" encoding="UTF-8"?>
    <openbox_menu xmlns="http://openbox.org/3.4/menu">
      <menu id="root-menu" label="Nix2office">
    ${fullItems}
    ${appItems}
        <separator />
        <item label="Настройки на мрежата">
          <action name="Execute"><command>${pkgs.networkmanagerapplet}/bin/nm-connection-editor</command></action>
        </item>
        <item label="Терминал">
          <action name="Execute"><command>${pkgs.xterm}/bin/xterm</command></action>
        </item>
        <item label="Звук">
          <action name="Execute"><command>${pkgs.pavucontrol}/bin/pavucontrol</command></action>
        </item>
        <item label="Системен монитор">
          <action name="Execute"><command>${pkgs.xterm}/bin/xterm -e ${pkgs.htop}/bin/htop</command></action>
        </item>
        <separator />
        <item label="Рестартирай">
          <action name="Execute"><command>${pkgs.systemd}/bin/systemctl reboot</command></action>
        </item>
        <item label="Изключи">
          <action name="Execute"><command>${pkgs.systemd}/bin/systemctl poweroff</command></action>
        </item>
      </menu>
    </openbox_menu>
  '';
in
{
  config = lib.mkIf enabled {
    assertions = [
      {
        assertion = thin.profiles != [ ];
        message = "The RDP thin client requires at least one profile.";
      }
    ];
    environment.systemPackages = [
      (import ../packages/freerdp-vaapi.nix { inherit pkgs; })
    ]
    ++ lib.optionals thinOnly [
      pkgs.xterm
      pkgs.networkmanagerapplet
    ];
    services.pcscd.enable = smartcard;
    security.polkit = lib.mkIf thinOnly {
      enable = true;
      extraConfig = ''
        polkit.addRule(function(action, subject) {
          if (subject.user === ${builtins.toJSON cfg.user.name}) {
            if (action.id === "org.freedesktop.login1.reboot"
                || action.id === "org.freedesktop.login1.reboot-multiple-sessions"
                || action.id === "org.freedesktop.login1.power-off"
                || action.id === "org.freedesktop.login1.power-off-multiple-sessions"
                || action.id.indexOf("org.freedesktop.NetworkManager.") === 0) {
              return polkit.Result.YES;
            }
          }
          return polkit.Result.NOT_HANDLED;
        });
      '';
    };
    services.xserver.windowManager.openbox.enable = thinOnly;
    services.displayManager.autoLogin = lib.mkIf thinOnly {
      enable = true;
      user = cfg.user.name;
    };
    home-manager.users.${cfg.user.name} = {
      xdg.desktopEntries = entries;
      xdg.configFile."openbox/menu.xml" = lib.mkIf thinOnly {
        text = menuXml;
      };
      xdg.configFile."openbox/autostart" = lib.mkIf thinOnly {
        text = ''
          ${launcher} --profile "${(lib.head thin.profiles).name}" --wait-secret-timeout 60 --wait-network-timeout 120 --attempts 6 --backoff 5 &
        '';
        executable = true;
      };
    };
  };
}
