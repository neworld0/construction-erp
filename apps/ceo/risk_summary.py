from __future__ import annotations


def build_risk_summary(
    *,
    open_count: int,
    critical_count: int,
    high_count: int = 0,
    stale_48h_count: int = 0,
    pending_approvals_count: int = 0,
    closing_block_count: int = 0,
    top_reason: str = "",
    sample_project: str = "",
) -> dict:
    """
    Display-only risk summary generator for CEO dashboard.
    DB schema/business workflow is intentionally untouched.
    """
    safe_reason = (top_reason or "").strip() or "데이터 점검 필요"
    safe_project = (sample_project or "").strip()

    if critical_count > 0:
        summary_text = f"🔴 CRITICAL {critical_count}건 — 즉시 확인이 필요합니다."
        if stale_48h_count > 0:
            sub_text = f"장기 미해결 {stale_48h_count}건이 포함되어 있습니다."
        elif safe_project:
            sub_text = f"주요 원인: {safe_reason}. ({safe_project} 등)"
        else:
            sub_text = f"주요 원인: {safe_reason}."
        return {
            "severity": "CRITICAL",
            "summary_text": summary_text,
            "sub_text": sub_text,
        }

    if open_count > 0 or stale_48h_count > 0:
        summary_text = f"🟠 OPEN 리스크 {open_count}건이 있습니다."
        if stale_48h_count > 0:
            sub_text = f"48시간 이상 미해결 {stale_48h_count}건을 우선 확인하세요."
        elif safe_project:
            sub_text = f"{safe_reason} 이슈가 가장 많습니다. ({safe_project} 등)"
        else:
            sub_text = "리스크 상세에서 원인을 확인하세요."
        return {
            "severity": "WARNING",
            "summary_text": summary_text,
            "sub_text": sub_text,
        }

    summary_text = "🟢 현재 주요 리스크가 없습니다."
    if pending_approvals_count > 0:
        sub_text = f"승인 대기 {pending_approvals_count}건 처리 시 KPI가 더 선명해집니다."
    elif closing_block_count > 0:
        sub_text = f"마감 점검 필요 항목 {closing_block_count}건이 있습니다."
    else:
        sub_text = "제출·승인·마감 흐름이 정상입니다."
    return {
        "severity": "OK",
        "summary_text": summary_text,
        "sub_text": sub_text,
    }

