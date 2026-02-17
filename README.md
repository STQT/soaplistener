# SOAP Listener для Crystals SetLoyalty

Принимает SOAP-запросы `processPurchases` от Crystals SetLoyalty, декодирует base64 из `<purchases>`, сохраняет XML в базу и позволяет анализировать данные через админку.

## Возможности

- **SOAP endpoint** `/soap` — принимает `processPurchases` (Content-Type: text/xml)
- **Base64 декодирование** — извлекает XML из `<purchases>`
- **Хранение** — декодированный XML сохраняется как строка в PostgreSQL
- **Админка** — Flask-Admin на `/admin` для просмотра и поиска

## Запуск (локально)

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# PostgreSQL должен быть запущен, переменная DATABASE_URL
export DATABASE_URL="postgresql://user:pass@localhost:5432/soaplistener"
python application.py
```

Для production (gunicorn + systemd) указывайте модуль `wsgi:app`:

```bash
gunicorn --workers 2 --bind 127.0.0.1:5000 "wsgi:app"
```

- SOAP: `http://localhost:5000/soap`
- Админка: `http://localhost:5000/admin`
- Health: `http://localhost:5000/health`

## Docker Compose (если будет добавлен)

```bash
docker-compose up -d
```

## Формат данных

Входной SOAP содержит base64-кодированный XML в теге `<purchases>`. После декодирования получается XML с чеками (purchase) и их позициями. Всё хранится целиком как `xml_content`.

## Структура проекта

```
soaplistener/
├── application.py   # Flask + SOAP endpoint + Admin
├── wsgi.py          # Точка входа для gunicorn (wsgi:app)
├── app/
│   ├── config.py
│   ├── extensions.py
│   ├── models.py
│   └── services/
│       └── purchase_processor.py
├── requirements.txt
└── README.md
```
