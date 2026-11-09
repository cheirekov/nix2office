{ pkgs }:
# FreeRDP 3 with FFmpeg VA-API hardware H.264 decoding enabled (software
# fallback). OpenH264 is disabled so the libavcodec backend is selected; its
# WITH_FFMPEG_HWACCEL path auto-uses VA-API on Linux when a driver is present.
pkgs.freerdp.overrideAttrs (old: {
  cmakeFlags = (old.cmakeFlags or [ ]) ++ [
    "-DWITH_OPENH264=FALSE"
    "-DWITH_FFMPEG_HWACCEL=ON"
  ];
  meta = (old.meta or { }) // {
    description = (old.meta.description or "FreeRDP") + " with VA-API H.264 decoding";
  };
})
