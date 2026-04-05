# CS2 Skins Analysis System — Project Brief

## Что это
Персональная аналитическая система для анализа предметов и лотов CS2.
Не продукт на продажу. Внутренний инструмент для принятия решений о покупке скинов.

## Для кого
Только для меня. Один пользователь, power user, разбирается в CS2-экономике.

## Главная цель
Понять, какие предметы / лоты стоит покупать, а какие нет.
Итоговый output системы — решение: **buy / no-buy / manual review** с обоснованием.

## Что система должна учитывать
- **Item identity** — каноническая идентификация предмета (weapon, skin name, quality, StatTrak)
- **Exact-параметры экземпляра** — float value, wear, stickers (name, position, condition), pattern index, StatTrak kills
- **Базовая рыночная цена** — текущая market price для данного типа предмета
- **Premium за exact-характеристики** — надбавка/скидка за конкретный float, stickers, pattern
- **Ликвидность** — насколько быстро и по какой цене можно перепродать
- **Причины дисконта** — почему лот стоит дешевле рынка (если стоит)
- **Risk и аномалии** — подозрительные паттерны, фейковые скриншоты, манипуляции
- **Meta-demand и community signals** — тренды, хайп, стримеры, Reddit/YouTube mentions
- **Safe exit** — можно ли выйти без убытка если что-то пойдет не так

## Ключевые use cases
1. **Быстрая оценка лота** — вижу лот на площадке, хочу за 30 секунд понять: стоит или нет
2. **Глубокий анализ предмета** — полный разбор конкретного item с exact-параметрами
3. **Мониторинг выгодных лотов** — система сама находит underpriced lots по заданным критериям
4. **Portfolio tracking** — что у меня есть, сколько стоит, что лучше продать
5. **Market overview** — общая картина рынка, тренды, аномалии

## Основные компоненты
- Source Ingestion Layer — подключение к marketplace API, парсинг данных
- Item Identity Engine — каноническая идентификация предметов
- Exact Instance Enrichment — обогащение данными о конкретном экземпляре
- Pricing Engine — базовая цена + exact premium calculation
- Liquidity Analyzer — оценка ликвидности и safe exit
- Signal Aggregator — community signals, meta-demand, trend detection
- Risk Detector — аномалии, подозрительные паттерны
- Decision Engine — итоговый buy/no-buy/review с confidence score
- CLI Interface — Rich-based терминальный интерфейс

## Чем НЕ является (антискоуп)
- НЕ торговый бот (не совершает сделки автоматически)
- НЕ маркетплейс и НЕ агрегатор площадок
- НЕ ML-heavy система на старте (rule-based сначала, ML потом)
- НЕ real-time trading platform
- НЕ multi-user SaaS
- НЕ инвестиционный советник для других людей

## Ограничения
- Один пользователь, локальный запуск
- Постепенное наращивание источников (не все сразу)
- Rule-based logic сначала, ML позже
- Бюджет на API: разумный, не unlimited
- Система должна быть пригодна для постепенного расширения

## Источники данных (приоритет)
### Tier 1 — обязательны для MVP
- Steam Market (цены, листинги, история)
- Steam Inventory / inspect links (float, stickers, pattern)
- CSFloat API (exact item data, market data)

### Tier 2 — после MVP
- Skinport, DMarket, Buff163
- Price history aggregators
- Community APIs (csgostash, etc.)

### Tier 3 — опционально
- Reddit/Twitter sentiment
- YouTube/Twitch streamer mentions
- Trade-up calculator data
- Chinese market data (Buff, IGXE)
