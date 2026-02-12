# Quality Checklist (UTF-8 + Attachments)

## UTF-8 / Korean Rendering

- [ ] `templates/app/base_app.html` has `<meta charset="utf-8">`
- [ ] FIELD page text is readable (no `??` mojibake)
- [ ] HQ page text is readable (labels/buttons/status)
- [ ] CEO page text is readable (labels/buttons/status)
- [ ] New templates/components are saved in UTF-8

## Attachment Policy

- [ ] Detail pages use common attachment panel standard (inline preview + list)
- [ ] List pages show attachment badge only (`🖼 n` / `📎 n`)
- [ ] Draft/Rejected can edit attachments
- [ ] Submitted/Approved cannot edit attachments
- [ ] Closing-locked objects cannot edit attachments regardless of status
- [ ] Server rejects upload when `can_edit=False`

## Regression / Performance

- [ ] Draft upload -> submit keeps attached files
- [ ] No duplicate files on repeated draft save
- [ ] Attachment rendering does not add N+1 query issues

