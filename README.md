# CS2 Skins Analysis System

Аналитическая CLI-система для анализа, мониторинга и управления портфелем скинов CS2: buy / no-buy / manual review.

## Что делает

Система автоматизирует сбор и анализ данных о конкретном лоте CS2. На вход — URL листинга или описание предмета. На выход — Decision Card с оценкой: стоит ли покупать, по какой цене можно безопасно выйти, и обоснование решения. Анализирует item identity, exact-параметры (float, stickers, pattern), рыночную цену, премиум за редкость и ликвидность.

Дополнительно: пакетный анализ из файла, сравнение лотов, история цен, отслеживание портфеля и мониторинг цен.

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
# Отредактировать .env — добавить CSFLOAT_API_KEY (обязательно), остальные опционально

# Запустить анализ
cs2 analyze "https://csfloat.com/item/..."
```

## Конфигурация

### .env — API-ключи

```env
CSFLOAT_API_KEY=your_key_here
STEAM_API_KEY=your_key_here       # опционально
SKINPORT_API_KEY=your_key_here    # опционально
DMARKET_API_KEY=your_key_here     # опционально
```

### config.toml — пороги и настройки

Файл `config.toml` управляет порогами принятия решений, TTL кэша, множителями премиумов. Все значения имеют разумные дефолты — файл можно не создавать для начала работы.

Основные секции:
- **Thresholds** — минимальные пороги для premium-классификации (float percentile, стоимость стикера)
- **Cache TTL** — время жизни кэша по типам данных (цены: 1ч, листинги: 15мин, identity: 7д)
- **Liquidity** — пороги для HIGH/MEDIUM/LOW grade
- **Premium multipliers** — множители для расчета стикерных премиумов
- **Sources** — включение/отключение дополнительных источников (`skinport_enabled`, `dmarket_enabled`)
- **Monitor** — настройки мониторинга цен (интервал, пороги уведомлений)

## Использование

### Анализ

```bash
# Анализ по URL (CSFloat или Steam Market)
cs2 analyze "https://csfloat.com/item/..."
cs2 analyze "https://steamcommunity.com/market/listings/730/..."

# Ручное указание параметров (без Source Ingest)
cs2 analyze --weapon "AK-47" --skin "Redline" --quality FT --float 0.151

# Пакетный анализ из файла (по одному URL на строку)
cs2 analyze urls.txt

# Экспорт результатов
cs2 analyze "https://csfloat.com/item/..." --format json -o result.json
cs2 analyze "https://csfloat.com/item/..." --format csv -o result.csv

# Офлайн-режим (только из кэша, без API-запросов)
cs2 analyze "https://csfloat.com/item/..." --offline
```

### Сравнение лотов

```bash
# Сравнение двух лотов side-by-side
cs2 compare "https://csfloat.com/item/..." "https://csfloat.com/item/..."
```

### История цен

```bash
# История цены предмета за последние 30 дней
cs2 history "AK-47 Redline FT" --days 30
```

### Портфель

```bash
# Добавить предмет в портфель
cs2 portfolio add "https://csfloat.com/item/..." --price 80.00

# Список предметов в портфеле
cs2 portfolio list

# Отметить продажу
cs2 portfolio sell <item_id> --price 95.00

# Текущая стоимость портфеля
cs2 portfolio value
```

### Мониторинг цен

```bash
# Мониторинг с фильтрами
cs2 monitor --weapon AK-47 --skin Redline --max-price 50 --min-float 0.15 --max-float 0.20
```

## Источники данных

- **CSFloat API** (основной) — листинги, данные предметов, история цен
- **Steam Community Market** — рыночные цены, объемы торгов
- **Skinport** — дополнительные цены (опционально, `skinport_enabled` в config.toml)
- **DMarket** — дополнительные цены (опционально, `dmarket_enabled` в config.toml)

Все источники кроме CSFloat опциональны. Система работает с любым набором доступных источников — graceful degradation при недоступности.

## Архитектура

Система построена как линейный pipeline из 6 модулей. Каждый модуль получает результат предыдущего, обрабатывает и передает дальше. Pydantic-модели служат контрактами между шагами. Все данные кэшируются в SQLite с TTL. Решения логируются для будущего обучения ML-моделей. Поддерживается офлайн-режим (работа только из кэша).

```
CLI Interface (Rich terminal output)
       │
       ▼
Pipeline Orchestrator (runs modules in strict sequence)
       │
       ▼
┌──────────────┐     ┌─────────────────────────────────────────┐
│ 1. Source     │ ←── │ CSFloat / Steam / Skinport / DMarket    │
│    Ingest     │     └─────────────────────────────────────────┘
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
       │
       ▼
Monitor (непрерывное отслеживание цен по фильтрам)
```

## Разработка

```bash
# Запуск тестов (222 теста)
pytest

# Запуск с покрытием
pytest --cov=src/cs2

# Структура проекта
src/cs2/
├── cli.py             # CLI-интерфейс (Rich)
├── pipeline.py        # Оркестратор pipeline
├── config.py          # Загрузка TOML + .env
├── models/            # Pydantic-модели (items, pricing, liquidity, decision)
├── sources/           # API-клиенты (CSFloat, Steam, Skinport, DMarket)
│   ├── csfloat.py
│   ├── steam.py
│   ├── skinport.py
│   └── dmarket.py
├── engine/            # Модули анализа (identity, enrichment, pricing, liquidity, decision, monitor)
│   └── monitor.py     # Мониторинг цен
├── storage/           # SQLite (cache, logger)
└── data/              # Статические данные (special_patterns.json)
```

## License

MIT
