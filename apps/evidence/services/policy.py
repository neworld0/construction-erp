from typing import Tuple

from apps.evidence.models import Evidence, EvidencePolicy


def check_evidence_required(object_type, object_id, when_status) -> Tuple[bool, str]:
    policy = (
        EvidencePolicy.objects.filter(object_type=object_type, when_status=when_status)
        .order_by("-id")
        .first()
    )
    if not policy or not policy.is_required:
        return True, ""

    evidence = Evidence.objects.filter(object_type=object_type, object_id=object_id).first()
    if evidence is None:
        return False, "Evidence is required."

    files = list(evidence.files.all())
    if len(files) < policy.min_files:
        return False, "Not enough evidence files."

    if policy.allowed_types:
        for file_obj in files:
            if file_obj.content_type not in policy.allowed_types:
                return False, "Evidence file type not allowed."

    return True, ""
