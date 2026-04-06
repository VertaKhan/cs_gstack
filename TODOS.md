# TODOS — CS2 Skins Analysis System

## Реализовано (из Deferred CEO Review 2026-04-05)

### [DONE] P2: Batch Analysis Mode
- `cs2 analyze urls.txt` — анализ списка лотов за один запуск
- Коммит: Add price history CLI and batch analysis mode

### [DONE] P2: Price Alert / Monitoring
- `cs2 monitor --weapon "AK-47" --skin "Redline" --max-price 50` — polling мониторинг
- Коммит: Add price monitoring

### [DONE] P3: JSON/CSV Export
- `cs2 analyze --format json/csv -o file` — экспорт результатов
- Коммит: Add JSON/CSV export and comparative analysis

### [DONE] P3: Comparative Analysis
- `cs2 compare <url1> <url2>` — side-by-side сравнение
- Коммит: Add JSON/CSV export and comparative analysis

### [DONE] P3: Offline Mode
- `cs2 analyze --offline` — работа только с кэшированными данными
- Коммит: Add Skinport/DMarket sources and offline mode

### [DONE] P2: Price History CLI
- `cs2 history "AK-47 Redline FT"` — отображение таблицы цен
- Коммит: Add price history CLI and batch analysis mode

### [DONE] P2: Additional Marketplaces
- Skinport, DMarket source adapters
- Коммит: Add Skinport/DMarket sources and offline mode

### [DONE] P2: Portfolio Tracking
- `cs2 portfolio add/list/sell/value` — отслеживание инвентаря
- Коммит: Add portfolio tracking

## Backlog (не реализовано)

### P1: ML Pricing Models
- **What:** Trained model для premium estimation вместо rule-based heuristics
- **Why:** Более точная оценка exact-premium items
- **Effort:** XL (human) → L (CC)
- **Status:** BLOCKED — нужны 500+ labeled decisions в decision_log
- **Depends on:** Накопление данных через использование системы. Каждый `cs2 analyze` логирует решение. После накопления достаточного объёма можно обучить модель.
