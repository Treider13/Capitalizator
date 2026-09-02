# card

Вход: JSON черновика (5–7 claims) или (жест, n). `CardLive` — выход контура B (вердикт, макро, метки, volume_snapshot).
Выход: `CardDraft` / `require_card`; `FirstFact` с `size_mult=1`. n<20 или SILENCE → `shadow_gesture`.
Не делает: ордер, VERIFIED в JSON файла, «DEFEND → больше лотов», выдуманные 23 из 31. VERIFIED только после bind. Telegram нет.
Ключи не читает.
