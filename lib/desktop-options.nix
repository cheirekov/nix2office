{ lib }:
let
  inherit (lib) mkOption types;
in
{
  user = {
    name = mkOption {
      type = types.strMatching "[a-z_][a-z0-9_.-]{0,30}";
      default = "office";
      description = "Unix login name; distinct from the person's displayed full name.";
    };
    fullName = mkOption {
      type = types.str;
      default = "Офис";
      description = "Displayed name, including Unicode, for example Мария Димитрова.";
    };
    email = mkOption {
      type = types.str;
      default = "";
      description = "Optional contact metadata, not an automatically configured account.";
    };
  };
  apps = {
    browser = mkOption {
      type = types.enum [
        "firefox-esr"
        "chromium"
        "brave"
        "google-chrome"
      ];
      default = "firefox-esr";
      description = "Managed default browser.";
    };
    office = mkOption {
      type = types.enum [
        "libreoffice"
        "onlyoffice"
        "none"
      ];
      default = "libreoffice";
      description = "Office suite. The Bulgarian tabbed profile applies to LibreOffice.";
    };
    pdfEditor = mkOption {
      type = types.enum [
        "none"
        "pdfarranger"
        "xournalpp"
        "both"
      ];
      default = "none";
      description = "Optional PDF page tools and/or annotation editor; Atril remains the reader.";
    };
    artcraft = lib.mkEnableOption "experimental WordCraft, GridCraft, DeckCraft and PdfCraft alongside the main office suite";
    nextcloud = mkOption {
      type = types.bool;
      default = true;
      description = "Install and autostart the Nextcloud sync client.";
    };
  };
  keyboard.bulgarian = mkOption {
    type = types.enum [
      "phonetic"
      "bds"
    ];
    default = "phonetic";
    description = "Bulgarian traditional phonetic or standard BDS, alongside English US.";
  };
  vpn = {
    wireguard = mkOption {
      type = types.bool;
      default = true;
      description = "Offer WireGuard tools; connection profiles are imported into NetworkManager.";
    };
    tailscale = mkOption {
      type = types.bool;
      default = false;
      description = "Enable Tailscale and its Trayscale desktop interface; sign-in remains interactive.";
    };
    zerotier = mkOption {
      type = types.bool;
      default = false;
      description = "Enable ZeroTier; network membership may require controller approval.";
    };
    zerotierNetworks = mkOption {
      type = types.listOf (types.strMatching "[0-9a-fA-F]{16}");
      default = [ ];
      description = "Public ZeroTier network IDs. Removing one does not automatically leave it.";
    };
  };
}
