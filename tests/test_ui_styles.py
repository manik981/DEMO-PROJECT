"""Guard the two dark-on-dark regressions without needing a browser.

Streamlit renders st.status as an expander. These checks test the declared
palette with WCAG contrast maths so a future theme edit cannot silently make the
status container or alerts unreadable again.
"""

from __future__ import annotations

from pathlib import Path

APP_SOURCE = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")


def _luminance(hex_colour: str) -> float:
    value = hex_colour.lstrip("#")
    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_css_is_injected_into_the_app():
    assert "st.markdown(CSS, unsafe_allow_html=True)" in APP_SOURCE


def test_status_expander_header_overrides_dark_theme_surface():
    # The root cause: Streamlit's dark summary painted dark while global p was navy.
    assert '[data-testid="stExpander"] summary {' in APP_SOURCE
    assert "background: var(--surface) !important;" in APP_SOURCE
    assert '[data-testid="stExpander"] summary p { color: var(--navy) !important; }' in APP_SOURCE


def test_status_container_body_and_nested_text_stay_readable():
    for selector in (
        '[data-testid="stExpander"] [data-testid="stExpanderDetails"] { background: var(--surface); }',
        '[data-testid="stExpander"] [data-testid="stExpanderDetails"] span,',
        '[data-testid="stMain"] [data-testid="stText"] span { color: var(--navy) !important; }',
        '[data-testid="stSidebar"] p,',
        '[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #D5DDE7 !important; }',
        '[data-testid="stSidebar"] h1,',
    ):
        assert selector in APP_SOURCE


def test_button_and_file_chip_descendants_use_contrasting_ink():
    for selector in (
        '[data-testid="stMain"] [data-testid="stBaseButton-primary"] * { color: #FFFFFF !important; }',
        '[data-testid="stMain"] [data-testid="stFileChip"] {',
        '[data-testid="stMain"] [data-testid="stFileChip"] *,',
        '[data-testid="stMain"] [data-testid="stFileChips"] [data-testid="stBaseButton-borderlessIcon"] * {',
    ):
        assert selector in APP_SOURCE
    assert _contrast("#FFFFFF", "#0D1B2A") >= 4.5
    assert _contrast("#0D1B2A", "#FFFFFF") >= 4.5


def test_alert_ink_and_pastel_surfaces_clear_wcag_aa():
    pairs = {
        "error": ("#8A1C1C", "#FDECEC"),
        "warning": ("#6B4700", "#FFF6E0"),
        "info": ("#1F3A57", "#EAF2FB"),
        "success": ("#1E4D36", "#EAF5EE"),
    }
    for name, (ink, surface) in pairs.items():
        assert ink.lower() in APP_SOURCE.lower(), f"{name} alert ink is not styled"
        assert surface.lower() in APP_SOURCE.lower(), f"{name} alert surface is not styled"
        assert _contrast(ink, surface) >= 4.5, f"{name} alert contrast is too low"


def test_main_ink_on_white_clears_wcag_aaa():
    assert _contrast("#0D1B2A", "#FFFFFF") >= 7.0
    assert _contrast("#4E5D6C", "#FFFFFF") >= 4.5
