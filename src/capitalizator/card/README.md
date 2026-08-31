# card

Вход: JSON черновика (5–7 claims) или (жест, n).
Выход: `CardDraft` / `require_card`; `FirstFact` с `size_mult=1`. n<20 или SILENCE → `shadow_gesture`.
Не делает: ордер, VERIFIED, «DEFEND → больше лотов», выдуманные 23 из 31.
Ключи не читает.
