"""
SOAP Listener for Crystals SetLoyalty processPurchases.
Receives base64-encoded XML, decodes and stores in database.
"""
import base64
import re
import logging
from flask import Flask, request
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from app.extensions import db
from app.models import PurchasesData
from app.services.purchase_processor import PurchaseProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object("app.config.Config")
db.init_app(app)

class PurchasesDataView(ModelView):
    column_list = ["id", "purchases_count", "version", "created_at"]
    column_default_sort = ("created_at", True)
    column_searchable_list = ["xml_content"]
    column_sortable_list = ["id", "purchases_count", "created_at"]
    form_columns = ["xml_content", "version", "purchases_count"]
    form_widget_args = {"xml_content": {"rows": 15}}


admin = Admin(app, name="Crystals SetLoyalty", template_mode="bootstrap4")
admin.add_view(PurchasesDataView(PurchasesData, db.session, name="Purchases (XML)", category="Данные"))

purchase_processor = PurchaseProcessor()


def extract_purchases_from_soap(body: bytes) -> tuple[str | None, str | None]:
    """Extract base64 purchases and version from SOAP body."""
    try:
        text = body.decode("utf-8", errors="replace")
        # Ищем <purchases>BASE64</purchases>
        match = re.search(r"<[^:]*:?purchases[^>]*>([^<]+)</[^:]*:?purchases>", text, re.IGNORECASE | re.DOTALL)
        purchases_b64 = match.group(1).strip() if match else None
        # Version
        version_match = re.search(r"<[^:]*:?version[^>]*>([^<]+)</[^:]*:?version>", text, re.IGNORECASE)
        version = version_match.group(1).strip() if version_match else None
        return purchases_b64, version
    except Exception as e:
        logger.exception("Failed to extract purchases from SOAP: %s", e)
        return None, None


def soap_response(success: bool, message: str = "") -> str:
    """Build SOAP response for processPurchases."""
    status = "success" if success else "error"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ns2:processPurchasesResponse xmlns:ns2="http://purchases.erpi.crystals.ru">
      <return>
        <status>{status}</status>
        <message>{message}</message>
      </return>
    </ns2:processPurchasesResponse>
  </soap:Body>
</soap:Envelope>"""


@app.route("/soap", methods=["POST"])
def soap_endpoint():
    """SOAP endpoint for Crystals SetLoyalty processPurchases."""
    if "text/xml" not in request.content_type and "application/xml" not in request.content_type:
        return "Content-Type must be text/xml or application/xml", 400

    body = request.get_data()
    purchases_b64, version = extract_purchases_from_soap(body)

    if not purchases_b64:
        logger.warning("No purchases data in request")
        return soap_response(False, "No purchases data"), 200, {"Content-Type": "text/xml; charset=utf-8"}

    try:
        decoded = base64.b64decode(purchases_b64)
        xml_str = decoded.decode("utf-8")
    except Exception as e:
        logger.exception("Base64 decode failed: %s", e)
        return soap_response(False, str(e)), 200, {"Content-Type": "text/xml; charset=utf-8"}

    try:
        result = purchase_processor.process(xml_str, version=version)
        logger.info("Processed %d purchases", result.get("count", 0))
        return soap_response(True, f"Processed {result.get('count', 0)} purchases"), 200, {"Content-Type": "text/xml; charset=utf-8"}
    except Exception as e:
        logger.exception("Processing failed: %s", e)
        return soap_response(False, str(e)), 200, {"Content-Type": "text/xml; charset=utf-8"}


@app.route("/health")
def health():
    """Health check for Docker."""
    return {"status": "ok"}


def create_app():
    """Application factory."""
    return app


if __name__ == "__main__":
    with app.app_context():
        from app.models import PurchasesData  # noqa: F401
        db.create_all()
    app.run(host="0.0.0.0", port=5000)
