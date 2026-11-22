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
  usbStorage = thinOnly && thin.usbStorage;
  freerdp = import ../packages/freerdp-vaapi.nix {
    inherit pkgs;
    kioskUsb = usbStorage;
  };
  usbPython = pkgs.python3.withPackages (ps: [ ps.pyudev ]);
  usbDialog = pkgs.writeShellScript "nix2office-usb-dialog" ''
    exec ${pkgs.util-linux}/bin/flock -n "$XDG_RUNTIME_DIR/nix2office-usb-dialog.lock" \
      ${pkgs.python3}/bin/python ${../scripts/kiosk-usb.py} dialog ${pkgs.zenity}/bin/zenity ${pkgs.xdotool}/bin/xdotool
  '';
  usbAction = pkgs.writeShellScript "nix2office-rdp-action" ''
    case "$1:${"$"}{2-}" in
      key:) printf '%s\n' 'ctrl+alt+f8' ;;
      # FreeRDP requires a nonempty reply to its event subscription query.
      xevent:) printf '%s\n' 'none' ;;
      key:ctrl+alt+f8)
        ${usbDialog} </dev/null >/dev/null 2>&1 &
        printf '%s\n' 'key-local'
        ;;
    esac
  '';
  smartcard = builtins.elem "smartcard" thin.redirect;
  xml = s: builtins.replaceStrings [ "&" "<" ">" ] [ "&amp;" "&lt;" "&gt;" ] s;
  appLabel =
    app:
    let
      base = lib.last (lib.splitString "\\" app);
      trimmed = lib.removeSuffix ".exe" base;
    in
    if trimmed == "" then app else trimmed;
  isPath =
    app:
    lib.substring 0 2 app == "||"
    || lib.hasInfix "\\" app
    || lib.hasInfix "/" app
    || (lib.stringLength app >= 2 && lib.substring 1 1 app == ":");
  configJson = pkgs.writeText "rdp-config.json" (
    builtins.toJSON {
      credentials = thin.credentials;
      redirect = thin.redirect;
      usb_storage = usbStorage;
      usb_action = if usbStorage then toString usbAction else null;
      kiosk_shared = thinOnly;
      fullscreen = thin.fullscreen;
      unicode_keyboard = thin.unicodeKeyboard;
      gfx = thin.gfx;
      shared = "/home/${cfg.user.name}/Shared";
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
    export PATH=${lib.makeBinPath [ freerdp ]}:$PATH
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
      shells = lib.concatMap (
        p:
        lib.imap1 (
          j: app:
          lib.nameValuePair "rdp-shell-${p.name}-${toString j}" (
            entry "${appLabel app} (Alternate shell)" app ''${launcher} --profile "${p.name}" --shell "${app}"''
          )
        ) (builtins.filter isPath p.remoteApps)
      ) thin.profiles;
    in
    lib.listToAttrs (full ++ apps ++ shells);
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
  shellItems = lib.concatMapStringsSep "\n" (
    p:
    lib.concatMapStringsSep "\n" (
      app:
      menuEntry "${appLabel app} - Alternate shell (${p.name})" "${launcher} --profile ${lib.escapeShellArg p.name} --shell ${lib.escapeShellArg app}"
    ) (builtins.filter isPath p.remoteApps)
  ) thin.profiles;
  menuXml = ''
    <?xml version="1.0" encoding="UTF-8"?>
    <openbox_menu xmlns="http://openbox.org/3.4/menu">
      <menu id="root-menu" label="Nix2office">
    ${fullItems}
    ${appItems}
    ${shellItems}
        ${menuEntry "Файлов мениджър — Shared" "${pkgs.thunar}/bin/thunar /home/${cfg.user.name}/Shared"}
        ${lib.optionalString usbStorage (menuEntry "Безопасно изваждане на USB" (toString usbDialog))}
        <item label="Прекрати RDP сесията и върни менюто">
          <action name="Execute"><command>${pkgs.procps}/bin/pkill -x xfreerdp</command></action>
        </item>
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
      {
        assertion = !thin.usbStorage || thinOnly;
        message = "USB storage redirection is available only in the thin kiosk role.";
      }
    ];
    environment.systemPackages = [
      freerdp
    ]
    ++ lib.optionals thinOnly [
      pkgs.xterm
      pkgs.networkmanagerapplet
      pkgs.thunar
    ];
    services.pcscd.enable = smartcard;
    systemd.services.nix2office-usb = lib.mkIf usbStorage {
      description = "Mount removable USB storage for the Nix2office kiosk";
      wantedBy = [ "multi-user.target" ];
      path = [ pkgs.util-linux ];
      serviceConfig = {
        ExecStart = "${usbPython}/bin/python ${../scripts/kiosk-usb.py} monitor ${cfg.user.name}";
        RuntimeDirectory = "nix2office-usb";
        RuntimeDirectoryMode = "0755";
        Restart = "on-failure";
        RestartSec = "3s";
      };
    };
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
    home-manager.users.${cfg.user.name} = { lib, ... }: {
      home.activation.kioskShared = lib.mkIf thinOnly (
        lib.hm.dag.entryAfter [ "writeBoundary" ] ''
          if [ ! -e "$HOME/Shared" ] && [ ! -L "$HOME/Shared" ]; then
            run ${pkgs.coreutils}/bin/mkdir -m 700 "$HOME/Shared"
          fi
        ''
      );
      xdg.desktopEntries = entries;
      xdg.configFile."openbox/menu.xml" = lib.mkIf thinOnly {
        text = menuXml;
      };
      xdg.configFile."openbox/autostart" = lib.mkIf thinOnly {
        text = ''
          (
            ${lib.optionalString usbStorage ''
              ${lib.getExe pkgs.zenity} --info --timeout=4 --title="Nix2office" \
                --text="Изваждане на флашка: Ctrl+Alt+F8" || true
            ''}
            exec ${launcher} --profile "${(lib.head thin.profiles).name}" --wait-secret-timeout 60 --wait-network-timeout 120 --attempts 6 --backoff 5
          ) &
        '';
        executable = true;
      };
    };
  };
}
