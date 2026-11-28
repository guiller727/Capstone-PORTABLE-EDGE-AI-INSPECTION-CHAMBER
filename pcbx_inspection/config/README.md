# config/  - settings changed from the GUI

`settings.json` (created by Settings > Inspection / Profile & model) overrides a
small, validated set of values from `config.py`:

| key | type | meaning |
|---|---|---|
| ACTIVE_PROFILE | text | folder in `models/` (e.g. `pcb_x`) |
| INSPECTION_MODE | `dual` / `flip` | two cameras one insertion / one camera + flip |
| FLIP_CAMERA | `upper` / `lower` | camera used in flip mode |
| ALLOW_FLIPPED_INSERTION | true/false | dual mode: accept a board inserted upside-down |
| LED_BRIGHTNESS | 0.05-1.0 | WS2812B brightness |
| LED_SETTLE_S | 0-3 | wait after switching the LED on |
| SAVE_RAW_IMAGES | true/false | keep raw camera images in logs/ |
| REQUIRE_DOOR_CLOSED | true/false | refuse to start with the drawer open |

Invalid entries are ignored (and logged) - a broken file cannot stop the program.
Delete `settings.json` to return to the `config.py` defaults.
Everything else (camera numbers, exposure, focus, GPIO pins) is edited in `config.py`.
