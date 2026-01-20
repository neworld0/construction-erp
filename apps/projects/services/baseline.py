from apps.projects.models import ProjectStatus


def is_baseline_locked(project) -> bool:
    if project is None:
        return True
    return project.status in (ProjectStatus.SUBMITTED, ProjectStatus.APPROVED)
