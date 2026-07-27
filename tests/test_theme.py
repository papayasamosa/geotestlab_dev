"""Contract tests for the Scandinavian theme.

These tests parse `.streamlit/config.toml` and `styles.css` directly — no
Streamlit runtime involved — and pin the values that make up the theme
contract: exact palette, exact radii, native widget-border / sidebar-nav
flags, the absence of `st-styled` as a dependency, and CSS safety rules
(no global focus-outline suppression, no BaseWeb internal classes, no
automatic dark-mode override). CSS is checked for specific rules, not
compared to the whole file by snapshot.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / ".streamlit" / "config.toml"
CSS_PATH = REPO_ROOT / "styles.css"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def _load_config() -> dict:
    return tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _load_css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def _load_pyproject() -> dict:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


class TestThemePalette:
    """Exact Scandinavian palette values in [theme]."""

    def test_base_is_light(self):
        assert _load_config()["theme"]["base"] == "light"

    def test_primary_colour(self):
        assert _load_config()["theme"]["primaryColor"] == "#5B8C7D"

    def test_backgrounds(self):
        theme = _load_config()["theme"]
        assert theme["backgroundColor"] == "#F7F7F2"
        assert theme["secondaryBackgroundColor"] == "#E8ECE6"

    def test_text_colour(self):
        assert _load_config()["theme"]["textColor"] == "#1E2421"

    def test_link_and_code_background(self):
        theme = _load_config()["theme"]
        assert theme["linkColor"] == "#4A7B6C"
        assert theme["codeBackgroundColor"] == "#E3E8E1"

    def test_border_colours(self):
        theme = _load_config()["theme"]
        assert theme["borderColor"] == "#CED7CE"
        assert theme["dataframeBorderColor"] == "#C8D1C8"
        assert theme["dataframeHeaderBackgroundColor"] == "#D8E0D7"


class TestThemeSidebarPalette:
    """Exact Scandinavian palette values in [theme.sidebar]."""

    def test_sidebar_colours(self):
        sidebar = _load_config()["theme"]["sidebar"]
        assert sidebar["primaryColor"] == "#5B8C7D"
        assert sidebar["backgroundColor"] == "#EEF2EC"
        assert sidebar["secondaryBackgroundColor"] == "#E1E8E1"
        assert sidebar["textColor"] == "#222925"
        assert sidebar["linkColor"] == "#467565"
        assert sidebar["codeBackgroundColor"] == "#DCE4DC"

    def test_sidebar_border_colours(self):
        sidebar = _load_config()["theme"]["sidebar"]
        assert sidebar["borderColor"] == "#C8D2C8"
        assert sidebar["dataframeBorderColor"] == "#C2CCC2"
        assert sidebar["dataframeHeaderBackgroundColor"] == "#D2DCD2"

    def test_sidebar_widget_border_enabled(self):
        assert _load_config()["theme"]["sidebar"]["showWidgetBorder"] is True


class TestThemeRadiiAndWidgets:
    def test_radii(self):
        theme = _load_config()["theme"]
        assert theme["baseRadius"] == "6px"
        assert theme["buttonRadius"] == "8px"
        assert theme["sidebar"]["baseRadius"] == "6px"
        assert theme["sidebar"]["buttonRadius"] == "8px"

    def test_widget_border_enabled(self):
        assert _load_config()["theme"]["showWidgetBorder"] is True

    def test_sidebar_outer_border_disabled(self):
        # showSidebarBorder governs the vertical separator between the
        # sidebar and main content; the CSS must not reintroduce it (see
        # TestCSSSafety.test_no_sidebar_border_override below).
        assert _load_config()["theme"]["showSidebarBorder"] is False


class TestClientConfig:
    def test_sidebar_navigation_disabled(self):
        assert _load_config()["client"]["showSidebarNavigation"] is False


class TestNoExternalFonts:
    """No external font URLs unless the product owner explicitly approves them."""

    def test_no_external_font_url(self):
        theme = _load_config()["theme"]
        for key in ("font", "headingFont", "codeFont"):
            assert "http" not in theme[key], f"theme.{key} references an external URL"

    def test_sidebar_no_external_font_url(self):
        sidebar = _load_config()["theme"]["sidebar"]
        for key in ("font", "headingFont", "codeFont"):
            assert "http" not in sidebar[key], f"theme.sidebar.{key} references an external URL"


class TestNoStStyledDependency:
    def test_st_styled_not_a_dependency(self):
        pyproject = _load_pyproject()
        project = pyproject["project"]
        all_deps = list(project.get("dependencies", []))
        for extra_deps in project.get("optional-dependencies", {}).values():
            all_deps.extend(extra_deps)
        joined = " ".join(all_deps).lower()
        assert "st-styled" not in joined
        assert "st_yled" not in joined

    def test_config_attribution_does_not_add_dependency(self):
        # The theme is adapted (not imported) from st-styled; the config
        # file may credit it in a comment but must not install it.
        config_text = CONFIG_PATH.read_text(encoding="utf-8")
        assert "st-styled" in config_text  # attribution comment present
        assert "st_yled" in config_text  # source path attribution present


class TestCSSSafety:
    """Reject patterns that would silently break accessibility or theme layering."""

    def test_no_global_outline_suppression(self):
        assert "outline: none !important" not in _load_css()

    def test_no_baseweb_internal_class(self):
        assert ".st-eb" not in _load_css()

    def test_no_automatic_dark_mode_override(self):
        css = _load_css()
        assert "prefers-color-scheme: dark" not in css
        assert ".dark {" not in css

    def test_no_sidebar_border_override(self):
        # showSidebarBorder=false is a deliberate choice; CSS must not
        # reintroduce a manual sidebar border-right that fights it.
        assert "border-right" not in _load_css()

    def test_focus_visible_rule_present(self):
        css = _load_css()
        for selector in (
            "button:focus-visible",
            "input:focus-visible",
            "textarea:focus-visible",
            '[role="combobox"]:focus-visible',
            '[role="radio"]:focus-visible',
            '[role="checkbox"]:focus-visible',
            "[tabindex]:focus-visible",
        ):
            assert selector in css, f"missing required focus-visible selector: {selector}"
        assert "outline: 3px solid #5B8C7D" in css
        assert "outline-offset: 2px" in css

    def test_no_hardcoded_old_teal_palette(self):
        css = _load_css()
        for old_hex in ("#0F766E", "#0D5D5A", "#CCFBF1", "#E6F7F5", "#7C3AED", "#6D28D9"):
            assert old_hex not in css, f"old teal/purple palette value {old_hex} still in CSS"

    def test_semantic_status_colours_remain_distinct(self):
        css = _load_css()
        assert "--success: #10B981" in css
        assert "--warning: #F59E0B" in css
        assert "--error: #EF4444" in css
        assert "--info: #3B82F6" in css
        # all four must resolve to different values, not one shared sage tone
        values = {"#10B981", "#F59E0B", "#EF4444", "#3B82F6"}
        assert len(values) == 4
