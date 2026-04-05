# TODOS — CS2 Skins Analysis System

## Deferred from CEO Review (2026-04-05)

### P2: Batch Analysis Mode
- **What:** `cs2 analyze urls.txt` — анализ списка лотов за один запуск
- **Why:** Ускоряет workflow при просмотре множества лотов
- **Effort:** S (human) → S (CC)
- **Depends on:** Stable single-item pipeline

### P2: Price Alert / Monitoring
- **What:** `cs2 monitor --criteria "weapon=AK-47 skin=Redline max_price=50"` — фоновый мониторинг
- **Why:** Автоматический поиск выгодных лотов без ручного запуска
- **Effort:** L (human) → M (CC)
- **Depends on:** Stable pipeline + async scheduler

### P3: JSON/CSV Export
- **What:** `cs2 analyze --format json/csv` — экспорт результатов
- **Why:** Интеграция с внешними инструментами, spreadsheets
- **Effort:** S (human) → S (CC)
- **Depends on:** Stable output format

### P3: Comparative Analysis
- **What:** `cs2 compare <lot1> <lot2>` — side-by-side сравнение двух лотов
- **Why:** Помогает выбрать лучший из нескольких вариантов
- **Effort:** M (human) → S (CC)
- **Depends on:** Stable single-item pipeline

### P3: Offline Mode
- **What:** Полноценная работа только с кэшированными данными
- **Why:** Анализ без интернета, при rate limit'ах
- **Effort:** S (human) → S (CC)
- **Depends on:** Mature cache layer

### P2: Price History CLI
- **What:** `cs2 history "AK-47 Redline FT"` — отображение графика цен
- **Why:** Контекст для принятия решения (тренд вверх/вниз)
- **Effort:** M (human) → S (CC)
- **Depends on:** Price history data in SQLite (already collected by pricing engine)

### P2: Additional Marketplaces
- **What:** Skinport, DMarket, Buff163 source adapters
- **Why:** Больше данных = точнее pricing и liquidity
- **Effort:** L (human) → M (CC) per source
- **Depends on:** Adapter pattern in source ingest

### P1: ML Pricing Models
- **What:** Trained model для premium estimation вместо rule-based heuristics
- **Why:** Более точная оценка exact-premium items
- **Effort:** XL (human) → L (CC)
- **Depends on:** 500+ labeled decisions in decision_log

### P2: Portfolio Tracking
- **What:** `cs2 portfolio add/list/value` — отслеживание инвентаря
- **Why:** Общая картина позиции, P&L tracking
- **Effort:** M (human) → S (CC)
- **Depends on:** Stable pricing engine
