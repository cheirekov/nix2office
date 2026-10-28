{
  config,
  pkgs,
  lib,
  ...
}:
let
  uint = value: {
    type = "uint";
    inherit value;
  };
  officeDefaults = pkgs.writeText "libreoffice-defaults.xcu" ''
    <?xml version="1.0" encoding="UTF-8"?>
    <oor:items xmlns:oor="http://openoffice.org/2001/registry">
      <item oor:path="/org.openoffice.Office.UI.ToolbarMode/Applications/Writer"><prop oor:name="Active" oor:op="fuse"><value>notebookbar.ui</value></prop></item>
      <item oor:path="/org.openoffice.Office.UI.ToolbarMode/Applications/Calc"><prop oor:name="Active" oor:op="fuse"><value>notebookbar.ui</value></prop></item>
      <item oor:path="/org.openoffice.Office.UI.ToolbarMode/Applications/Impress"><prop oor:name="Active" oor:op="fuse"><value>notebookbar.ui</value></prop></item>
      <item oor:path="/org.openoffice.Office.Linguistic/General"><prop oor:name="DefaultLocale" oor:op="fuse"><value>bg-BG</value></prop></item>
      <item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="FirstRun" oor:op="fuse"><value>false</value></prop></item>
      <item oor:path="/org.openoffice.Setup/Product"><prop oor:name="WhatsNew" oor:op="fuse"><value>false</value></prop></item>
    </oor:items>
  '';
  desktopShortcut = name: icon: exec: ''
    [Desktop Entry]
    Type=Application
    Name=${name}
    Icon=${icon}
    Exec=${exec}
    Terminal=false
  '';
  desktopLaunchers = {
    browser = desktopShortcut "Интернет" "firefox-esr" "firefox-esr";
    writer = desktopShortcut "Текстови документи" "libreoffice-writer" "libreoffice --writer";
    calc = desktopShortcut "Електронни таблици" "libreoffice-calc" "libreoffice --calc";
    nextcloud = desktopShortcut "Nextcloud" "Nextcloud" "nextcloud";
  };
