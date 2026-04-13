// form.js
// Renders the comment form inside a modal and manages create/edit flow.

const FormUI = {
  modal: null,
  container: null,
  title: null,
  closeBtn: null,
  editingId: null,

  init() {
    this.modal = document.getElementById('form-modal');
    this.container = document.getElementById('form-container');
    this.title = document.getElementById('form-title');
    this.closeBtn = document.getElementById('btn-close-form');

    this.closeBtn.addEventListener('click', () => this.close());
    this.modal.addEventListener('click', (e) => {
      if (e.target === this.modal) this.close();
    });
  },

  // Open the form for a NEW comment with timecode info
  openNew({ tcStart, tcEnd, isGeneral }) {
    this.editingId = null;
    this.title.textContent = isGeneral ? 'New general comment' : 'New comment';
    this.render({
      tcStart, tcEnd, isGeneral,
      element: '', action: '', priority: '', description: ''
    });
    this.modal.hidden = false;
  },

  // Open the form to EDIT an existing comment
  openEdit(commentId) {
    const c = Comments.get(commentId);
    if (!c) return;
    this.editingId = commentId;
    this.title.textContent = 'Edit comment';
    this.render({
      tcStart: c.timecode_start,
      tcEnd: c.timecode_end,
      isGeneral: c.timecode_start == null,
      element: c.element,
      action: c.action,
      priority: c.priority,
      description: c.description
    });
    this.modal.hidden = false;
  },

  close() {
    this.modal.hidden = true;
    this.container.innerHTML = '';
    this.editingId = null;
  },

  render({ tcStart, tcEnd, isGeneral, element, action, priority, description }) {
    let contextHtml = '';
    if (isGeneral) {
      contextHtml = `
        <div class="form-context">
          <strong>General comment</strong>
          Not anchored to any specific time. Use this for feedback about the whole piece.
        </div>
      `;
    } else {
      const isRange = tcEnd != null && tcEnd > tcStart + 0.05;
      const tcLabel = isRange
        ? `${formatTime(tcStart)} → ${formatTime(tcEnd)}`
        : formatTime(tcStart);
      const excerpt = Transcript.getPhraseInRange(tcStart, isRange ? tcEnd : tcStart);
      contextHtml = `
        <div class="form-context">
          <strong>Anchored to:</strong>
          <span class="form-context-tc">${tcLabel}</span>
          ${excerpt ? `<div class="form-context-excerpt">"${escapeHtml(excerpt)}"</div>` : ''}
        </div>
      `;
    }

    this.container.innerHTML = `
      ${contextHtml}
      <form id="comment-form">
        <div class="form-field">
          <label for="f-element">Element <span class="required">*</span></label>
          <select id="f-element" required>
            <option value="">Select…</option>
            <option value="Music">Music</option>
            <option value="Dialogue">Dialogue</option>
            <option value="Sound">Sound (general)</option>
            <option value="Video">Video</option>
            <option value="Editing">Editing</option>
            <option value="Graphics">Graphics</option>
            <option value="Subtitles">Subtitles</option>
          </select>
        </div>
        <div class="form-field">
          <label for="f-action">Action <span class="required">*</span></label>
          <select id="f-action" required>
            <option value="">Select…</option>
            <option value="Substitute">Substitute</option>
            <option value="Improve">Improve</option>
            <option value="Modify">Modify</option>
          </select>
        </div>
        <div class="form-field">
          <label for="f-priority">Priority <span class="required">*</span></label>
          <select id="f-priority" required>
            <option value="">Select…</option>
            <option value="Must-fix">Must-fix</option>
            <option value="Nice-to-have">Nice-to-have</option>
            <option value="Suggestion">Suggestion</option>
          </select>
        </div>
        <div class="form-field">
          <label for="f-description">Description <span class="required">*</span></label>
          <textarea id="f-description" required placeholder="Describe what should change and why."></textarea>
        </div>
        <div class="form-actions">
          <button type="button" class="btn btn-secondary" id="f-cancel">Cancel</button>
          <button type="submit" class="btn btn-primary">Save comment</button>
        </div>
      </form>
    `;

    document.getElementById('f-element').value = element || '';
    document.getElementById('f-action').value = action || '';
    document.getElementById('f-priority').value = priority || '';
    document.getElementById('f-description').value = description || '';

    document.getElementById('f-cancel').addEventListener('click', () => this.close());
    document.getElementById('comment-form').addEventListener('submit', (e) => {
      e.preventDefault();
      this.handleSubmit({ tcStart, tcEnd, isGeneral });
    });
  },

  handleSubmit({ tcStart, tcEnd, isGeneral }) {
    const element = document.getElementById('f-element').value;
    const action = document.getElementById('f-action').value;
    const priority = document.getElementById('f-priority').value;
    const description = document.getElementById('f-description').value.trim();

    if (!element || !action || !priority || !description) return;

    const isRange = !isGeneral && tcEnd != null && tcEnd > tcStart + 0.05;
    const excerpt = isGeneral ? '' : Transcript.getPhraseInRange(tcStart, isRange ? tcEnd : tcStart);

    const comment = {
      timecode_start: isGeneral ? null : tcStart,
      timecode_end: isGeneral ? null : (isRange ? tcEnd : tcStart),
      transcript_excerpt: excerpt,
      element, action, priority, description
    };

    if (this.editingId) {
      Comments.update(this.editingId, comment);
    } else {
      Comments.add(comment);
    }
    this.close();
  }
};

function escapeHtml(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
