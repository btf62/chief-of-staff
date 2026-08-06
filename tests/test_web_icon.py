"""Focused product-icon integration and packaging-boundary tests."""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ElementTree
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from flask import Flask, render_template_string

from chief_of_staff.web.app import DEFAULT_HOST, close_application, create_app

ROOT = Path(__file__).resolve().parents[1]
DESIGN_ASSET_ROOT = ROOT / "docs/product/design/assets"
STATIC_ASSET_ROOT = ROOT / "src/chief_of_staff/web/static"
BASE_URL = f"http://{DEFAULT_HOST}:8765"
ICON_ASSETS = (
    "chief-of-staff-icon.svg",
    "chief-of-staff-icon-32.png",
    "chief-of-staff-icon-16.png",
)


class _AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.scripts = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "link":
            self.links.append(values)
        elif tag == "img":
            self.images.append(values)
        elif tag == "script":
            self.scripts += 1


def _render_empty_home(tmp_path: Path) -> tuple[Flask, str]:
    app = create_app(
        tmp_path / "state.sqlite3",
        session_secret=b"s" * 32,
        testing=True,
    )
    response = app.test_client().get("/", base_url=BASE_URL)
    assert response.status_code == 200
    return app, response.get_data(as_text=True)


def _parse_assets(html: str) -> _AssetParser:
    parser = _AssetParser()
    parser.feed(html)
    return parser


@pytest.mark.parametrize("asset_name", ICON_ASSETS)
def test_application_icon_copy_matches_governing_design_asset(
    asset_name: str,
) -> None:
    assert (STATIC_ASSET_ROOT / asset_name).read_bytes() == (
        DESIGN_ASSET_ROOT / asset_name
    ).read_bytes()


def test_governing_svg_is_valid_and_uses_only_the_accepted_palette() -> None:
    svg = (DESIGN_ASSET_ROOT / "chief-of-staff-icon.svg").read_text(encoding="utf-8")
    ElementTree.fromstring(svg)  # noqa: S314 - trusted, committed design asset
    assert set(re.findall(r"#[0-9A-Fa-f]{6}", svg)) == {
        "#241F20",
        "#F2C659",
        "#EEE7D6",
    }


@pytest.mark.parametrize("size", (16, 32))
def test_png_fallback_has_exact_square_dimensions(size: int) -> None:
    png = (DESIGN_ASSET_ROOT / f"chief-of-staff-icon-{size}.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (size, size)


def test_shared_head_declares_svg_and_png_favicons(tmp_path: Path) -> None:
    app, html = _render_empty_home(tmp_path)
    try:
        icon_links = [
            link for link in _parse_assets(html).links if link.get("rel") == "icon"
        ]
        assert icon_links == [
            {
                "rel": "icon",
                "type": "image/svg+xml",
                "href": "/static/chief-of-staff-icon.svg",
            },
            {
                "rel": "icon",
                "type": "image/png",
                "sizes": "32x32",
                "href": "/static/chief-of-staff-icon-32.png",
            },
            {
                "rel": "icon",
                "type": "image/png",
                "sizes": "16x16",
                "href": "/static/chief-of-staff-icon-16.png",
            },
        ]
    finally:
        close_application(app)


def test_visible_header_icon_is_local_explicit_and_decorative(tmp_path: Path) -> None:
    app, html = _render_empty_home(tmp_path)
    try:
        parser = _parse_assets(html)
        icons = [
            image for image in parser.images if image.get("class") == "product-icon"
        ]
        assert icons == [
            {
                "class": "product-icon",
                "src": "/static/chief-of-staff-icon.svg",
                "width": "32",
                "height": "32",
                "alt": "",
            }
        ]
        assert parser.scripts == 0
        assert not icons[0]["src"].startswith(("data:", "http://", "https://"))
    finally:
        close_application(app)


def test_classic_and_planner_children_inherit_one_shared_icon(tmp_path: Path) -> None:
    app, classic_html = _render_empty_home(tmp_path)
    try:
        with app.test_request_context("/", base_url=BASE_URL):
            planner_html = render_template_string(
                """{% extends \"base.html\" %}
                {% block title %}Planner preview · Chief of Staff{% endblock %}
                {% block content %}<p>synthetic planner child</p>{% endblock %}
                """
            )
        for html in (classic_html, planner_html):
            parser = _parse_assets(html)
            assert (
                sum(image.get("class") == "product-icon" for image in parser.images)
                == 1
            )
    finally:
        close_application(app)


def test_every_application_view_inherits_the_single_shared_icon() -> None:
    template_root = ROOT / "src/chief_of_staff/web/templates"
    base = (template_root / "base.html").read_text(encoding="utf-8")
    assert base.count('class="product-icon"') == 1

    child_templates = sorted(
        path for path in template_root.glob("*.html") if path.name != "base.html"
    )
    assert {path.name for path in child_templates} >= {
        "conclusion.html",
        "error.html",
        "home.html",
    }
    for template in child_templates:
        assert template.read_text(encoding="utf-8").startswith(
            '{% extends "base.html" %}'
        )


def test_header_icon_css_preserves_the_complete_undecorated_square() -> None:
    css = (STATIC_ASSET_ROOT / "style.css").read_text(encoding="utf-8")
    match = re.search(r"\.product-icon\s*\{(?P<body>[^}]*)\}", css)
    assert match is not None
    declarations = match.group("body")
    assert "width: 2rem" in declarations
    assert "height: 2rem" in declarations
    assert all(
        forbidden not in declarations
        for forbidden in (
            "animation",
            "border-radius",
            "box-shadow",
            "filter",
            "object-fit",
            "transform",
        )
    )


def test_icon_integration_adds_no_remote_or_executable_browser_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_call(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("icon rendering must not make an external call")

    monkeypatch.setattr("urllib.request.urlopen", forbidden_call)
    monkeypatch.setattr("openai.OpenAI", forbidden_call)
    app, html = _render_empty_home(tmp_path)
    try:
        parser = _parse_assets(html)
        browser_assets = [
            asset
            for asset in (*parser.links, *parser.images)
            if asset.get("href", asset.get("src", ""))
        ]
        assert parser.scripts == 0
        assert all(
            asset.get("href", asset.get("src", "")).startswith("/static/")
            for asset in browser_assets
        )
        assert "data:" not in html
    finally:
        close_application(app)
