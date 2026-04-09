// piece-init.js
// Bootstraps the piece review page: loads config + transcript, initializes the
// player, comments store, and form modal, and wires the buttons.

(async function () {
  const params = new URLSearchParams(window.location.search);
  const projectId = params.get('project');
  const pieceId = params.get('piece');
  const version = params.get('v');

  if (!projectId || !pieceId || version == null) {
    document.getElementById('piece-title').textContent = 'Invalid link';
    document.getElementById('piece-meta').textContent =
      'The URL is missing project, piece, or version.';
    return;
  }

  // ---- Load global + project config + transcript ---------------------------------
  let globalConfig, config, piece, versionData, transcriptData;
  try {
    globalConfig = await loadGlobalConfig();
    config = await loadProjectConfig(projectId);
    piece = findPiece(config, pieceId);
    if (!piece) throw new Error(`Piece "${pieceId}" not found in project "${projectId}"`);
    versionData = findVersion(piece, version);
    if (!versionData) throw new Error(`Version v${version} not found for piece "${pieceId}"`);
    transcriptData = await loadTranscript(projectId, versionData.transcript_file);
    Transcript.load(transcriptData);
  } catch (err) {
    document.getElementById('piece-title').textContent = 'Failed to load piece';
    document.getElementById('piece-meta').textContent = err.message;
    return;
  }

  // ---- Update header --------------------------------------------------------------
  document.title = `${piece.name} v${versionData.version} · ${config.name}`;
  document.getElementById('piece-name-header').textContent = `${config.name} · ${piece.name}`;
  document.getElementById('piece-title').textContent = `${piece.name} — v${versionData.version}`;
  document.getElementById('piece-meta').textContent =
    `Exported ${versionData.export_date}`;
  document.getElementById('back-link').href = `project.html?id=${config.id}`;

  // ---- Init comments store --------------------------------------------------------
  Comments.init(config.id, piece.id, versionData.version);

  // ---- Init form modal ------------------------------------------------------------
  FormUI.init();

  // ---- Init player ----------------------------------------------------------------
  if (!versionData.youtube_id || versionData.youtube_id === 'PENDING') {
    document.getElementById('player-wrapper').innerHTML =
      '<p style="color:#fff;padding:32px;text-align:center;">Video not yet uploaded to YouTube.</p>';
  } else {
    Player.init(versionData.youtube_id, 'player', () => {
      // Enable timecode buttons once player is ready
      document.getElementById('btn-add-point').disabled = false;
      document.getElementById('btn-mark-start').disabled = false;
      document.getElementById('btn-mark-end').disabled = false;
    });
  }

  // ---- Wire range tracking --------------------------------------------------------
  let rangeStart = null;
  const rangeStatus = document.getElementById('range-status');
  function updateRangeStatus() {
    if (rangeStart == null) {
      rangeStatus.hidden = true;
    } else {
      rangeStatus.hidden = false;
      rangeStatus.textContent =
        `Range start marked at ${formatTime(rangeStart)}. Click "Mark range end" to anchor a comment to this range.`;
    }
  }

  document.getElementById('btn-mark-start').addEventListener('click', () => {
    rangeStart = Player.getCurrentTime();
    updateRangeStatus();
  });

  document.getElementById('btn-mark-end').addEventListener('click', () => {
    if (rangeStart == null) {
      alert('First click "Mark range start" at the beginning of the range.');
      return;
    }
    const rangeEnd = Player.getCurrentTime();
    if (rangeEnd <= rangeStart) {
      alert('Range end must be after the range start.');
      return;
    }
    Player.pause();
    FormUI.openNew({ tcStart: rangeStart, tcEnd: rangeEnd, isGeneral: false });
    rangeStart = null;
    updateRangeStatus();
  });

  document.getElementById('btn-add-point').addEventListener('click', () => {
    Player.pause();
    const t = Player.getCurrentTime();
    FormUI.openNew({ tcStart: t, tcEnd: t, isGeneral: false });
  });

  document.getElementById('btn-add-general').addEventListener('click', () => {
    FormUI.openNew({ isGeneral: true });
  });

  // ---- Render comments list -------------------------------------------------------
  const listEl = document.getElementById('comments-list');
  const counterEl = document.getElementById('comments-count');
  const submitBtn = document.getElementById('btn-submit');
  const reviewerInput = document.getElementById('reviewer-name');

  function priorityClass(priority) {
    return 'tag-priority-' + priority.toLowerCase().replace(/[^a-z]+/g, '-');
  }

  function renderList(comments) {
    counterEl.textContent = comments.length;
    if (comments.length === 0) {
      listEl.innerHTML = '<p class="empty-comments">No comments yet. Pause the video and click "Add comment at current time" to start.</p>';
    } else {
      listEl.innerHTML = comments.map(c => {
        const isRange = c.timecode_end != null && c.timecode_end > c.timecode_start + 0.05;
        const tcLabel = c.timecode_start == null
          ? 'GENERAL'
          : (isRange ? `${formatTime(c.timecode_start)}–${formatTime(c.timecode_end)}` : formatTime(c.timecode_start));
        return `
          <div class="comment-item" data-id="${c.comment_id}">
            <div class="comment-meta">
              <span class="tag tag-tc">${tcLabel}</span>
              <span class="tag tag-element">${c.element}</span>
              <span class="tag tag-action">${c.action}</span>
              <span class="tag ${priorityClass(c.priority)}">${c.priority}</span>
            </div>
            ${c.transcript_excerpt ? `<div class="comment-excerpt">"${escapeHtml(c.transcript_excerpt)}"</div>` : ''}
            <div class="comment-description">${escapeHtml(c.description)}</div>
            <div class="comment-actions">
              ${c.timecode_start != null ? `<button data-action="seek">Jump to time</button>` : ''}
              <button data-action="edit">Edit</button>
              <button data-action="delete" class="delete">Delete</button>
            </div>
          </div>
        `;
      }).join('');

      // Wire per-item buttons
      listEl.querySelectorAll('.comment-item').forEach(item => {
        const id = item.dataset.id;
        item.querySelectorAll('button[data-action]').forEach(btn => {
          btn.addEventListener('click', () => {
            const action = btn.dataset.action;
            if (action === 'seek') {
              const c = Comments.get(id);
              if (c && c.timecode_start != null) Player.seekTo(c.timecode_start);
            } else if (action === 'edit') {
              FormUI.openEdit(id);
            } else if (action === 'delete') {
              if (confirm('Delete this comment?')) Comments.delete(id);
            }
          });
        });
      });
    }
    updateSubmitState();
  }

  function updateSubmitState() {
    const hasName = reviewerInput.value.trim().length > 0;
    const hasComments = Comments.count() > 0;
    submitBtn.disabled = !(hasName && hasComments);
  }

  Comments.onChange(renderList);
  reviewerInput.addEventListener('input', updateSubmitState);
  renderList(Comments.getAll());

  // Restore reviewer name from localStorage if present
  const reviewerKey = 'souts-reviewer-name';
  reviewerInput.value = localStorage.getItem(reviewerKey) || '';
  reviewerInput.addEventListener('change', () => {
    localStorage.setItem(reviewerKey, reviewerInput.value.trim());
  });
  updateSubmitState();

  // ---- Submit ---------------------------------------------------------------------
  const submitStatus = document.getElementById('submit-status');
  submitBtn.addEventListener('click', async () => {
    const reviewerName = reviewerInput.value.trim();
    if (!reviewerName) {
      alert('Please enter your name.');
      return;
    }
    const endpoint = globalConfig.google_apps_script_endpoint;
    if (!endpoint || endpoint.includes('PENDING')) {
      alert('The submission endpoint is not configured yet. Please contact SideOutSticks.');
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending…';
    submitStatus.hidden = true;

    try {
      await Submit.send({
        endpoint: endpoint,
        project_id: config.id,
        piece_id: piece.id,
        version: versionData.version,
        reviewer_name: reviewerName,
        comments: Comments.getAll()
      });
      submitStatus.hidden = false;
      submitStatus.className = 'submit-status success';
      submitStatus.textContent = `Thanks! ${Comments.count()} comment${Comments.count() === 1 ? '' : 's'} sent.`;
      Comments.clear();
      submitBtn.textContent = 'Submit feedback';
    } catch (err) {
      console.error(err);
      submitStatus.hidden = false;
      submitStatus.className = 'submit-status error';
      submitStatus.textContent = `Could not send: ${err.message}. Your comments are still saved locally.`;
      submitBtn.disabled = false;
      submitBtn.textContent = 'Retry submit';
    }
  });
})();
