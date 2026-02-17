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


# Тип: (purchases_b64, version, method_name, namespace_uri, soap_12)
def extract_purchases_from_soap(body: bytes) -> tuple[str | None, str | None, str | None, str | None, bool]:
    """Extract base64 purchases, version, method name and namespace from SOAP body."""
    try:
        text = body.decode("utf-8", errors="replace")
        # SOAP 1.2 или 1.1
        soap_12 = "http://www.w3.org/2003/05/soap-envelope" in text or "soap/envelope/12" in text

        # Ищем открывающий тег метода и его namespace
        method_tag = re.search(
            r"<([^:>]*:)?(processPurchases|processPurchasesWithTI|processCancelledPurchases|processCancelledPurchasesWithTI)([^>]*)>",
            text,
            re.IGNORECASE
        )
        method_name = None
        namespace_uri = "http://purchases.erpi.crystals.ru"  # по умолчанию из документации
        if method_tag:
            method_name = method_tag.group(2).lower() if method_tag.group(2) else None
            attrs = method_tag.group(3) or ""
            # xmlns:ns2="..." или xmlns="..."
            ns_prefixed = re.search(r'xmlns:([^=]+)=["\']([^"\']+)["\']', attrs)
            ns_default = re.search(r'\bxmlns=["\']([^"\']+)["\']', attrs)
            if ns_prefixed:
                namespace_uri = ns_prefixed.group(2)
            elif ns_default:
                namespace_uri = ns_default.group(1)

        # Ищем <purchases>BASE64</purchases>
        match = re.search(r"<[^:]*:?purchases[^>]*>([^<]+)</[^:]*:?purchases>", text, re.IGNORECASE | re.DOTALL)
        purchases_b64 = match.group(1).strip() if match else None
        version_match = re.search(r"<[^:]*:?version[^>]*>([^<]+)</[^:]*:?version>", text, re.IGNORECASE)
        version = version_match.group(1).strip() if version_match else None
        return purchases_b64, version, method_name, namespace_uri, soap_12
    except Exception as e:
        logger.exception("Failed to extract purchases from SOAP: %s", e)
        return None, None, None, "http://purchases.erpi.crystals.ru", False


def build_soap_response(
    method_name: str | None = None,
    namespace_uri: str = "http://purchases.erpi.crystals.ru",
    soap_12: bool = False,
) -> str:
    """
    Строим ответ в том же формате, что ожидает клиент (с обратной связью).
    return: boolean True при успешной обработке (документация).
    """
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

    # Используем префикс ns2 и namespace из запроса, чтобы клиент принял ответ.
    # Часть клиентов ожидает элемент return в том же namespace (ns2:return).
    ns_prefix = "ns2"
    body_content = (
        f'<{ns_prefix}:{response_method} xmlns:{ns_prefix}="{namespace_uri}">'
        f"<{ns_prefix}:return>true</{ns_prefix}:return>"
        f"</{ns_prefix}:{response_method}>"
    )

    if soap_12:
        envelope_ns = "http://www.w3.org/2003/05/soap-envelope"
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{envelope_ns}">
  <soap:Body>
    {body_content}
  </soap:Body>
</soap:Envelope>"""
    # SOAP 1.1
    envelope_ns = "http://schemas.xmlsoap.org/soap/envelope/"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="{envelope_ns}">
  <soap:Body>
    {body_content}
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
    purchases_b64, version, method_name, namespace_uri, soap_12 = extract_purchases_from_soap(body)

    # Логируем входящий запрос (формат ответа подстраиваем под запрос для режима «с обратной связью»)
    logger.info(
        "Received SOAP request, method: %s, has purchases: %s, namespace: %s, SOAP 1.2: %s",
        method_name or "unknown",
        bool(purchases_b64),
        namespace_uri,
        soap_12,
    )

    # Ответ в том же формате, что и запрос (namespace + SOAP 1.1/1.2), чтобы клиент принял его
    soap_response = build_soap_response(method_name, namespace_uri=namespace_uri, soap_12=soap_12)

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
