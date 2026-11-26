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
  hasRdp = thin.profiles != [ ];
  kioskClients = builtins.fromJSON (builtins.readFile ../scripts/nix2office/kiosk-clients.json);
  clientNames = lib.optional (thinOnly && thin.awsWorkSpaces) "aws-workspaces" ++ thin.nativeClients;
  needsLoginBrowser = lib.any (name: kioskClients.${name}.browser or false) clientNames;
  clientCommand =
    name:
    let
      client = kioskClients.${name};
      exe = lib.getExe' pkgs.${client.package} client.program;
    in
    exe
    + lib.optionalString (
      name == "amazon-dcv" && thin.dcvConnectionFile != null
    ) " ${lib.escapeShellArg thin.dcvConnectionFile}"
    + lib.optionalString (
      name == "tigervnc" && thin.vncPasswordFile != null
    ) " -PasswordFile ${lib.escapeShellArg thin.vncPasswordFile}";
  usbStorage = thinOnly && hasRdp && thin.usbStorage;
  portalLauncher =
    portal:
    pkgs.writeShellScript "nix2office-portal-${portal.name}" ''
      set -eu
      umask 077
      profile=$(${pkgs.coreutils}/bin/mktemp -d "$XDG_RUNTIME_DIR/nix2office-portal.XXXXXXXX")
      trap '${pkgs.coreutils}/bin/rm -rf -- "$profile"' EXIT
      ${lib.getExe pkgs.firefox-esr} --no-remote --profile "$profile" --kiosk ${lib.escapeShellArg portal.url}
    '';
  profileNames = map (p: p.name) (thin.profiles ++ thin.portals) ++ clientNames;
  startupName =
    if thin.startupProfile == "" then (lib.head (profileNames ++ [ "" ])) else thin.startupProfile;
  startupPortal = lib.findFirst (p: p.name == startupName) null thin.portals;
  kioskRdp = "${launcher} --normalize-session-exit";
  rdpProfile = name: "${kioskRdp} --profile ${lib.escapeShellArg name}";
  usbHint = "Изваждане на флашка в RDP: Ctrl+Alt+F8";
  startupCommand =
    if builtins.elem startupName clientNames then
      clientCommand startupName
    else if startupPortal != null then
      toString (portalLauncher startupPortal)
    else
      "${rdpProfile startupName} --wait-dialog ${lib.getExe pkgs.zenity} --wait-secret-timeout 60 --wait-network-timeout 120 --attempts 6 --backoff 5";
  freerdp = import ../packages/freerdp-vaapi.nix {
    inherit pkgs;
    kioskUsb = usbStorage;
  };
  usbPython = pkgs.python3.withPackages (ps: [ ps.pyudev ]);
  usbDialog = pkgs.writeShellScript "nix2office-usb-dialog" ''
    exec ${pkgs.util-linux}/bin/flock -n "$XDG_RUNTIME_DIR/nix2office-usb-dialog.lock" \
      ${pkgs.python3}/bin/python ${../scripts/kiosk-usb.py} dialog ${pkgs.zenity}/bin/zenity ${pkgs.xdotool}/bin/xdotool ${lib.getLib pkgs.libx11}/lib/libX11.so.6 "$@"
  '';
  usbAction = pkgs.writeShellScript "nix2office-rdp-action" ''
    case "$1:${"$"}{2-}" in
      key:) printf '%s\n' 'ctrl+alt+f8' ;;
      # FreeRDP requires a nonempty reply to its event subscription query.
      xevent:) printf '%s\n' 'none' ;;
      key:ctrl+alt+f8)
        ${usbDialog} rdp </dev/null >/dev/null 2>&1 &
        printf '%s\n' 'key-local'
        ;;
    esac
  '';
  smartcard = hasRdp && builtins.elem "smartcard" thin.redirect;
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
      account_dialog = if thin.allowOtherAccount then lib.getExe pkgs.zenity else null;
      personal_dialog = if thin.allowPersonalConnections then lib.getExe pkgs.zenity else null;
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
      otherAccounts = lib.optionals thin.allowOtherAccount (
        lib.imap1 (
          i: p:
          lib.nameValuePair "rdp-other-account-${toString i}" (
            entry "Вход с друг акаунт — ${p.name}" "Въведи Windows потребител и парола" ''
              ${launcher} --profile "${p.name}" --other-account
            ''
          )
        ) thin.profiles
      );
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
    lib.listToAttrs (full ++ otherAccounts ++ apps ++ shells)
    // lib.optionalAttrs thin.allowPersonalConnections {
      rdp-personal = entry "Лични RDP връзки" "Добави или отвори лична връзка" "${launcher} --personal";
    };
  menuEntry = label: command: ''
    <item label="${xml label}">
      <action name="Execute"><command>${xml command}</command></action>
    </item>'';
  item = kind: label: command: { inherit kind label command; };
  connections =
    map (p: item "Отдалечен работен плот" p.name (rdpProfile p.name)) thin.profiles
    ++ map (p: item "Работен портал" p.name (toString (portalLauncher p))) thin.portals
    ++ lib.concatMap (
      p:
      map (
        app:
        item "Отдалечено приложение" "${appLabel (lib.removePrefix "||" app)} (${p.name})"
          "${rdpProfile p.name} --app ${lib.escapeShellArg app}"
      ) p.remoteApps
    ) thin.profiles
    ++ map (name: item "Клиент" kioskClients.${name}.label (clientCommand name)) clientNames
    ++ lib.optionals thin.allowOtherAccount (
      map (
        p: item "Друг акаунт" "Вход с друг акаунт — ${p.name}" "${rdpProfile p.name} --other-account"
      ) thin.profiles
    )
    ++ lib.optional thin.allowPersonalConnections (
      item "Лични" "Лични RDP връзки" "${launcher} --personal"
    );
  localItems = [
    (item "Локално" "Мрежа и Wi-Fi" networkSettings)
    (item "Локално" "Споделени файлове" "${lib.getExe pkgs.thunar} /home/${cfg.user.name}/Shared")
  ]
  ++ lib.optional usbStorage (item "Локално" "Безопасно изваждане на USB" (toString usbDialog));
  wifiPython = pkgs.python3.withPackages (ps: [ ps.pygobject3 ]);
  networkSettings = toString (
    pkgs.writeShellScript "nix2office-kiosk-wifi" ''
        export GI_TYPELIB_PATH=${config.networking.networkmanager.package}/lib/girepository-1.0
      exec ${wifiPython}/bin/python ${../scripts/kiosk-wifi.py} \
          ${lib.getExe pkgs.zenity} ${pkgs.networkmanagerapplet}/bin/nm-connection-editor
    ''
  );
  settings = [
    (item "Локално" "Мрежа" networkSettings)
    (item "Локално" "Звук" (lib.getExe pkgs.pavucontrol))
  ]
  ++ lib.optional cfg.devices.bluetooth (
    item "Локално" "Bluetooth" "${pkgs.blueman}/bin/blueman-manager"
  );
  diagnostics = [
    (item "Локално" "Терминал" (lib.getExe pkgs.xterm))
    (item "Локално" "Системен монитор" "${lib.getExe pkgs.xterm} -e ${lib.getExe pkgs.htop}")
  ]
  ++ lib.concatMap (
    p:
    map (
      app:
      item "Alternate shell" "${appLabel app} (${p.name})"
        "${rdpProfile p.name} --shell ${lib.escapeShellArg app}"
    ) (builtins.filter (app: isPath app && !(lib.hasPrefix "||" app)) p.remoteApps)
  ) thin.profiles;
  power = [
    (item "Локално" "Изключи" "${pkgs.systemd}/bin/systemctl poweroff")
    (item "Локално" "Рестартирай" "${pkgs.systemd}/bin/systemctl reboot")
  ];
  sections =
    lib.mapAttrs (section: lib.imap0 (i: details: details // { id = "${section}-${toString i}"; }))
      {
        main = connections ++ localItems;
        inherit settings diagnostics power;
      };
  submenus = [
    "settings"
    "Настройки"
    "Локално"
    "diagnostics"
    "Диагностика"
    "Локално"
    "power"
    "Изключване и рестарт"
    "Локално"
  ];
  kioskConnections = pkgs.writeShellScript "nix2office-kiosk-connections" ''
    zenity=${lib.getExe pkgs.zenity}
    flock=${pkgs.util-linux}/bin/flock
    usb_hint=${lib.escapeShellArg (lib.optionalString usbStorage usbHint)}
    ${lib.concatStringsSep "\n" (
      lib.mapAttrsToList (section: items: ''
        rows_${section}=( ${
          lib.escapeShellArgs (
            lib.concatMap (entry: [
              entry.id
              entry.label
              entry.kind
            ]) items
            ++ lib.optionals (section == "main") submenus
          )
        } )
      '') sections
    )}
    run_action() {
      case "$1" in
        network) ${networkSettings} ;;
        ${lib.optionalString (thin.startup == "auto") ''
          auto) ${startupCommand} ;;
        ''}
        ${lib.concatMapStringsSep "\n" (entry: "${entry.id}) ${entry.command} ;;") (
          lib.concatLists (lib.attrValues sections)
        )}
        *) return 1 ;;
      esac
    }
    ${builtins.readFile ../scripts/kiosk-connections.sh}
  '';
  showItems = lib.concatMapStringsSep "\n" (entry: menuEntry entry.label entry.command);
  menuGroup = id: label: items: ''
    <menu id="${id}" label="${label}">
      ${showItems items}
    </menu>
  '';
  menuXml = ''
    <?xml version="1.0" encoding="UTF-8"?>
    <openbox_menu xmlns="http://openbox.org/3.4/menu">
      <menu id="root-menu" label="Nix2office">
        ${menuEntry "Отвори екрана Връзки" (toString kioskConnections)}
        ${menuGroup "kiosk-direct" "Директно стартиране" connections}
        ${showItems localItems}
        ${lib.optionalString hasRdp (
          menuEntry "Прекрати RDP сесията и върни менюто" "${pkgs.procps}/bin/pkill -x xfreerdp"
        )}
        <separator />
        ${menuGroup "kiosk-settings" "Настройки" settings}
        ${menuGroup "kiosk-diagnostics" "Диагностика" diagnostics}
        ${menuGroup "kiosk-power" "Изключване и рестарт" power}
      </menu>
    </openbox_menu>
  '';
