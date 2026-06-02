# BrainExtender — Текущее состояние проекта

> Документ описывает архитектуру, инфраструктуру и рабочее состояние на 2026-06-02.  
> Читай его, когда заходишь с нового компа или после перерыва.

---

## Что это такое

Персональный second brain на базе Obsidian. Работает так:

1. Отправляешь текст / PDF / фото / DOCX боту в Telegram
2. Claude классифицирует контент и сохраняет структурированную заметку в Markdown
3. Obsidian синхронизирует заметки через WebDAV (Remotely Save плагин)
4. API доступен внешним клиентам на `https://brain.kzkovich.ru/api/ingest`

---

## Инфраструктура

| Компонент | Где |
|---|---|
| Сервер | VPS, IP `62.3.12.2` |
| Проект | `/opt/BrainExtender/` |
| Данные (заметки, БД) | `/srv/brain/` — bind mount для Docker и nginx |
| Nginx конфиг | `/etc/nginx/sites-available/brain.kzkovich.ru` |
| WebDAV htpasswd | `/etc/nginx/dav.htpasswd` |
| Docker | v1 — использовать `docker-compose`, не `docker compose` |

### Docker-контейнеры

```
brain-bot   — Telegram бот (aiogram 3.x)
brain-api   — FastAPI HTTP API (порт 8001, только localhost)
```

Запуск/рестарт:
```bash
cd /opt/BrainExtender
docker-compose down && docker-compose up -d
docker logs brain-bot --tail 50
```

### Nginx

`brain.kzkovich.ru` → две точки входа:

| URL | Куда |
|---|---|
| `https://brain.kzkovich.ru/` | FastAPI `127.0.0.1:8001` (API) |
| `https://brain.kzkovich.ru/dav/` | WebDAV → `/srv/brain/users/` |

---

## Структура данных `/srv/brain/`

```
/srv/brain/
├── users/
│   └── {tg_user_id}/
│       ├── brain/               ← заметки Obsidian (Markdown)
│       │   ├── _inbox/
│       │   ├── _index/manifest.json
│       │   ├── work/
│       │   │   └── {workspace}/
│       │   │       ├── meetings/
│       │   │       ├── features/
│       │   │       ├── research/
│       │   │       └── tasks/
│       │   ├── personal/
│       │   │   ├── health/
│       │   │   ├── travel/
│       │   │   └── interests/
│       │   └── attachments/     ← изображения из PDF/DOCX
│       ├── chroma/              ← векторный индекс (не используется активно)
│       └── meta.json            ← настройки пользователя
└── shared/
```

**Важно:** данные лежат в `/srv/brain/`, а **не** в Docker-volume. Это намеренно — nginx должен читать/писать эти файлы (WebDAV), а Docker не даёт nginx доступ к своим volume-директориям (`/var/lib/docker/volumes/` закрыт для `www-data`).

---

## Настройка Obsidian (Remotely Save)

Плагин: **Remotely Save** (в Community plugins)

Настройки:
- Service: `WebDAV`
- Server address: `https://brain.kzkovich.ru`
- Base path: `/dav/390604543/brain`
- Username: `390604543`
- Password: `Cbdo8f6nmT`

---

## Компоненты кода

```
/opt/BrainExtender/
├── bot/
│   └── main.py          — Telegram бот. Обработчики: текст, документы (PDF/DOCX), фото
├── api/
│   └── main.py          — FastAPI. POST /api/ingest — принимает текст, запускает пайплайн
├── brain/
│   ├── classifier.py    — Классифицирует контент через Claude (JSON-mode)
│   ├── document_parser.py — Парсит PDF (pymupdf), DOCX, изображения (Claude Vision)
│   ├── formatter.py     — Форматирует заметку через Jinja2-шаблон + Claude
│   ├── linker.py        — Добавляет [[wikilinks]] на связанные заметки
│   ├── deduplicator.py  — Проверяет дубли перед сохранением
│   ├── indexer.py       — Обновляет manifest.json
│   ├── storage.py       — Файловое хранилище с защитой от path traversal
│   └── profiles.py      — Загружает профили пользователя из /profiles/
├── core/
│   ├── claude.py        — Обёртка над Anthropic API
│   └── quotas.py        — Лимиты по тарифам (free/pro/plus)
├── db/
│   └── models.py        — SQLAlchemy: User, UsageLog, Payment. SQLite в /srv/brain/
├── config/
│   └── settings.py      — Pydantic settings, читает .env
├── profiles/            — YAML-файлы профилей (universal, developer, etc.)
├── templates/           — Jinja2-шаблоны заметок
├── deploy/
│   └── nginx.conf       — Шаблон nginx конфига (эталон)
└── scripts/
    ├── create_test_user.py
    └── relink_all.py    — Перестраивает wikilinks по всем заметкам
```

