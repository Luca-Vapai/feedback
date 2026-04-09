// comments.js
// In-memory comment state with localStorage persistence.
// Storage key includes project + piece + version so each piece-version has its own draft.

const Comments = {
  storageKey: null,
  list: [],
  changeListeners: [],

  init(projectId, pieceId, version) {
    this.storageKey = `souts-review-${projectId}-${pieceId}-v${version}`;
    this.load();
  },

  load() {
    try {
      const raw = localStorage.getItem(this.storageKey);
      this.list = raw ? JSON.parse(raw) : [];
    } catch (err) {
      console.error('Failed to load comments from localStorage:', err);
      this.list = [];
    }
    this._notify();
  },

  save() {
    try {
      localStorage.setItem(this.storageKey, JSON.stringify(this.list));
    } catch (err) {
      console.error('Failed to save comments to localStorage:', err);
    }
  },

  clear() {
    this.list = [];
    localStorage.removeItem(this.storageKey);
    this._notify();
  },

  add(comment) {
    if (!comment.comment_id) {
      comment.comment_id = `c-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    }
    this.list.push(comment);
    this.save();
    this._notify();
    return comment.comment_id;
  },

  update(commentId, updates) {
    const idx = this.list.findIndex(c => c.comment_id === commentId);
    if (idx === -1) return false;
    this.list[idx] = { ...this.list[idx], ...updates };
    this.save();
    this._notify();
    return true;
  },

  delete(commentId) {
    this.list = this.list.filter(c => c.comment_id !== commentId);
    this.save();
    this._notify();
  },

  get(commentId) {
    return this.list.find(c => c.comment_id === commentId);
  },

  getAll() {
    return this.list.slice();
  },

  count() {
    return this.list.length;
  },

  onChange(callback) {
    this.changeListeners.push(callback);
  },

  _notify() {
    this.changeListeners.forEach(cb => cb(this.list));
  }
};
