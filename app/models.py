"""SQLAlchemy models - храним декодированный XML как строку."""
from datetime import datetime
from app.extensions import db


class PurchasesData(db.Model):
    """Принятые данные от Crystals SetLoyalty. XML хранится как строка."""
    __tablename__ = "purchases_data"

    id = db.Column(db.Integer, primary_key=True)
    xml_content = db.Column(db.Text, nullable=False)  # декодированный XML из <purchases>
    version = db.Column(db.String(50))  # версия из SOAP
    purchases_count = db.Column(db.Integer)  # count из атрибута purchases, для удобства
    content_hash = db.Column(db.String(64), unique=True, index=True)  # SHA256 хеш для дедупликации
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<PurchasesData #{self.id} count={self.purchases_count} {self.created_at}>"
