import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.projects.models import Project


class Command(BaseCommand):
    help = "Seed initial RBAC roles, users, and a sample project."

    def handle(self, *args, **options):
        if os.getenv("SEED_ENABLE", "").strip().lower() != "true":
            self.stdout.write("seed_initial skipped (SEED_ENABLE != true).")
            return

        ceo_username = os.getenv("SEED_CEO_USERNAME", "ceo")
        ceo_password = os.getenv("SEED_CEO_PASSWORD", "change-me")
        hq_username = os.getenv("SEED_HQ_USERNAME", "hq")
        hq_password = os.getenv("SEED_HQ_PASSWORD", "change-me")
        field_username = os.getenv("SEED_FIELD_USERNAME", "field1")
        field_password = os.getenv("SEED_FIELD_PASSWORD", "change-me")

        project_code = os.getenv("SEED_PROJECT_CODE", "PRJ-DEMO-001")
        project_name = os.getenv("SEED_PROJECT_NAME", "Demo Project")

        User = get_user_model()

        ceo_user, ceo_created = User.objects.get_or_create(username=ceo_username)
        ceo_user.set_password(ceo_password)
        ceo_user.save(update_fields=["password"])
        UserProfile.objects.get_or_create(user=ceo_user, defaults={"role": Role.CEO})

        hq_user, hq_created = User.objects.get_or_create(username=hq_username)
        hq_user.set_password(hq_password)
        hq_user.save(update_fields=["password"])
        UserProfile.objects.get_or_create(user=hq_user, defaults={"role": Role.HQ})

        field_user, field_created = User.objects.get_or_create(username=field_username)
        field_user.set_password(field_password)
        field_user.save(update_fields=["password"])
        UserProfile.objects.get_or_create(user=field_user, defaults={"role": Role.FIELD})

        project, project_created = Project.objects.get_or_create(
            code=project_code, defaults={"name": project_name}
        )

        assignment, assignment_created = ProjectAssignment.objects.get_or_create(
            user=field_user, project=project, defaults={"is_active": True}
        )

        self.stdout.write(
            "seed_initial done: "
            f"ceo={'created' if ceo_created else 'exists'}, "
            f"hq={'created' if hq_created else 'exists'}, "
            f"field={'created' if field_created else 'exists'}, "
            f"project={'created' if project_created else 'exists'}, "
            f"assignment={'created' if assignment_created else 'exists'}"
        )
