# authors

Вход: jsonl с `ts` и `known_at`; allow-list в `infra/authors/sources.yaml`.
Выход: сырые `author_call` без `weight`.
Не делает: 20 выдуманных постов, TG, вес, копировать гуру.
Ключи не читает.
