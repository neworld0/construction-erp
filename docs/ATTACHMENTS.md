# Attachments Standard (ATT-1)

## Discovery Summary

- **Storage model**: `apps.evidence.models.Evidence` + `apps.evidence.models.EvidenceFile`.
- **File field**: `EvidenceFile.file` (`upload_to="evidence/"`).
- **Link style**: object-level connection through `Evidence.object_type` + `Evidence.object_id`.
- **Open endpoint**: `/app/evidence-files/<file_id>/open/` (`apps.core.views.evidence_file_open`).
- **Upload endpoints**:
  - API: `apps.evidence.views.EvidenceFileUploadView`
  - Web edit: `apps.evidence.web_views.evidence_edit`
- **Current detail rendering examples**:
  - `templates/app/hq/daily_progress_detail.html`
  - `templates/app/hq/field_report_detail.html`
- **Current field draft/submit flow (evidence)**:
  - `apps.field.web_views.py` (progress/cost/report handlers with `request.FILES.getlist(...)`)

## ATT-1 Common Policy

### Editability

- Editable statuses: `DRAFT`, `REJECTED`
- Read-only statuses: `SUBMITTED`, `APPROVED`
- Closing lock (month closed or project closed) has highest priority: always read-only

Server helper:
- `apps.evidence.attachment_policy.can_edit_attachments`
- `apps.evidence.attachment_policy.evaluate_attachment_editability`

### UI Standard

- **Detail**: image inline preview + file list + open link.
- **List**: icon + count only (`🖼 n` or `📎 n`), no thumbnail grid.
- **Link behavior**: open in new tab for user-safe read access.

### Draft -> Submit behavior

- Draft files must remain after submit.
- No duplicate attachment creation during draft edits.
- Submitted/approved/closing-locked objects: upload/delete hidden and server-rejected.

## ATT-1 Components

- `templates/components/attachments_panel.html`
  - Inputs: `attachments`, `can_edit`, `upload_url`, `delete_url`, `object_label`, `help_text`
- `templates/components/attachment_badge.html`
  - Input: `attachments`

## Common Done Criteria (for ATT-2 ~ ATT-5)

- Attachment standard unified:
  - detail = inline preview + list
  - list = icon + count
  - links consistent
- Draft/Rejected: editable, Submitted/Approved: read-only, Closing lock: always read-only
- Mobile and desktop both support multiple uploads in editable states
- No Korean text corruption in FIELD/HQ/CEO
- No N+1 regression on attachment listing pages

