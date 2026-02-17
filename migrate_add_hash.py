"""Миграция: добавление поля content_hash для дедупликации."""
import hashlib
from sqlalchemy import text
from app.extensions import db
from app.config import Config
from flask import Flask
from app.models import PurchasesData

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    # Проверяем, существует ли колонка
    inspector = db.inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('purchases_data')]
    
    if 'content_hash' not in columns:
        # Добавляем колонку content_hash
        try:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    ALTER TABLE purchases_data 
                    ADD COLUMN content_hash VARCHAR(64);
                """))
                conn.commit()
            print("✓ Column content_hash added")
        except Exception as e:
            print(f"Error adding column: {e}")
    else:
        print("✓ Column content_hash already exists")
    
    # Создаём уникальный индекс для быстрого поиска
    try:
        with db.engine.connect() as conn:
            # Проверяем, существует ли индекс
            result = conn.execute(text("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename = 'purchases_data' 
                AND indexname = 'ix_purchases_data_content_hash';
            """))
            if not result.fetchone():
                conn.execute(text("""
                    CREATE UNIQUE INDEX ix_purchases_data_content_hash 
                    ON purchases_data(content_hash);
                """))
                conn.commit()
                print("✓ Unique index on content_hash created")
            else:
                print("✓ Unique index already exists")
    except Exception as e:
        print(f"Note: {e}")
    
    # Для существующих записей вычисляем хеш
    try:
        records = PurchasesData.query.filter(PurchasesData.content_hash.is_(None)).all()
        if records:
            print(f"Computing hashes for {len(records)} existing records...")
            for record in records:
                record.content_hash = hashlib.sha256(record.xml_content.encode("utf-8")).hexdigest()
            db.session.commit()
            print(f"✓ Hashes computed for {len(records)} records")
        else:
            print("✓ No records need hash computation")
    except Exception as e:
        print(f"Error computing hashes: {e}")
        db.session.rollback()

print("Migration completed!")
