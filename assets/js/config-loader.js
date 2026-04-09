// config-loader.js
// Loads the global site config, project config, and transcript data.
// The global config.json lives at the root of Feedback web/ and holds
// values shared across all projects (GAS endpoint, brand info, etc.).
// Per-project configs live under /projects/{id}/.

async function loadGlobalConfig() {
  const res = await fetch('config.json');
  if (!res.ok) throw new Error('Global config.json not found at site root');
  return res.json();
}

async function loadProjectConfig(projectId) {
  const res = await fetch(`projects/${projectId}/config.json`);
  if (!res.ok) throw new Error(`Project "${projectId}" not found`);
  return res.json();
}

async function loadTranscript(projectId, transcriptFile) {
  const res = await fetch(`projects/${projectId}/${transcriptFile}`);
  if (!res.ok) throw new Error(`Transcript "${transcriptFile}" not found`);
  return res.json();
}

function findVersion(piece, versionNumber) {
  return piece.versions.find(v => v.version === Number(versionNumber));
}

function findPiece(config, pieceId) {
  return config.pieces.find(p => p.id === pieceId);
}
