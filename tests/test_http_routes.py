"""HTTP smoke checks for the public shell and favicon assets."""


def test_homepage_and_favicon_are_served(client):
    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "Sharma Cafe" in homepage.text
    assert '/favicon.svg' in homepage.text

    ico = client.get("/favicon.ico")
    assert ico.status_code == 200
    assert ico.headers["content-type"].startswith("image/x-icon")
    assert ico.content[:6] == b"\x00\x00\x01\x00\x01\x00"

    svg = client.get("/favicon.svg")
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in svg.content
