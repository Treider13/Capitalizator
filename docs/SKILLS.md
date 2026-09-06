# Запрошенные skills и границы применения

В этой сессии прочитаны применимые инструкции из всех пяти указанных источников.
Skills используются как правила проверки; их чтение не устанавливает биржевые
интеграции, не обучает новые модели и не доказывает доходность.

| Источник | Использование |
| --- | --- |
| [agiprolabs/claude-trading-skills](https://github.com/agiprolabs/claude-trading-skills) | position-sizing, risk-management, exit-strategies, slippage-modeling: лимиты сделки/портфеля и выход; strategy-framework: формальные правила; ohlcv-processing и feature-engineering: непрерывность и причинность; market-microstructure-traditional: стороны L2 и границы наблюдаемости; walk-forward-validation: границы OOS; trading-visualization: отображение данных/сделок |
| [DaviddTech/ai-trading-agent](https://github.com/DaviddTech/ai-trading-agent) | ai-hedge-fund, strategy-optimizer, position-optimizer, quant-mathematician, mean-reversion-engineer: baseline сохранён, изменения не объявлены прибылью без измерений; workflows создания Pine и оптимизации не запускались |
| [bybit-exchange/skills](https://github.com/bybit-exchange/skills) | bybit-trading: REST/WS, идентичность instrument, лимиты, реальные позиции/заявки; официальная API-спецификация выше предположений примеров |
| [Lumiwealth/lumibot](https://github.com/Lumiwealth/lumibot) | options-trading: current Greeks, позиции и факт исполнения; опционные заявки и Lumibot runtime не подключались |
| [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) | market-intel: freshness/read-only context; snapshot не выдаётся за live-сбор всех новостей, AI4Trade endpoints не интегрировались |

Bybit skill требует отдельный фоновый запрос manifest: он выполнен отдельным
агентом, завершился сетевым timeout; обновлений skill не было. Режимы проекта
Demo Trading/Live сохранены согласно требованиям пользователя; тестнет из
общего примера skill не подменяет Demo Trading.

Не запущены внешние Trader Dev backtests: соответствующих MCP-инструментов
в сессии нет, пользователь также запретил тесты. Не переносились DEX/AMM формулы
в CEX order book; wallet/MEV/LP/tax/prediction-market навыки не являются частью
этого Bybit USDT execution scope. Skills с описанием STUB не использовались
как готовые реализации. Предыдущий каталог 83 SKILL.md можно найти в истории PR #46;
это не заявление о повторном выполнении всех 83 workflows.

[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
просмотрен как внешний multi-agent research framework. Его автоматическое
включение в синхронный путь исполнения не обосновано; запрос пользователя
«просто взгляните» не превращён в непроверенную замену архитектуры.

Примеры из skills применяются критически: рекомендуемые случайные задержки,
martingale, полное Kelly, синтетическое заполнение пропусков или сторонние
проценты риска не заменяют действующие пользовательские правила.
