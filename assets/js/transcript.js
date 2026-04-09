// transcript.js
// Looks up the script phrase that corresponds to a given timecode (or range).
// Input format is a flat array of word objects: [{word, start, end}, ...]
// (Same format produced by Whisper word_timestamps in our project.)

const Transcript = {
  data: null,

  load(words) {
    this.data = words || [];
  },

  // Returns the words that overlap with [startSec, endSec]
  // If endSec is omitted or equal to startSec, finds words that contain that point.
  getWordsInRange(startSec, endSec) {
    if (!this.data) return [];
    const end = endSec == null ? startSec + 0.01 : endSec;
    return this.data.filter(w => w.end > startSec && w.start < end);
  },

  // Returns the script text spoken in the given range as a single string
  getPhraseInRange(startSec, endSec) {
    const words = this.getWordsInRange(startSec, endSec);
    if (words.length === 0) return '';
    return words.map(w => w.word).join(' ').replace(/\s+([.,;:!?])/g, '$1');
  },

  // For a single point: extends a small window around it (e.g. ±2s) to capture nearby words
  getPhraseAtTime(seconds, windowBefore = 0.5, windowAfter = 1.5) {
    return this.getPhraseInRange(seconds - windowBefore, seconds + windowAfter);
  }
};
