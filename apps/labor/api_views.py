from datetime import datetime

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_project_access, require_role
from apps.projects.models import Project

from .models import (
    LaborRateScope,
    LaborRateTable,
    LaborRateType,
    LaborRole,
    PayrollAllocationBatch,
    PayrollAllocationLine,
    PayrollAllocationStatus,
    Timesheet,
)
from .services import (
    create_labor_role,
    create_rate,
    get_applicable_rate,
    update_labor_role,
    update_rate,
    approve_timesheet,
    create_timesheet,
    reject_timesheet,
    submit_timesheet,
    upsert_timesheet_lines,
    create_payroll_batch,
    submit_payroll_batch,
    update_payroll_batch,
    upsert_payroll_lines,
    validate_payroll_batch,
)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def _clamp_limit(value, default=30, low=1, high=100):
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(low, min(high, parsed))


class LaborRoleListView(APIView):
    def get(self, request):
        role = get_user_role(request.user)
        q = (request.GET.get("q") or "").strip()
        active_param = request.GET.get("active")
        include_inactive = request.GET.get("include_inactive") == "1"
        limit = _clamp_limit(request.GET.get("limit"), default=30)
        qs = LaborRole.objects.all().order_by("sort_order", "code")
        if q:
            qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
        if role == Role.FIELD:
            qs = qs.filter(is_active=True)
        else:
            if active_param in ("0", "1"):
                qs = qs.filter(is_active=active_param == "1")
            elif not include_inactive:
                qs = qs.filter(is_active=True)
        data = [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "role_group": item.role_group,
                "is_active": item.is_active,
                "default_cbs_id": item.default_cbs_id,
            }
            for item in qs[:limit]
        ]
        return Response(data)

    def post(self, request):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        payload = request.data or {}
        try:
            role = create_labor_role(payload, actor=request.user)
        except ValidationError as exc:
            return Response({"detail": exc.message_dict if hasattr(exc, "message_dict") else str(exc)}, status=400)
        return Response(
            {
                "id": role.id,
                "code": role.code,
                "name": role.name,
                "role_group": role.role_group,
                "is_active": role.is_active,
            },
            status=201,
        )


class LaborRoleDetailView(APIView):
    def patch(self, request, role_id):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        role = get_object_or_404(LaborRole, id=role_id)
        payload = request.data or {}
        try:
            role = update_labor_role(role, payload, actor=request.user)
        except ValidationError as exc:
            return Response({"detail": exc.message_dict if hasattr(exc, "message_dict") else str(exc)}, status=400)
        return Response(
            {
                "id": role.id,
                "code": role.code,
                "name": role.name,
                "role_group": role.role_group,
                "is_active": role.is_active,
            }
        )


class LaborRateListView(APIView):
    def get(self, request):
        role = get_user_role(request.user)
        labor_role_id = request.GET.get("role")
        project_id = request.GET.get("project")
        date_param = _parse_date(request.GET.get("date"))
        active_param = request.GET.get("active")
        include_inactive = request.GET.get("include_inactive") == "1"
        limit = _clamp_limit(request.GET.get("limit"), default=50)

        qs = LaborRateTable.objects.select_related("labor_role", "project").order_by(
            "-effective_from", "labor_role_id"
        )
        if labor_role_id:
            qs = qs.filter(labor_role_id=labor_role_id)
        if project_id:
            qs = qs.filter(project_id=project_id)
        if date_param:
            qs = qs.filter(effective_from__lte=date_param).filter(
                Q(effective_to__isnull=True) | Q(effective_to__gte=date_param)
            )
        if role == Role.FIELD:
            qs = qs.filter(is_active=True)
        else:
            if active_param in ("0", "1"):
                qs = qs.filter(is_active=active_param == "1")
            elif not include_inactive:
                qs = qs.filter(is_active=True)
        data = [
            {
                "id": rate.id,
                "labor_role_id": rate.labor_role_id,
                "labor_role_code": rate.labor_role.code,
                "labor_role_name": rate.labor_role.name,
                "rate_type": rate.rate_type,
                "unit_rate": rate.unit_rate,
                "currency": rate.currency,
                "effective_from": rate.effective_from,
                "effective_to": rate.effective_to,
                "scope_type": rate.scope_type,
                "project_id": rate.project_id,
                "is_active": rate.is_active,
                "note": rate.note,
            }
            for rate in qs[:limit]
        ]
        return Response(data)

    def post(self, request):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        payload = request.data or {}
        try:
            rate = create_rate(payload, actor=request.user)
        except ValidationError as exc:
            return Response({"detail": exc.message_dict if hasattr(exc, "message_dict") else str(exc)}, status=400)
        return Response(
            {
                "id": rate.id,
                "labor_role_id": rate.labor_role_id,
                "rate_type": rate.rate_type,
                "unit_rate": rate.unit_rate,
                "scope_type": rate.scope_type,
                "project_id": rate.project_id,
                "effective_from": rate.effective_from,
                "effective_to": rate.effective_to,
                "is_active": rate.is_active,
            },
            status=201,
        )


