// SideOutSticks Reviews — Google Apps Script endpoint
// ====================================================
// Receives POST submissions from the feedback web and appends each comment
// to the shared "feedback" sheet as a new row.
//
// IMPORTANT: This endpoint is shared across ALL projects. Rows are disambiguated
// by the `project_id` column, so a single Sheet + single deployment serves every
// project. Do NOT create a new Sheet per project.
//
// HOW TO DEPLOY (one-time, ~5 minutes):
// 1. Go to https://sheets.google.com and create a new Sheet.
//    Name it "SideOutSticks Reviews" (generic, shared across projects).
// 2. Rename the first tab to "feedback".
// 3. Add this header row in row 1 (copy and paste these 13 columns):
//      timestamp | project_id | piece_id | version | reviewer_name | comment_id |
//      timecode_start | timecode_end | transcript_excerpt | element | action |
//      priority | description
//    (One column per pipe-separated value above.)
// 4. From the Sheet menu: Extensions → Apps Script. A new tab opens.
// 5. Delete any sample code in Code.gs and paste THIS ENTIRE FILE.
// 6. Click the floppy-disk Save icon. Give the project a name (e.g. "SideOutSticks Reviews API").
// 7. Click "Deploy" (top-right) → "New deployment".
// 8. In the "Select type" gear icon, choose "Web app".
// 9. Configure:
//      Description: "SideOutSticks Reviews v1"
//      Execute as: Me (your account)
//      Who has access: "Anyone" (this is required so the public web can POST)
// 10. Click Deploy. Authorize when prompted (Google will warn it's an unverified app —
//     click "Advanced" → "Go to ... (unsafe)" → "Allow". This is normal for personal scripts.)
// 11. Copy the "Web app URL" that appears. It looks like:
//       https://script.google.com/macros/s/AKfycb.../exec
// 12. Paste that URL into the root config.json (at Feedback web/config.json)
//     under "google_apps_script_endpoint". This single endpoint will be used
//     by every project in the repo.
//
// To update later: edit this code, click Deploy → Manage deployments → pencil icon →
// "New version" → Deploy. The URL stays the same.

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('feedback')
                || SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();

    const rows = (data.comments || []).map(c => [
      new Date(),
      data.project_id || '',
      data.piece_id || '',
      data.version || '',
      data.reviewer_name || '',
      c.comment_id || '',
      c.timecode_start != null ? c.timecode_start : '',
      c.timecode_end != null ? c.timecode_end : '',
      c.transcript_excerpt || '',
      c.element || '',
      c.action || '',
      c.priority || '',
      c.description || ''
    ]);

    if (rows.length > 0) {
      sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
    }

    return ContentService
      .createTextOutput(JSON.stringify({ status: 'success', count: rows.length }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ status: 'error', message: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// Optional: respond to GET so you can check from a browser that the endpoint is live.
function doGet() {
  return ContentService
    .createTextOutput(JSON.stringify({ status: 'ok', message: 'SideOutSticks Reviews endpoint is live.' }))
    .setMimeType(ContentService.MimeType.JSON);
}
