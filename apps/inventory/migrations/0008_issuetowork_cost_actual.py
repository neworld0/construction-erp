from django.db import migrations, models
import django.db.models.deletion


def link_existing_issue_cost_actuals(apps, schema_editor):
    IssueToWork = apps.get_model("inventory", "IssueToWork")
    CostActualLine = apps.get_model("cost", "CostActualLine")
    ApprovalRequest = apps.get_model("core", "ApprovalRequest")

    for issue in IssueToWork.objects.filter(cost_actual__isnull=True).iterator():
        line = CostActualLine.objects.filter(
            description__contains=f"(IW {issue.issue_no})"
        ).order_by("id").first()
        if line is None:
            continue
        issue.cost_actual_id = line.cost_actual_id
        approval = ApprovalRequest.objects.filter(
            object_type="COST_ACTUAL", object_id=line.cost_actual_id
        ).order_by("-id").first()
        if approval is not None:
            if approval.status == "APPROVED":
                issue.status = "APPROVED"
                issue.approved_by_id = approval.approved_by_id
                issue.approved_at = approval.approved_at
            elif approval.status == "REJECTED":
                issue.status = "REJECTED"
            elif approval.status == "SUBMITTED":
                issue.status = "SUBMITTED"
        issue.save()


class Migration(migrations.Migration):
    dependencies = [
        ("cost", "0007_revenuerecognitionclose"),
        ("inventory", "0007_projectmaterialrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="issuetowork",
            name="cost_actual",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="inventory_issue_to_work",
                to="cost.costactual",
            ),
        ),
        migrations.RunPython(link_existing_issue_cost_actuals, migrations.RunPython.noop),
    ]
