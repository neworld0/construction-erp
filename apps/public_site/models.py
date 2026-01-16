from django.db import models


class PublicProjectCategory(models.TextChoices):
    ARCH = "ARCH", "Architecture"
    CIVIL = "CIVIL", "Civil"
    LAND = "LAND", "Landscape"


class PublicProject(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, db_index=True)
    category = models.CharField(max_length=10, choices=PublicProjectCategory.choices)
    location = models.CharField(max_length=255, blank=True, default="")
    year = models.PositiveIntegerField(null=True, blank=True)
    client = models.CharField(max_length=255, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    detail = models.TextField(blank=True, default="")
    thumbnail = models.FileField(upload_to="public_projects/", blank=True, null=True)
    is_published = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.title


class ContactMessage(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True, default="")
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} - {self.email}"
