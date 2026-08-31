# authors

Вход: jsonl с `ts` и `known_at`; allow-list в `infra/authors/sources.yaml`.
Выход: сырые `author_call` без `weight`. `AuthorParse` принимает строку только если уже есть `claims`+`horizon`+`known_at`.
Не делает: 20/50 выдуманных постов, разбор свободного текста моделью, TG, вес, копировать гуру.
Ключи не читает.