in
{
  home.stateVersion = "26.05";
  programs.home-manager.enable = true;
  xdg.enable = true;
  xdg.userDirs = {
    enable = true;
    createDirectories = true;
    desktop = "${config.home.homeDirectory}/Desktop";
    documents = "${config.home.homeDirectory}/Documents";
    download = "${config.home.homeDirectory}/Downloads";
  };
  home.packages = [
    pkgs.greybird
    pkgs.adwaita-icon-theme
  ];
  gtk = {
    enable = true;
    theme = {
      name = "Greybird";
      package = pkgs.greybird;
    };
    iconTheme = {
      name = "Adwaita";
      package = pkgs.adwaita-icon-theme;
    };
    font = {
      name = "DejaVu Sans";
      size = 10;
    };
    gtk3.extraConfig.gtk-application-prefer-dark-theme = false;
  };
  xfconf.settings = {
    xsettings = {
      "Net/ThemeName" = "Greybird";
      "Net/IconThemeName" = "Adwaita";
      "Gtk/FontName" = "DejaVu Sans 10";
    };
    xfwm4 = {
      "general/theme" = "Greybird";
      "general/button_layout" = "O|HMC";
      "general/use_compositing" = false;
      "general/workspace_count" = 1;
      "general/title_font" = "DejaVu Sans Bold 10";
    };
    thunar = {
      "misc-single-click" = false;
      "last-view" = "ThunarDetailsView";
    };
    xfce4-desktop = {
      "desktop-icons/style" = 2;
      "desktop-icons/file-icons/show-home" = true;
      "desktop-icons/file-icons/show-trash" = true;
      "desktop-icons/file-icons/show-filesystem" = false;
      "desktop-icons/single-click" = false;
      "backdrop/screen0/monitorHDMI-1/workspace0/image-style" = 0;
      "backdrop/screen0/monitorHDMI-1/workspace0/color-style" = 0;
      "backdrop/screen0/monitorHDMI-1/workspace0/rgba1" = [
        0.13
        0.30
        0.43
        1.0
      ];
    };
    xfce4-panel = {
      "configver" = 2;
      "panels" = [ 1 ];
      "panels/dark-mode" = false;
      "panels/panel-1/position" = "p=10;x=0;y=0";
      "panels/panel-1/position-locked" = true;
      "panels/panel-1/length" = uint 100;
      "panels/panel-1/size" = (uint 40);
      "panels/panel-1/plugin-ids" = [
        10
        11
        12
        13
        14
        15
        18
        16
        17
      ];
      "plugins/plugin-10" = "whiskermenu";
      "plugins/plugin-10/button-title" = "Меню";
      "plugins/plugin-10/show-button-title" = true;
      "plugins/plugin-10/show-button-icon" = true;
      "plugins/plugin-11" = "tasklist";
      "plugins/plugin-11/show-handle" = false;
      "plugins/plugin-11/show-labels" = true;
      "plugins/plugin-11/grouping" = (uint 1);
      "plugins/plugin-12" = "separator";
      "plugins/plugin-12/expand" = true;
      "plugins/plugin-12/style" = (uint 0);
      "plugins/plugin-13" = "systray";
      "plugins/plugin-14" = "pulseaudio";
      "plugins/plugin-14/mixer-command" = "pavucontrol";
      "plugins/plugin-15" = "notification-plugin";
      "plugins/plugin-16" = "clock";
      "plugins/plugin-16/digital-layout" = (uint 3);
      "plugins/plugin-16/digital-time-format" = "%H:%M";
      "plugins/plugin-16/digital-date-format" = "%d.%m.%Y";
      "plugins/plugin-17" = "showdesktop";
      "plugins/plugin-18" = "xkb";
      "plugins/plugin-18/display-type" = uint 1;
      "plugins/plugin-18/display-name" = uint 1;
      "plugins/plugin-18/group-policy" = uint 0;
    };
    xfce4-keyboard-shortcuts = {
      "commands/custom/Super_L" = "xfce4-popup-whiskermenu";
      "commands/custom/<Super>e" = "thunar";
      "commands/custom/<Super>l" = "xflock4";
    };
    xfce4-session."general/SaveOnExit" = false;
  };

  xdg.configFile."autostart/nextcloud.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Nextcloud
    Exec=${pkgs.nextcloud-client}/bin/nextcloud --background
    Icon=Nextcloud
    Terminal=false
  '';
  # XFCE resolves URLs through Exo helpers as well as MIME associations.
  xdg.dataFile."xfce4/helpers/firefox-esr.desktop".text = ''
    [Desktop Entry]
    Version=1.0
    Type=X-XFCE-Helper
    Name=Firefox ESR
    Icon=firefox-esr
    X-XFCE-Category=WebBrowser
    X-XFCE-Binaries=firefox-esr;
    X-XFCE-Commands=%B;
    X-XFCE-CommandsWithParameter=%B "%s";
  '';
  xdg.desktopEntries.sound-settings = {
    name = "Звук";
    genericName = "Настройки на звука";
    exec = "pavucontrol";
    icon = "multimedia-volume-control";
    categories = [
      "Settings"
      "HardwareSettings"
    ];
    settings = {
      "X-XFCE-SettingsDialog" = "true";
      "X-XFCE-SettingsName" = "Sound";
    };
  };
  xdg.mimeApps = {
    enable = true;
    defaultApplications = {
      "text/html" = [ "firefox-esr.desktop" ];
      "x-scheme-handler/http" = [ "firefox-esr.desktop" ];
      "x-scheme-handler/https" = [ "firefox-esr.desktop" ];
      "application/pdf" = [ "atril.desktop" ];
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document" = [ "writer.desktop" ];
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" = [ "calc.desktop" ];
      "application/vnd.openxmlformats-officedocument.presentationml.presentation" = [ "impress.desktop" ];
    };
  };
  # Copies are writable user files: store symlinks display padlock overlays.
  home.activation.desktopLaunchers = lib.hm.dag.entryAfter [ "linkGeneration" ] (
    lib.concatStringsSep "\n" (
      lib.mapAttrsToList (name: contents: ''
        if [ -L "$HOME/Desktop/${name}.desktop" ]; then
          run rm "$HOME/Desktop/${name}.desktop"
        fi
        run install -Dm755 ${pkgs.writeText "${name}.desktop" contents} "$HOME/Desktop/${name}.desktop"
      '') desktopLaunchers
    )
  );
  home.activation.defaultBrowserHelper = lib.hm.dag.entryAfter [ "linkGeneration" ] ''
    helpers="$HOME/.config/xfce4/helpers.rc"
    run mkdir -p "$(dirname "$helpers")"
    if [ ! -e "$helpers" ]; then
      run touch "$helpers"
    fi
    if ! ${pkgs.gnugrep}/bin/grep -q '^WebBrowser=' "$helpers"; then
      run ${pkgs.bash}/bin/bash -c 'printf "WebBrowser=firefox-esr\n" >> "$1"' -- "$helpers"
    elif ${pkgs.gnugrep}/bin/grep -q '^WebBrowser=firefox$' "$helpers" || {
      ${pkgs.gnugrep}/bin/grep -q '^WebBrowser=custom-WebBrowser$' "$helpers" &&
      ${pkgs.gnugrep}/bin/grep -qE '^X-XFCE-Commands=firefox(;|$)' "$HOME/.local/share/xfce4/helpers/custom-WebBrowser.desktop"
    }; then
      # Repair the original missing Firefox ESR helper, preserving other helpers.
      run ${pkgs.gnused}/bin/sed -i 's/^WebBrowser=.*/WebBrowser=firefox-esr/' "$helpers"
    fi
  '';
  home.activation.seedLibreOffice = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    target="$HOME/.config/libreoffice/4/user/registrymodifications.xcu"
    if [ ! -e "$target" ]; then
      run install -Dm600 ${officeDefaults} "$target"
    else
      # Migrate the invalid mode identifier used by the initial office profile.
      run ${pkgs.gnused}/bin/sed -i 's|<value>Tabbed</value>|<value>notebookbar.ui</value>|g' "$target"
    fi
  '';
}
