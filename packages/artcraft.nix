# Pinned upstream Linux binaries; experimental additions, not default document handlers.
{ pkgs }:
let
  releases = {
    wordcraft = {
      version = "0.12.0";
      hash = "sha256-zZq9DuehG5ha8cFXFlMzLJYHfl3MSLXhh7VcgvR1oz4=";
    };
    gridcraft = {
      version = "0.13.0";
      hash = "sha256-IMbFbsH/1rvP/ubN7ljPa1yt0vSgSkNg3XzGTVOtl+U=";
    };
    deckcraft = {
      version = "0.12.0";
      hash = "sha256-SkENPKpCPoc9Dcq1HJjgZYj1W9/PA+nB6RQJqGwI3j4=";
    };
    pdfcraft = {
      version = "0.15.0";
      hash = "sha256-sWehjGCnsynwWlu/l+Mtxniq0/jVhm2OQ3j/JCc/gxM=";
    };
  };
  libraries = with pkgs; [
    libGL
    vulkan-loader
    wayland
    libxkbcommon
    fontconfig
    libx11
    libxcb
    libxcursor
    libxi
    libxrandr
  ];
  make =
    name: release:
    pkgs.stdenv.mkDerivation {
      pname = name;
      inherit (release) version;
      src = pkgs.fetchurl {
        url = "https://github.com/storytold/${name}/releases/download/v${release.version}/${name}-${release.version}-linux-x86_64.tar.gz";
        inherit (release) hash;
      };
      nativeBuildInputs = [
        pkgs.autoPatchelfHook
        pkgs.makeWrapper
      ];
      buildInputs = [
        pkgs.stdenv.cc.cc.lib
        pkgs.alsa-lib
      ];
      dontBuild = true;
      installPhase = ''
        runHook preInstall
        mkdir -p "$out"
        cp -r bin share "$out/"
        for executable in "$out"/bin/*; do
          wrapProgram "$executable" --prefix LD_LIBRARY_PATH : ${pkgs.lib.makeLibraryPath libraries}
        done
        runHook postInstall
      '';
      meta = {
        description = "Experimental ArtCraft ${name} desktop application";
        homepage = "https://getartcraft.com/apps/${name}";
        license = pkgs.lib.licenses.asl20;
        platforms = [ "x86_64-linux" ];
        mainProgram = name;
        sourceProvenance = [ pkgs.lib.sourceTypes.binaryNativeCode ];
      };
    };
in
pkgs.lib.mapAttrs make releases
