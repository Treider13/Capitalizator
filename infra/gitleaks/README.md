# gitleaks

Вход: рабочее дерево.
Выход: отказ коммита, если в `src/` есть ключ.
Не делает: хранение настоящих ключей, allowlist для `src/`.

Проверка фикстуры (должна упасть):

```
gitleaks detect --no-git -s tests/fixtures/gitleaks/fake_secret.txt --exit-code
```

Фикстура в allowlist репо-скана, чтобы обычный коммит проходил. В `src/` allowlist нет.
