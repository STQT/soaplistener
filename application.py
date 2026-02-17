"""
SOAP Listener for Crystals SetLoyalty processPurchases.
Receives base64-encoded XML, decodes and stores in database.
"""
import base64
import hashlib
import re
import logging
from flask import Flask, request, Response
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


def extract_purchases_from_soap(body: bytes) -> tuple[str | None, str | None, str | None]:
    """Extract base64 purchases, version, and method name from SOAP body."""
    try:
        text = body.decode("utf-8", errors="replace")
        # Определяем вызываемый метод
        method_match = re.search(
            r"<[^:]*:?process(Purchases|CancelledPurchases)(?:WithTI)?[^>]*>",
            text,
            re.IGNORECASE
        )
        method_name = None
        if method_match:
            full_match = re.search(
                r"<[^:]*:?(processPurchases|processPurchasesWithTI|processCancelledPurchases|processCancelledPurchasesWithTI)[^>]*>",
                text,
                re.IGNORECASE
            )
            if full_match:
                method_name = full_match.group(1).lower()
        
        # Ищем <purchases>BASE64</purchases>
        match = re.search(r"<[^:]*:?purchases[^>]*>([^<]+)</[^:]*:?purchases>", text, re.IGNORECASE | re.DOTALL)
        purchases_b64 = match.group(1).strip() if match else None
        # Version
        version_match = re.search(r"<[^:]*:?version[^>]*>([^<]+)</[^:]*:?version>", text, re.IGNORECASE)
        version = version_match.group(1).strip() if version_match else None
        return purchases_b64, version, method_name
    except Exception as e:
        logger.exception("Failed to extract purchases from SOAP: %s", e)
        return None, None, None


def build_soap_response(method_name: str | None = None) -> str:
    """
    Build SOAP response according to official documentation.
    Returns boolean True in case of successful package processing.
    """
    # Определяем имя метода ответа на основе входящего метода
    if method_name:
        if method_name == "processpurchases":
            response_method = "processPurchasesResponse"
        elif method_name == "processpurchaseswithti":
            response_method = "processPurchasesWithTIResponse"
        elif method_name == "processcancelledpurchases":
            response_method = "processCancelledPurchasesResponse"
        elif method_name == "processcancelledpurchaseswithti":
            response_method = "processCancelledPurchasesWithTIResponse"
        else:
            response_method = "processPurchasesResponse"
    else:
        response_method = "processPurchasesResponse"
    
    # Формат ответа согласно официальной документации
    # Возвращаемый параметр: boolean, True при успешной обработке
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ns2:{response_method} xmlns:ns2="http://purchases.erpi.crystals.ru">
      <return>true</return>
    </ns2:{response_method}>
  </soap:Body>
</soap:Envelope>"""




@app.route("/soap", methods=["POST"])
def soap_endpoint():
    """
    SOAP endpoint for Crystals SetLoyalty.
    Supports: processPurchases, processPurchasesWithTI, 
              processCancelledPurchases, processCancelledPurchasesWithTI.
    Returns boolean True according to official documentation.
    """
    body = request.get_data()
    purchases_b64, version, method_name = extract_purchases_from_soap(body)

    # Логируем входящий запрос для отладки
    logger.info(f"Received SOAP request, method: {method_name or 'unknown'}, has purchases: {bool(purchases_b64)}")

    # Строим ответ на основе вызываемого метода
    soap_response = build_soap_response(method_name)

    if not purchases_b64:
        logger.warning("No purchases data in request, returning OK anyway")
        return Response(soap_response, status=200, mimetype="text/xml; charset=utf-8")

    try:
        decoded = base64.b64decode(purchases_b64)
        xml_str = decoded.decode("utf-8")
    except Exception as e:
        logger.exception("Base64 decode failed: %s", e)
        # Всё равно возвращаем 200 с boolean True, чтобы Crystals не повторял запрос
        return Response(soap_response, status=200, mimetype="text/xml; charset=utf-8")

    # Вычисляем хеш содержимого для дедупликации
    content_hash = hashlib.sha256(xml_str.encode("utf-8")).hexdigest()
    
    # Проверяем, не был ли уже обработан этот пакет
    existing = db.session.query(PurchasesData).filter_by(content_hash=content_hash).first()
    if existing:
        logger.warning(
            f"Duplicate request detected! Content hash: {content_hash[:16]}..., "
            f"already processed at {existing.created_at} (ID: {existing.id})"
        )
        # Возвращаем успешный ответ, но не обрабатываем повторно
        logger.info("Returning boolean True for duplicate request (already processed)")
        return Response(soap_response, status=200, mimetype="text/xml; charset=utf-8")

    try:
        purchase_processor.process(xml_str, version=version, content_hash=content_hash)
        logger.info(f"Successfully processed purchases (hash: {content_hash[:16]}...), returning boolean True")
    except Exception as e:
        logger.exception("DB save failed: %s", e)
        # Согласно документации, возвращаем True даже при ошибках БД,
        # чтобы избежать повторной отправки пакета

    logger.info("Response: <return>true</return> (boolean True for successful processing)")
    return Response(soap_response, status=200, mimetype="text/xml; charset=utf-8")


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
