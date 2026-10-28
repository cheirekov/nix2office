{ pkgs, apps }:
let
  browsers = {
    firefox-esr = {
      name = "Firefox ESR";
      exec = "firefox-esr";
      icon = "firefox-esr";
      desktop = "firefox-esr.desktop";
      package = pkgs.firefox-esr;
    };
    chromium = {
      name = "Chromium";
      exec = "chromium";
      icon = "chromium";
      desktop = "chromium-browser.desktop";
      package = pkgs.chromium;
    };
    brave = {
      name = "Brave";
      exec = "brave";
      icon = "brave-browser";
      desktop = "brave-browser.desktop";
      package = pkgs.brave;
    };
    google-chrome = {
      name = "Google Chrome";
      exec = "google-chrome-stable";
      icon = "google-chrome";
      desktop = "google-chrome.desktop";
      package = pkgs.google-chrome;
    };
  };
in
{
  browser = browsers.${apps.browser};
  officePackages =
    if apps.office == "libreoffice" then
      [ (import ../packages/libreoffice-bg.nix { inherit pkgs; }) ]
    else
      pkgs.lib.optional (apps.office == "onlyoffice") pkgs.onlyoffice-desktopeditors;
  pdfPackages =
    pkgs.lib.optional (builtins.elem apps.pdfEditor [
      "pdfarranger"
      "both"
    ]) pkgs.pdfarranger
    ++ pkgs.lib.optional (builtins.elem apps.pdfEditor [
      "xournalpp"
      "both"
    ]) pkgs.xournalpp;
}
