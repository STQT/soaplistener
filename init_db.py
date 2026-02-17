"""Создание таблиц в БД. Запуск: python init_db.py"""
from application import app
from app.extensions import db
from app.models import PurchasesData  # noqa: F401 - для регистрации модели


with app.app_context():
    db.create_all()
    print("Таблицы созданы: purchases_data")
