# CS2 Skins Analysis System

Аналитическая CLI-система для принятия решений о покупке скинов CS2: buy / no-buy / manual review.

## Что делает

Система автоматизирует сбор и анализ данных о конкретном лоте CS2. На вход — URL листинга или описание предмета. На выход — Decision Card с оценкой: стоит ли покупать, по какой цене можно безопасно выйти, и обоснование решения. Анализирует item identity, exact-параметры (float, stickers, pattern), рыночную цену, премиум за редкость и ликвидность.

Пример вывода Decision Card:

```
╭─── CS2 Analysis ─── BUY ──────────────────────╮
│                                                 │
│  AK-47 | Redline | Field-Tested                │
│  Float: 0.151  Pattern: 661  StatTrak: No      │
│  Stickers: Katowice 2014 Titan (Holo) [pos 1]  │
│                                                 │
│  Listing Price:    $80.00                       │
│  Estimated Value:  $120.00  (+50.0%)            │
│  Safe Exit:        $95.00   (+18.8%)            │
│                                                 │
│  ├── Base Price:   $45.00                       │
│  ├── Float Premium: +$30.00 (0.151 = top 2%)   │
│  └── Sticker Premium: +$45.00 (Kato14 Titan)   │
│                                                 │
│  Liquidity: GOOD (12/day, 8% spread)            │
│  Confidence: 82%                                │
│                                                 │
│  ✓ Underpriced by 33% vs estimated value        │
│  ✓ Safe exit above listing price                │
│  ✓ Good daily volume                            │
│                                                 │
╰─────────────────────────────────────────────────╯
```

## Quick Start

**Требования:** Python 3.12+

```bash
# Клонировать репозиторий
git clone https://github.com/VertaKhan/cs_gstack.git
cd cs_gstack

# Установить зависимости
pip install -e ".[dev]"

# Создать .env с API-ключами
cp .env.example .env
# Отредактировать .env — добавить CSFLOAT_API_KEY (обязательно) и STEAM_API_KEY (опционально)

# Запустить анализ
cs2 analyze "https://csfloat.com/item/..."
```

## Конфигурация

### .env — API-ключи

```env
CSFLOAT_API_KEY=your_key_here
STEAM_API_KEY=your_key_here    # опционально
```

### config.toml — пороги и настройки

Файл `config.toml` управляет порогами принятия решений, TTL кэша, множителями премиумов. Все значения имеют разумные дефолты — файл можно не создавать для начала работы.

Основные секции:
- **Thresholds** — минимальные пороги для premium-классификации (float percentile, стоимость стикера)
- **Cache TTL** — время жизни кэша по типам данных (цены: 1ч, листинги: 15мин, identity: 7д)
- **Liquidity** — пороги для HIGH/MEDIUM/LOW grade
- **Premium multipliers** — множители для расчета стикерных премиумов

## Использование

```bash
# Анализ по URL (CSFloat или Steam Market)
cs2 analyze "https://csfloat.com/item/..."
cs2 analyze "https://steamcommunity.com/market/listings/730/..."

# Ручное указание параметров (без Source Ingest)
cs2 analyze --weapon "AK-47" --skin "Redline" --quality FT --float 0.151
```

## Архитектура

Система построена как линейный pipeline из 6 модулей. Каждый модуль получает результат предыдущего, обрабатывает и передает дальше. Pydantic-модели служат контрактами между шагами. Все данные кэшируются в SQLite с TTL. Решения логируются для будущего обучения ML-моделей.

```
CLI Interface (Rich terminal output)
       │
       ▼
Pipeline Orchestrator (runs modules in strict sequence)
       │
       ▼
┌──────────────┐
│ 1. Source     │ ← Steam Market / CSFloat API
│    Ingest     │
└──────┬───────┘
       ▼
┌──────────────┐
│ 2. Item       │ ← Resolve canonical identity
│    Identity   │
└──────┬───────┘
       ▼
┌──────────────┐
│ 3. Exact      │ ← Float, stickers, pattern, StatTrak
│    Enrichment │
└──────┬───────┘
       ▼
┌──────────────┐
│ 4. Pricing    │ ← Base price + premium calculation
│    Engine     │
└──────┬───────┘
       ▼
┌──────────────┐
│ 5. Liquidity  │ ← Volume, spread, safe exit
│    Analyzer   │
└──────┬───────┘
       ▼
┌──────────────┐
│ 6. Decision   │ ← Buy/no-buy/review + confidence
│    Engine     │
└──────────────┘
       │
       ▼
SQLite Storage (item cache, price history, decision log)
```

## Разработка

```bash
# Запуск тестов
pytest

# Запуск с покрытием
pytest --cov=src/cs2

# Структура проекта
src/cs2/
├── cli.py             # CLI-интерфейс (Rich)
├── pipeline.py        # Оркестратор pipeline
├── config.py          # Загрузка TOML + .env
├── models/            # Pydantic-модели (items, pricing, liquidity, decision)
├── sources/           # API-клиенты (CSFloat, Steam)
├── engine/            # Модули анализа (identity, enrichment, pricing, liquidity, decision)
├── storage/           # SQLite (cache, logger)
└── data/              # Статические данные (special_patterns.json)
```

## License

MIT