---

## Пайплайн обработки сообщения

```
Telegram message
    ↓
[bot/main.py] handle_ingest / handle_document / handle_photo
    ↓
[brain/document_parser.py] → извлечь текст + изображения (если файл)
    ↓
[brain/classifier.py] classify() → Claude определяет тип, путь, теги
    ↓
[brain/deduplicator.py] check_before_save() → есть ли похожее уже в brain?
    ↓
[brain/formatter.py] format_content() → Claude форматирует в Markdown по шаблону
    ↓
[bot] показывает превью пользователю с кнопками ✅ / ✏️ / ❌
    ↓ (после нажатия ✅)
[brain/storage.py] write_file() → сохраняет .md файл
[brain/indexer.py] update_index() → обновляет manifest.json
```

---

## Переменные окружения (`.env`)

```
TELEGRAM_TOKEN=...
ANTHROPIC_API_KEY=...
DATABASE_URL=sqlite:///./second_brain.db
DATA_PATH=./data
```

Модель по умолчанию: `claude-sonnet-4-6` (в `config/settings.py`).

---

## Тарифы

| Тариф | Ингестов/день | Запросов/день | API бюджет |
|---|---|---|---|
| free | 10 | 20 | $0.50 |
| pro | 100 | 200 | $3.00 |
| plus | 500 | 1000 | $10.00 |

Тариф `free` имеет trial-период (настраивается в БД). Команды бота: `/billing`, `/stats`, `/profile`, `/workspace`.

---

## Известные особенности и фиксы

### PDF и большие файлы (исправлено 2026-06-02)
`bot.download_file()` имеет дефолтный таймаут 30 сек. Файлы 4–10 МБ не успевали скачаться.  
Фикс: `timeout=120` передаётся явно в `bot/main.py` (строки 184 и 250).

### WebDAV 403 Forbidden (исправлено 2026-06-02)
Nginx worker `www-data` не может проходить по пути `/var/lib/docker/volumes/` — Docker запрещает.  
Фикс: данные перенесены в `/srv/brain/` (bind mount), nginx alias указывает туда же.  
`client_max_body_size 100m` добавлен в `/dav/` location (дефолт nginx 1 МБ блокировал бы загрузку файлов через WebDAV).

---

## Как развернуть с нуля на новом сервере

```bash
# 1. Клонировать
git clone git@github-personal:Kzkovich/BrainExtender.git /opt/BrainExtender
cd /opt/BrainExtender

# 2. Создать .env
cp .env.example .env
nano .env  # вписать TELEGRAM_TOKEN и ANTHROPIC_API_KEY

# 3. Создать директорию данных
mkdir -p /srv/brain
chown -R www-data:www-data /srv/brain

# 4. Запустить контейнеры
docker-compose up -d --build

# 5. Nginx
# Установить nginx с dav_ext модулем:
apt install -y libnginx-mod-http-dav-ext
# Скопировать конфиг:
cp deploy/nginx.conf /etc/nginx/sites-available/brain.kzkovich.ru
ln -s /etc/nginx/sites-available/brain.kzkovich.ru /etc/nginx/sites-enabled/
# Получить SSL:
certbot --nginx -d brain.kzkovich.ru
# Создать WebDAV пароль (username = tg_user_id):
apt install -y apache2-utils
htpasswd -c /etc/nginx/dav.htpasswd {tg_user_id}
nginx -t && systemctl reload nginx

# 6. Создать тестового пользователя в БД
docker exec brain-bot python3 scripts/create_test_user.py
```
