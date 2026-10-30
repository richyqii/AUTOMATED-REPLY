import re
import unicodedata
from urllib.parse import quote

BUSINESS_NUMBER = "60124182788"
PREFILLED_MESSAGE = "Hi, I'm interested in E-Invoice Training."
WHATSAPP_LINK = f"https://wa.me/{BUSINESS_NUMBER}?text={quote(PREFILLED_MESSAGE, safe='')}"
GUMROAD_URL = "https://einvoicemy.gumroad.com/l/e-invoice-training-2026"

SALES_REPLY = f"""Hello! 👋 Welcome to VIN Corporate Services Sdn Bhd.

Thank you for your interest in our Malaysia E-Invoice Training.

🎓 How to purchase:

1. Open our Gumroad purchase link:
   {GUMROAD_URL}

2. Click "I want this!"

3. Enter your email address and complete payment.

4. Open your Gumroad receipt.

5. Click "Watch Your Training" to access the video.

Need help? Reply HELP, and our team will assist you."""

HELP_REPLY = (
    "Thank you. Your request has been saved for the VIN Corporate Services Sdn Bhd team "
    "to review. Please describe the help you need here. Automatic sales replies are paused. "
    "For direct assistance, call +60 12-418 2788. Reply START to resume automatic replies."
)


def intent(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    command = normalized.strip(".!?, ")
    if command in {"help", "bantuan"}:
        return "help"
    if command in {"stop", "unsubscribe", "berhenti"}:
        return "stop"
    if command == "start":
        return "start"
    # Unicode dashes, spacing, e-invoicing, eInvoice and Malay e-invois.
    normalized = re.sub(r"[‐‑‒–—−]", "-", normalized)
    if re.search(r"\be[\s-]*invoic(?:e|ing)\b|\be[\s-]*invois\b", normalized):
        return "sales"
    return "unknown"
