// Minimal, self-contained h264ify: on YouTube, report VP8/VP9/AV1 as
// unsupported so the player falls back to H.264 (avc1), which Bay Trail and
// other older Intel GPUs can decode in hardware via VA-API.
(function () {
  function makeChecker(original) {
    return function (type) {
      if (type === undefined) return '';
      var blocked = ['webm', 'vp8', 'vp9', 'av01'];
      for (var i = 0; i < blocked.length; i++) {
        if (type.indexOf(blocked[i]) !== -1) return '';
      }
      return original(type);
    };
  }
  var video = document.createElement('video');
  video.__proto__.canPlayType = makeChecker(video.canPlayType.bind(video));
  var mse = window.MediaSource;
  if (mse !== undefined) {
    mse.isTypeSupported = makeChecker(mse.isTypeSupported.bind(mse));
  }
})();
