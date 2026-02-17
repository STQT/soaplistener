"""Process Crystals SetLoyalty XML - сохраняем как строку."""
import xml.etree.ElementTree as ET
from app.extensions import db
from app.models import PurchasesData


class PurchaseProcessor:
    """Сохраняет декодированный XML в БД."""

    def process(self, xml_str: str, version: str | None = None) -> dict:
        """Сохранить XML и опционально извлечь count для индекса."""
        purchases_count = None
        try:
            root = ET.fromstring(xml_str)
            count_attr = root.attrib.get("count")
            if count_attr:
                purchases_count = int(count_attr)
        except Exception:
            pass

        record = PurchasesData(
            xml_content=xml_str,
            version=version,
            purchases_count=purchases_count,
        )
        db.session.add(record)
        db.session.commit()

        return {"count": purchases_count or 0, "id": record.id}