in
{
  config = lib.mkIf enabled {
    assertions = [
      {
        assertion = profileNames != [ ];
        message = "Add an RDP connection or a kiosk HTTPS portal or native client.";
      }
      {
        assertion =
          thinOnly
          || (
            thin.portals == [ ] && !thin.awsWorkSpaces && thin.startup == "auto" && thin.startupProfile == ""
          );
        message = "HTTPS portals, AWS WorkSpaces and startup selection require the thin kiosk role.";
      }
      {
        assertion = thinOnly || lib.all (name: kioskClients.${name}.hybrid or false) thin.nativeClients;
        message = "These native clients require the thin kiosk role.";
      }
      {
        assertion = lib.length profileNames == lib.length (lib.unique profileNames);
        message = "Kiosk connection names must be unique.";
      }
      {
        assertion =
          thin.startupProfile == ""
          || (thin.startup == "auto" && builtins.elem thin.startupProfile profileNames);
        message = "The automatic startup connection must name an existing profile.";
      }
      {
        assertion =
          hasRdp
          || (
            !thin.usbStorage
            && !thin.allowOtherAccount
            && !thin.allowPersonalConnections
            && thin.credentials != "sops"
          );
        message = "RDP permissions and secrets require an RDP profile.";
      }
      {
        assertion = !thin.usbStorage || thinOnly;
        message = "USB storage redirection is available only in the thin kiosk role.";
      }
    ];
    environment.systemPackages =
      lib.optional hasRdp freerdp
      ++ lib.optional (needsLoginBrowser || (thinOnly && thin.portals != [ ])) pkgs.firefox-esr
      ++ lib.optional needsLoginBrowser pkgs.xdg-utils
      ++ map (name: pkgs.${kioskClients.${name}.package}) clientNames
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
      xdg.mimeApps = lib.mkIf needsLoginBrowser {
        enable = true;
        defaultApplications = {
          "x-scheme-handler/http" = [ "firefox-esr.desktop" ];
          "x-scheme-handler/https" = [ "firefox-esr.desktop" ];
        };
      };
      xdg.configFile."openbox/menu.xml" = lib.mkIf thinOnly {
        text = menuXml;
      };
      xdg.configFile."openbox/autostart" = lib.mkIf thinOnly {
        text = ''
          ${lib.getExe pkgs.xsetroot} -solid '#202d39'
          ${kioskConnections}${lib.optionalString (thin.startup == "auto") " --auto"} &
        '';
        executable = true;
      };
    };
  };
}