class LaborRateDetailView(APIView):
    def patch(self, request, rate_id):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        rate = get_object_or_404(LaborRateTable, id=rate_id)
        payload = request.data or {}
        try:
            rate = update_rate(rate, payload, actor=request.user)
        except ValidationError as exc:
            return Response({"detail": exc.message_dict if hasattr(exc, "message_dict") else str(exc)}, status=400)
        return Response(
            {
                "id": rate.id,
                "labor_role_id": rate.labor_role_id,
                "rate_type": rate.rate_type,
                "unit_rate": rate.unit_rate,
                "scope_type": rate.scope_type,
                "project_id": rate.project_id,
                "effective_from": rate.effective_from,
                "effective_to": rate.effective_to,
                "is_active": rate.is_active,
            }
        )


class LaborRateApplicableView(APIView):
    def get(self, request):
        role_id = request.GET.get("role_id")
        project_id = request.GET.get("project_id")
        rate_type = request.GET.get("rate_type") or LaborRateType.DAY
        date_param = _parse_date(request.GET.get("date"))
        if not role_id or not date_param:
            return Response({"detail": "role_id and date are required."}, status=400)
        rate = get_applicable_rate(project_id, role_id, date_param, rate_type=rate_type)
        if not rate:
            return Response(
                {"unit_rate": None, "rate_type": rate_type, "scope": None, "rate_id": None}
            )
        return Response(
            {
                "unit_rate": rate.unit_rate,
                "rate_type": rate.rate_type,
                "scope": rate.scope_type,
                "rate_id": rate.id,
            }
        )


class TimesheetListView(APIView):
    def get(self, request):
        role = get_user_role(request.user)
        project_id = request.GET.get("project")
        status_param = request.GET.get("status")
        start_date = _parse_date(request.GET.get("start"))
        end_date = _parse_date(request.GET.get("end"))
        qs = Timesheet.objects.select_related("project").order_by("-work_date", "-id")
        if project_id:
            qs = qs.filter(project_id=project_id)
        if status_param:
            qs = qs.filter(status=status_param)
        if start_date:
            qs = qs.filter(work_date__gte=start_date)
        if end_date:
            qs = qs.filter(work_date__lte=end_date)
        if role == Role.FIELD:
            qs = qs.filter(created_by=request.user)
        data = []
        totals = (
            qs.annotate(total_amount=Sum("lines__amount"))
            .values("id", "total_amount")
        )
        total_map = {item["id"]: item["total_amount"] or 0 for item in totals}
        for item in qs[:200]:
            data.append(
                {
                    "id": item.id,
                    "sheet_no": item.sheet_no,
                    "project_id": item.project_id,
                    "project_name": item.project.name if item.project_id else "",
                    "work_date": item.work_date,
                    "status": item.status,
                    "total_amount": total_map.get(item.id, 0),
                }
            )
        return Response(data)

    def post(self, request):
        require_role(request.user, [Role.FIELD, Role.HQ, Role.CEO], request=request)
        payload = request.data or {}
        project_id = payload.get("project_id")
        work_date = _parse_date(payload.get("work_date"))
        if not project_id or not work_date:
            return Response({"detail": "project_id and work_date are required."}, status=400)
        project = get_object_or_404(Project, id=project_id)
        require_project_access(request.user, project.id)
        try:
            timesheet = create_timesheet(
                project=project,
                work_date=work_date,
                actor=request.user,
                note=str(payload.get("note") or "").strip(),
            )
            lines_payload = payload.get("lines") or []
            if lines_payload:
                upsert_timesheet_lines(
                    timesheet=timesheet, lines_payload=lines_payload, actor=request.user
                )
        except (ValidationError, PermissionDenied) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"detail": detail}, status=400)
        return Response(
            {
                "id": timesheet.id,
                "sheet_no": timesheet.sheet_no,
                "project_id": timesheet.project_id,
                "work_date": timesheet.work_date,
                "status": timesheet.status,
            },
            status=201,
        )


