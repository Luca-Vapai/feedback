// submit.js
// Posts the collected comments as a single JSON payload to the GAS endpoint.

const Submit = {
  async send({ endpoint, project_id, piece_id, version, reviewer_name, comments }) {
    const payload = {
      project_id,
      piece_id,
      version,
      reviewer_name,
      submitted_at: new Date().toISOString(),
      comments
    };

    // GAS web apps require a CORS-friendly POST. We use text/plain to avoid the
    // preflight, which GAS doesn't handle. The script reads e.postData.contents.
    const res = await fetch(endpoint, {
      method: 'POST',
      mode: 'cors',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      throw new Error(`Server responded with ${res.status}`);
    }
    return res.json().catch(() => ({ status: 'success' }));
  }
};
