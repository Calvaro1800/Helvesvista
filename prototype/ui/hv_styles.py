"""ui/hv_styles.py — HelveVista 2.0 design tokens."""

HV_DARK   = "#0F1E2E"
HV_CARD   = "#122033"
HV_BORDER = "#1A3048"
HV_GOLD   = "#C9A84C"
HV_MUTED  = "#7A96B0"
HV_GREEN  = "#6FCF97"
HV_BLUE   = "#56B0E8"
HV_TEXT   = "#C8D8E8"
HV_DIM    = "#3E5F7A"

HV_MOBILE_CSS = """
<style>
@media (max-width: 768px) {
    /* Stack Streamlit columns vertically */
    [data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="stVerticalBlock"] {
        width: 100% !important;
        min-width: 100% !important;
    }

    /* Reduce main container padding */
    .main .block-container {
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-top: 1rem !important;
    }

    /* Keep the floating chat FAB reachable — shift left of the bottom nav */
    div[data-testid="stVerticalBlock"]:has(button[aria-label="💬"]) {
        bottom: 16px !important;
        right: 12px !important;
    }

    /* Ensure body text stays readable */
    html, body, [data-testid="stApp"] {
        font-size: 15px !important;
    }
    p, li, label, .stMarkdown {
        font-size: 0.92rem !important;
        line-height: 1.65 !important;
    }

    /* Prevent table overflow */
    table {
        display: block !important;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch !important;
    }
}
</style>
"""
