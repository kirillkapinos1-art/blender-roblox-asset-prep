# Blender Game Asset Prep & Validator (Roblox / Unity / Unreal)

Python-инструмент и аддон для **Blender 3.6+ / 4.x**, который автоматически проверяет 3D-модели перед экспортом в **Roblox Studio**, **Unity** или **Unreal Engine**, исправляет типовые ошибки геометрии/трансформаций в 1 клик, рендерит превью-карточку и экспортирует готовый `.fbx` / `.glb`.

## Что проверяет и исправляет инструмент

| Проверка | Уровень | Авто-фикс (`--fix`) | Описание |
| :--- | :--- | :---: | :--- |
| Бюджет треугольников | `ERROR` / `WARNING` | — | Контроль лимита Roblox (`10 000` tris на MeshPart), Unity (`65 000`), Unreal (`100 000`) |
| Отрицательный масштаб (`det < 0`) | `ERROR` | ✅ | Выявляет зеркальные объекты с вывернутыми наизнанку нормалями |
| Неприменённые `Scale` / `Rotation` | `WARNING` | ✅ | Применяет `Apply Rotation & Scale` (`1, 1, 1` и `0°`) и пересчитывает нормали наружу |
| Пустые слоты материалов | `WARNING` | ✅ | Удаляет пустые material slots перед экспортом |
| Удалённый Origin | `WARNING` | ✅ | Предупреждает и опционально центрирует Pivot (`--center-origin`) |
| Некорректные имена объектов | `INFO` | ✅ | Приводит имена к чистому ASCII-формату (`MiG_29_Fuselage`) |
| Non-manifold рёбра и габариты | `WARNING` / `ERROR` | — | Диагностика негерметичной геометрии и превышения лимита размера (2048 studs/м) |

## Установка как аддон в Blender

1. Откройте Blender → **Edit → Preferences → Add-ons → Install...**
2. Выберите `addon_ui.py` (поместите папку `blender-roblox-asset-prep` в каталог аддонов или добавьте путь к скриптам).
3. Включите **Roblox & Game Engine Asset Prep**.
4. Откройте боковую панель в **3D Viewport (`N`) → вкладка `Asset Prep`**.

## Запуск из командной строки (Headless / CI)

```bash
blender --background scene.blend --python blender_prep.py -- \
  --target roblox \
  --fix \
  --center-origin \
  --export out/plane.fbx \
  --preview out/plane_preview.png \
  --report out/validation_report.json
```

Для Roblox экспортёр автоматически выставляет `global_scale = 0.01` и `apply_unit_scale = True`, чтобы габариты в Blender (`1 м`) корректно переносились в Roblox Studio.

## Тесты (без запуска Blender)

Логика валидации вынесена в независимый модуль `validator.py` и полностью покрыта тестами:

```bash
pytest
```