class TimesheetDetailView(APIView):
    def get(self, request, timesheet_id):
        timesheet = get_object_or_404(
            Timesheet.objects.select_related("project").prefetch_related("lines", "lines__labor_role"),
            id=timesheet_id,
        )
        role = get_user_role(request.user)
        if role == Role.FIELD and timesheet.created_by_id != request.user.id:
            raise PermissionDenied("Project access denied.")
        lines = [
            {
                "id": line.id,
                "labor_role_id": line.labor_role_id,
                "labor_role_code": line.labor_role.code,
                "labor_role_name": line.labor_role.name,
                "headcount": line.headcount,
                "hours": line.hours,
                "rate_type": line.rate_type,
                "unit_rate": line.unit_rate,
                "amount": line.amount,
                "memo": line.memo,
            }
            for line in timesheet.lines.all()
        ]
        total_amount = sum([line["amount"] or 0 for line in lines])
        return Response(
            {
                "id": timesheet.id,
                "sheet_no": timesheet.sheet_no,
                "project_id": timesheet.project_id,
                "project_name": timesheet.project.name if timesheet.project_id else "",
                "work_date": timesheet.work_date,
                "status": timesheet.status,
                "note": timesheet.note,
                "lines": lines,
                "total_amount": total_amount,
            }
        )

    def patch(self, request, timesheet_id):
        require_role(request.user, [Role.FIELD, Role.HQ, Role.CEO], request=request)
        timesheet = get_object_or_404(Timesheet, id=timesheet_id)
        if timesheet.created_by_id != request.user.id and get_user_role(request.user) == Role.FIELD:
            raise PermissionDenied("Project access denied.")
        if timesheet.status not in ("DRAFT", "REJECTED"):
            return Response({"detail": "Cannot update submitted timesheet."}, status=400)
        note = str((request.data or {}).get("note") or "").strip()
        timesheet.note = note
        timesheet.save(update_fields=["note", "updated_at"])
        return Response({"id": timesheet.id, "note": timesheet.note})


class TimesheetLinesView(APIView):
    def patch(self, request, timesheet_id):
        require_role(request.user, [Role.FIELD, Role.HQ, Role.CEO], request=request)
        timesheet = get_object_or_404(Timesheet, id=timesheet_id)
        if timesheet.created_by_id != request.user.id and get_user_role(request.user) == Role.FIELD:
            raise PermissionDenied("Project access denied.")
        lines_payload = (request.data or {}).get("lines") or []
        try:
            upsert_timesheet_lines(
                timesheet=timesheet, lines_payload=lines_payload, actor=request.user
            )
        except (ValidationError, PermissionDenied) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"detail": detail}, status=400)
        return Response({"id": timesheet.id, "line_count": len(lines_payload)})


class TimesheetSubmitView(APIView):
    def post(self, request, timesheet_id):
        require_role(request.user, [Role.FIELD, Role.HQ, Role.CEO], request=request)
        timesheet = get_object_or_404(Timesheet, id=timesheet_id)
        if timesheet.created_by_id != request.user.id and get_user_role(request.user) == Role.FIELD:
            raise PermissionDenied("Project access denied.")
        try:
            timesheet, total_amount = submit_timesheet(
                timesheet=timesheet, actor=request.user
            )
        except (ValidationError, PermissionDenied) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"detail": detail}, status=400)
        return Response(
            {
                "id": timesheet.id,
                "sheet_no": timesheet.sheet_no,
                "status": timesheet.status,
                "total_amount": total_amount,
            }
        )


class TimesheetApproveView(APIView):
    def post(self, request, timesheet_id):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        timesheet = get_object_or_404(Timesheet, id=timesheet_id)
        try:
            timesheet = approve_timesheet(timesheet=timesheet, actor=request.user)
        except (ValidationError, PermissionDenied) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"detail": detail}, status=400)
        return Response({"id": timesheet.id, "status": timesheet.status})


