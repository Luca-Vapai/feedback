// player.js
// Wrapper around the YouTube IFrame API.
// The API is loaded via the <script src="...iframe_api"></script> tag in piece.html.
// YT.Player becomes available after onYouTubeIframeAPIReady fires.

const Player = {
  yt: null,
  ready: false,
  onReadyCallback: null,

  init(youtubeId, containerId, onReady) {
    this.onReadyCallback = onReady;
    // The API may not be loaded yet — defer until it is.
    if (window.YT && window.YT.Player) {
      this._create(youtubeId, containerId);
    } else {
      window.onYouTubeIframeAPIReady = () => this._create(youtubeId, containerId);
    }
  },

  _create(youtubeId, containerId) {
    this.yt = new YT.Player(containerId, {
      videoId: youtubeId,
      playerVars: {
        rel: 0,
        modestbranding: 1,
        playsinline: 1
      },
      events: {
        onReady: () => {
          this.ready = true;
          if (this.onReadyCallback) this.onReadyCallback();
        }
      }
    });
  },

  getCurrentTime() {
    if (!this.ready) return 0;
    return this.yt.getCurrentTime();
  },

  pause() {
    if (this.ready) this.yt.pauseVideo();
  },

  play() {
    if (this.ready) this.yt.playVideo();
  },

  seekTo(seconds) {
    if (this.ready) this.yt.seekTo(seconds, true);
  }
};

// Format seconds as M:SS.cs (e.g. 1:23.45)
function formatTime(seconds) {
  if (seconds == null || isNaN(seconds)) return '';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const cs = Math.floor((seconds % 1) * 100);
  return `${m}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '0')}`;
}
