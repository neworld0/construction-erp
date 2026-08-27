from django.db import migrations


def sync_issue_statuses_from_cost_approvals(apps, schema_editor):
    IssueToWork = apps.get_model("inventory", "IssueToWork")
    ApprovalRequest = apps.get_model("core", "ApprovalRequest")

    for issue in IssueToWork.objects.exclude(cost_actual__isnull=True).iterator():
        approval = ApprovalRequest.objects.filter(
            object_type="COST_ACTUAL", object_id=issue.cost_actual_id
        ).order_by("-id").first()
        if approval is None:
            continue
        status = (approval.status or "").upper()
        if status == "APPROVED":
            issue.status = "APPROVED"
            issue.approved_by_id = approval.approved_by_id
            issue.approved_at = approval.approved_at
        elif status == "REJECTED":
            issue.status = "REJECTED"
        elif status == "SUBMITTED":
            issue.status = "SUBMITTED"
        issue.save()


class Migration(migrations.Migration):
    dependencies = [("inventory", "0008_issuetowork_cost_actual")]

    operations = [
        migrations.RunPython(sync_issue_statuses_from_cost_approvals, migrations.RunPython.noop),
    ]