class TimesheetRejectView(APIView):
    def post(self, request, timesheet_id):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        timesheet = get_object_or_404(Timesheet, id=timesheet_id)
        reason = str((request.data or {}).get("reason") or "").strip()
        try:
            timesheet = reject_timesheet(
                timesheet=timesheet, actor=request.user, reason=reason
            )
        except (ValidationError, PermissionDenied) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"detail": detail}, status=400)
        return Response({"id": timesheet.id, "status": timesheet.status})


class PayrollBatchListView(APIView):
    def get(self, request):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        year = request.GET.get("year")
        month = request.GET.get("month")
        status = request.GET.get("status")
        qs = PayrollAllocationBatch.objects.order_by("-period_year", "-period_month", "-id")
        if year:
            qs = qs.filter(period_year=year)
        if month:
            qs = qs.filter(period_month=month)
        if status:
            qs = qs.filter(status=status)
        data = []
        totals = (
            PayrollAllocationLine.objects.filter(batch__in=qs)
            .values("batch_id")
            .annotate(total=Sum("amount"))
        )
        totals_map = {item["batch_id"]: item["total"] or 0 for item in totals}
        for batch in qs[:200]:
            total_lines = totals_map.get(batch.id, 0)
            data.append(
                {
                    "id": batch.id,
                    "batch_no": batch.batch_no,
                    "period_year": batch.period_year,
                    "period_month": batch.period_month,
                    "status": batch.status,
                    "total_amount": batch.total_amount,
                    "sum_lines": total_lines,
                    "diff": batch.total_amount - total_lines,
                    "created_by": batch.created_by_id,
                }
            )
        return Response(data)

    def post(self, request):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        payload = request.data or {}
        try:
            batch = create_payroll_batch(
                year=int(payload.get("period_year")),
                month=int(payload.get("period_month")),
                total_amount=payload.get("total_amount"),
                actor=request.user,
                note=str(payload.get("note") or ""),
            )
        except (ValidationError, PermissionDenied) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"detail": detail}, status=400)
        return Response(
            {
                "id": batch.id,
                "batch_no": batch.batch_no,
                "period_year": batch.period_year,
                "period_month": batch.period_month,
                "status": batch.status,
                "total_amount": batch.total_amount,
            },
            status=201,
        )


class PayrollBatchDetailView(APIView):
    def patch(self, request, batch_id):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        batch = get_object_or_404(PayrollAllocationBatch, id=batch_id)
        payload = request.data or {}
        try:
            batch = update_payroll_batch(batch, payload, actor=request.user)
        except (ValidationError, PermissionDenied) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"detail": detail}, status=400)
        return Response(
            {
                "id": batch.id,
                "batch_no": batch.batch_no,
                "period_year": batch.period_year,
                "period_month": batch.period_month,
                "status": batch.status,
                "total_amount": batch.total_amount,
                "note": batch.note,
            }
        )


class PayrollBatchLinesView(APIView):
    def put(self, request, batch_id):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        batch = get_object_or_404(PayrollAllocationBatch, id=batch_id)
        lines_payload = (request.data or {}).get("lines") or []
        try:
            upsert_payroll_lines(batch, lines_payload, actor=request.user)
            ok, diff, sum_lines = validate_payroll_batch(batch)
        except (ValidationError, PermissionDenied) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"detail": detail}, status=400)
        return Response(
            {
                "id": batch.id,
                "batch_no": batch.batch_no,
                "sum_lines": sum_lines,
                "diff": diff,
                "status": batch.status,
            }
        )


class PayrollBatchSubmitView(APIView):
    def post(self, request, batch_id):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        batch = get_object_or_404(PayrollAllocationBatch, id=batch_id)
        try:
            batch, sum_lines, diff = submit_payroll_batch(batch, actor=request.user)
        except (ValidationError, PermissionDenied) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else str(exc)
            return Response({"detail": detail}, status=400)
        return Response(
            {
                "id": batch.id,
                "batch_no": batch.batch_no,
                "status": batch.status,
                "sum_lines": sum_lines,
                "diff": diff,
            }
        )
