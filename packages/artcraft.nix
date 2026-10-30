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
  # fc-list's formatter cannot emit NULs (\0 prints "0"), and font paths can
  # contain newlines. Use the API to list files without parsing shell code.
  fontFiles =
    pkgs.runCommandCC "artcraft-font-files"
      {
        nativeBuildInputs = [ pkgs.pkg-config ];
        buildInputs = [ pkgs.fontconfig ];
      }
      ''
        mkdir -p "$out/bin"
        cat > font-files.c <<'EOF'
        #include <fontconfig/fontconfig.h>
        #include <stdio.h>
        #include <string.h>

        int main(void) {
          FcConfig *config = FcInitLoadConfigAndFonts();
          FcPattern *pattern = FcPatternCreate();
          FcObjectSet *objects = FcObjectSetBuild(FC_FILE, NULL);
          if (!config || !pattern || !objects) return 1;
          FcFontSet *fonts = FcFontList(config, pattern, objects);
          if (!fonts) return 1;
          int failed = 0;
          for (int i = 0; i < fonts->nfont; i++) {
            FcChar8 *file = NULL;
            if (FcPatternGetString(fonts->fonts[i], FC_FILE, 0, &file) == FcResultMatch) {
              size_t size = strlen((const char *)file) + 1;
              if (fwrite(file, 1, size, stdout) != size) failed = 1;
            }
          }
          if (fflush(stdout) != 0) failed = 1;
          FcFontSetDestroy(fonts);
          FcObjectSetDestroy(objects);
          FcPatternDestroy(pattern);
          FcConfigDestroy(config);
          return failed;
        }
        EOF
        $CC -Wall -Wextra -Werror font-files.c -o "$out/bin/artcraft-font-files" \
          $(pkg-config --cflags --libs fontconfig)
      '';
  # WordCraft 0.12 scans font files itself, ignoring Fontconfig and NixOS's
  # store-backed font directories. Its Flatpak scan path is usable without
  # rebuilding (and losing the release's embedded craft-fonts). Project the
  # current Fontconfig file list there in a private mount namespace, rather
  # than installing links in ~/.fonts or changing HOME/XDG settings.
  wordcraftFonts = pkgs.writeShellApplication {
    name = "wordcraft-fonts";
    runtimeInputs = [
      pkgs.bubblewrap
      pkgs.coreutils
    ];
    text = ''
      font_view=$(mktemp -d -t wordcraft-fonts.XXXXXXXX)
      trap 'rm -rf -- "$font_view"' EXIT
      mkdir "$font_view/fonts"

      # Fontconfig expands system/user configuration, including FONTCONFIG_FILE
      # and XDG_DATA_HOME. NUL separators preserve spaces and newlines in paths;
      # collections/variable fonts may return the same file more than once.
      ${fontFiles}/bin/artcraft-font-files > "$font_view/list"
      sort -zu "$font_view/list" -o "$font_view/list"
      index=0
      while IFS= read -r -d "" file; do
        case "''${file,,}" in
          *.ttf|*.otf|*.ttc|*.otc)
            if [[ -r "$file" ]]; then
              ln -s -- "$file" "$font_view/fonts/$index.''${file##*.}"
              index=$((index + 1))
            fi
            ;;
        esac
      done < "$font_view/list"

      # /run/host usually does not exist on NixOS. Create it in a private /run
      # while preserving the host's entries (including symlinks and sockets).
      # Keep the filesystem, session, devices and networking otherwise intact.
      mounts=(--bind / / --tmpfs /run)
      shopt -s nullglob dotglob
      for entry in /run/*; do
        if [[ "$entry" == /run/host ]]; then
          continue
        elif [[ -L "$entry" ]]; then
          mounts+=(--symlink "$(readlink -- "$entry")" "$entry")
        else
          mounts+=(--bind "$entry" "$entry")
        fi
      done
      mounts+=(--dir /run/host)
      for entry in /run/host/*; do
        if [[ "$entry" != /run/host/fonts ]]; then
          mounts+=(--bind "$entry" "$entry")
        fi
      done
      bwrap "''${mounts[@]}" \
        --ro-bind "$font_view/fonts" /run/host/fonts \
        -- "$@"
    '';
  };
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
        ${pkgs.lib.optionalString (name == "wordcraft") ''
          mkdir -p "$out/libexec"
          for program in wordcraft wordcraft-cli; do
            mv "$out/bin/$program" "$out/libexec/$program"
            makeWrapper ${pkgs.lib.getExe wordcraftFonts} "$out/bin/$program" \
              --add-flags "$out/libexec/$program"
          done
        ''}
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
