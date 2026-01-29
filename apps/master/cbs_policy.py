from dataclasses import dataclass

from apps.master.models import CBSChangeRequest, CBSChangeRequestStatus

from . import web_views


@dataclass(frozen=True)
class CbsPolicyResult:
    selectable: bool
    severity: str
    reason_code: str
    message: str
    active: bool
    locked: bool
    pending: bool


def has_pending_cbs_change(cost_item) -> bool:
    return CBSChangeRequest.objects.filter(
        cost_item=cost_item, status=CBSChangeRequestStatus.SUBMITTED
    ).exists()


def evaluate_cbs_selectability(
    cost_item, actor_role, context, *, is_existing_usage=False
):
    # Discovery:
    # - CostItem: apps.cost.models.CostItem (fields: is_active, code, name)
    # - CBSChangeRequest: apps.master.models.CBSChangeRequest (status SUBMITTED means pending)
    # - Locked: computed via apps.master.web_views._is_costitem_locked
    if context != "BUDGET":
        return CbsPolicyResult(True, "OK", "NONE", "", True, False, False)

    active = getattr(cost_item, "is_active", None)
    if active is None:
        active = getattr(cost_item, "active", None)
    if active is None:
        active = getattr(cost_item, "enabled", True)

    locked, _, _ = web_views._is_costitem_locked(cost_item, cost_item.__class__)
    pending = has_pending_cbs_change(cost_item)

    if is_existing_usage:
        if not active:
            return CbsPolicyResult(
                True,
                "WARN",
                "INACTIVE_LEGACY",
                "비활성 CBS(레거시)입니다. 신규 선택은 불가합니다.",
                active,
                locked,
                pending,
            )
        if pending:
            return CbsPolicyResult(
                True,
                "WARN",
                "PENDING_CHANGE_LEGACY",
                "CBS 변경 승인 대기 중입니다. 신규 선택은 불가합니다.",
                active,
                locked,
                pending,
            )
        if locked:
            return CbsPolicyResult(
                True,
                "WARN",
                "LOCKED",
                "잠김 CBS입니다. 변경은 제한됩니다.",
                active,
                locked,
                pending,
            )
        return CbsPolicyResult(True, "OK", "NONE", "", active, locked, pending)

    if not active:
        return CbsPolicyResult(
            False,
            "BLOCK",
            "INACTIVE",
            "비활성 CBS는 신규 예산 항목으로 선택할 수 없습니다.",
            active,
            locked,
            pending,
        )
    if pending:
        return CbsPolicyResult(
            False,
            "BLOCK",
            "PENDING_CHANGE",
            "CBS 변경 승인 대기 중인 항목은 선택할 수 없습니다.",
            active,
            locked,
            pending,
        )
    if locked:
        return CbsPolicyResult(
            True,
            "WARN",
            "LOCKED",
            "잠김 CBS입니다. 변경은 제한됩니다.",
            active,
            locked,
            pending,
        )

    return CbsPolicyResult(True, "OK", "NONE", "", active, locked, pending)


def build_cbs_badges(policy_result):
    badges = []
    if not policy_result.active:
        badges.append("비활성")
    if policy_result.locked:
        badges.append("잠김")
    if policy_result.pending:
        badges.append("변경승인대기")
    return badges
