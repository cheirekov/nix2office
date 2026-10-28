{ pkgs }:
let
  base = pkgs.libreoffice.unwrapped;
  # Keep translations and dictionaries exactly aligned with the cached office binary.
  version = "25.8.5.2";
  langpack = pkgs.fetchurl {
    url = "https://downloadarchive.documentfoundation.org/libreoffice/old/${version}/deb/x86_64/LibreOffice_${version}_Linux_x86-64_deb_langpack_bg.tar.gz";
    hash = "sha256-0jKgujz2UQsfY22ym/7bdj4ytYmKoXhOupNjAhv1lKo=";
  };
  localized =
    pkgs.runCommand "libreoffice-bg-${version}"
      {
        nativeBuildInputs = [ pkgs.dpkg ];
        passthru = base.passthru // {
          inherit version;
          inherit (base) pname;
        };
        inherit (base) meta;
      }
      ''
        mkdir -p unpack extracted "$out"
        tar xf ${langpack} -C unpack
        for deb in unpack/*/DEBS/*.deb; do
          dpkg-deb -x "$deb" extracted
        done
        cp -a ${base}/. "$out/"
        chmod -R u+w "$out"
        cp -a extracted/opt/libreoffice25.8/. "$out/lib/libreoffice/"
        # Retarget internal entrypoints; shared library RPATHs may still use the base.
        while IFS= read -r -d $'\0' link; do
          target=$(readlink "$link")
          ln -sfn "$out''${target#${base}}" "$link"
        done < <(find "$out" -type l -lname '${base}/*' -print0)
        substituteInPlace "$out/lib/libreoffice/program/soffice" \
          --replace-warn '${base}' "$out"
        test -f "$out/lib/libreoffice/program/resource/bg/LC_MESSAGES/sw.mo"
        test -f "$out/lib/libreoffice/share/extensions/dict-bg/bg_BG.dic"
      '';
in
assert pkgs.lib.assertMsg (
  base.version == version
) "Update the Bulgarian language pack together with LibreOffice.";
pkgs.libreoffice.override { unwrapped = localized; }
