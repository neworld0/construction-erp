import pytest


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path,expected_title",
    [
        ("/", "<title>ASAN</title>"),
        ("/about/", "<title>회사소개 | ASAN</title>"),
        ("/projects/", "<title>주요실적 | ASAN</title>"),
        ("/partners/", "<title>협력업체 | ASAN</title>"),
        ("/contact/", "<title>문의 | ASAN</title>"),
    ],
)
def test_public_site_branding_and_footer(client, path, expected_title):
    response = client.get(path)
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert expected_title in body
    assert "주식회사 아산" in body
    assert "진익주" in body
    assert "경기도 남양주시 다산중앙로146번길 70-123" in body
    assert 'tel:031-564-9407' in body
    assert 'href="/login/?next=/app/"' in body
    assert "ERP로 이동" in body
