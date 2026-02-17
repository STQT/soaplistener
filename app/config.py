"""Configuration for soaplistener."""
import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/soaplistener"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
