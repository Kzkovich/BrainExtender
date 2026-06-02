#!/usr/bin/env python3
"""Seed brain with starter notes for Alfa Bank Collection PO work."""
import asyncio
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from brain.indexer import update_index
from brain.storage import BrainStorage


def now():
    return datetime.utcnow().isoformat()


def fm(type_, workspace="alfa-bank", tags=None, people=None, feature_slug=""):
    return {
        "id": str(uuid.uuid4()),
        "type": type_,
        "note_mode": "structured",
        "status": "active",
        "domain": "work",
        "workspace": workspace,
        "feature_slug": feature_slug,
        "tags": tags or [],
        "date_created": now(),
        "date_updated": now(),
        "people": people or [],
        "source": "seed",
        "linked_to": [],
        "ingest_cost_tokens": 0,
        "ingest_model": "seed",
    }


NOTES = [
    (
        "work/alfa-bank/features/discount/_context.md",
        fm("feature", feature_slug="discount", tags=["офер", "дисконт", "90+"]),
        """# Дисконт — офер для сегмента 90+

## Суть
Прощение до 50% долга при единовременном закрытии остатка. Доступно при расторгнутом договоре, сегмент 90+ дней.

## Варианты
- **Дисконт** — клиент платит остаток сразу, банк прощает часть
- **Дисконт в рассрочку** — остаток разбивается на платежи

## Метрики успеха
- % активации дисконта из тех кому он доступен
- Среднее время от показа до активации
- % клиентов закрывших долг без суда

## Ограничения
- Только расторгнутый договор
- Выборочно (не всем клиентам)
- Регуляторика: ФЗ-230, требования к прозрачности оферов
""",
    ),
    (
        "work/alfa-bank/features/refinancing/_context.md",
        fm("feature", feature_slug="refinancing", tags=["офер", "рефинансирование", "30+"]),
        """# Рефинансирование — офер для сегмента 30+

## Суть
Объединяет все долги клиента в один кредит, автоматически гасит задолженность. Доступно с 30+ дней, выборочно.

## Интеграция
Проходит через ЕКК (Единый кредитный конвейер).

## Метрики
- Конверсия из показа офера в заявку
- % одобренных заявок
- Среднее время до погашения после рефинансирования

## Отличие от дисконта
Рефинансирование — новый кредит, дисконт — прощение части долга.
""",
    ),
    (
        "work/alfa-bank/features/alfa-pomoshnik/_context.md",
        fm("feature", feature_slug="alfa-pomoshnik", tags=["помощник", "чатбот", "сегмент-1-30"]),
        """# Альфа-Помощник

## Суть
Интерактивный помощник в разделе должника. Снижает тревожность клиента, отвечает на вопросы. Доступен с 1-го дня.

## Платформы
Android, iOS, Web — реализован на BDUI.

## Роль в CJM
Этап Investigation (1–29 дней). Оферов ещё нет, помощник — основной инструмент взаимодействия.

## Антропоморфизация
Аватар снижает стресс клиента — это наше уникальное конкурентное преимущество перед Сбером и ВТБ.
""",
    ),
    (
        "work/alfa-bank/research/competitors-2026.md",
        fm("research", tags=["конкуренты", "анализ", "recovery"]),
        """# Конкурентный анализ — Collection 2026

## Российские банки

| Банк | Фича | Метрика |
|------|------|---------|
| Сбер | AI-чатбот «Помощник должника», автоплатёж | Recovery 68% (1–30 дн) |
| ВТБ | «Кредит-пауза», тёплое предложение | NPS +15 |
| Т-Банк | Робо-коллектор, геймификация, отсрочка 7 дн | — |

## Мировые лидеры

- **JPMorgan** «Intelligent Collections»: AI + автозвонок → Recovery 73% (30–90 дн)
- **Barclays** Debt Wellbeing Portal: сообщество должников → NPS +20
- **KB Kookmin** AI-бот «Ribo»: изменение даты платежа → time-to-recovery −18%

## Наши преимущества
- Единая точка входа с 1-го дня (конкуренты позже)
- Альфа-Помощник с аватаром
- Витрина оферов прозрачно в цифровом канале
""",
    ),
    (
        "work/alfa-bank/research/bdui-decision.md",
        fm("decision", tags=["BDUI", "технология", "архитектура"]),
        """# Решение: BDUI как дефолтная технология

## Контекст
Любой новый функционал в разделе должника реализуется на BDUI по умолчанию.

## Решение
BDUI — дефолт. Отказ требует обоснования и согласования на Комитете BDUI.

## При использовании BDUI
Обязателен прототип в коде (черновик на моковых данных iOS/Android/JS).

## Последствия
- Единообразие на iOS и Android
- Нет необходимости в отдельных релизах платформ
- Прототип в коде — дополнительный этап перед UX-тестом
""",
    ),
    (
        "work/alfa-bank/research/kpi-targets.md",
        fm("research", tags=["KPI", "метрики", "бюджет"]),
        """# KPI и бюджет — Collection 2026

## Бюджет
Годовой бюджет команды: **70 млн рублей**. Минимальный ROI на фичу: **3:1**.

## Ключевые KPI
- Конверсия в погашение через цифровой канал
- Среднее время до первого погашения после входа в раздел
- % клиентов, закрывших задолженность без судебной стадии
- NPS должников в УКД
- Снижение звонков в колл-центр по вопросам просрочки
- % активации оферов (Дисконт, Рефинансирование, Дисконт в рассрочку, Рассрочка)

## Стратегическое видение
70% должников решают вопрос через мобайл самостоятельно (горизонт 6–12 мес).
""",
    ),
]


async def seed(user_id: str):
    storage = BrainStorage(user_id)
    print(f"Seeding brain for user {user_id}...\n")

    for rel_path, frontmatter, body in NOTES:
        path = storage.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        storage.write_file(rel_path, body, frontmatter)
        update_index(storage, rel_path, frontmatter, body)
        print(f"  ✓ {rel_path}")

    print(f"\nDone. Added {len(NOTES)} notes.")
    print(f"\nNow run: python3 scripts/relink_all.py --user-id {user_id}")


if __name__ == "__main__":
    user_id = sys.argv[1] if len(sys.argv) > 1 else "390604543"
    asyncio.run(seed(user_id))
