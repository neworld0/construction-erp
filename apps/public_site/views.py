from django.shortcuts import get_object_or_404, redirect, render

from .models import ContactMessage, PublicProject


def home(request):
    highlights = (
        PublicProject.objects.filter(is_published=True)
        .order_by("-created_at")[:3]
    )
    return render(
        request,
        "public_site/home.html",
        {"highlights": highlights},
    )


def about(request):
    return render(request, "public_site/about.html")


def projects_list(request):
    projects = (
        PublicProject.objects.filter(is_published=True)
        .order_by("-created_at")
    )
    return render(
        request,
        "public_site/projects_list.html",
        {"projects": projects},
    )


def projects_detail(request, slug):
    project = get_object_or_404(PublicProject, slug=slug, is_published=True)
    return render(
        request,
        "public_site/projects_detail.html",
        {"project": project},
    )


def partners(request):
    return render(request, "public_site/partners.html")


def contact(request):
    if request.method == "POST":
        ContactMessage.objects.create(
            name=(request.POST.get("name") or "").strip(),
            email=(request.POST.get("email") or "").strip(),
            phone=(request.POST.get("phone") or "").strip(),
            message=(request.POST.get("message") or "").strip(),
        )
        return redirect("/contact/?sent=1")

    sent = request.GET.get("sent") == "1"
    return render(request, "public_site/contact.html", {"sent": sent})
