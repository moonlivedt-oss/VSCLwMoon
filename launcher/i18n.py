# -*- coding: utf-8 -*-
"""Лёгкая локализация без внешних зависимостей.

Подход-overlay: русский текст в коде — это и есть ключ. `_(текст)` возвращает
английский перевод, если выбран язык 'en' и перевод есть в таблице; иначе —
исходный русский. Так частичный перевод не ломает UI: что не покрыто —
остаётся читаемым по-русски, а не превращается в пустоту или id.

Язык — глобальное состояние процесса (по одному окну на запуск), меняется
кнопкой в шапке и запоминается в конфиге.
"""

from __future__ import annotations

_lang = "ru"

# ru -> en. Только осмысленные строки интерфейса; форматные {}-подстановки
# сохраняются в переводе на тех же местах.
TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        # шапка / общий чром
        "VS Code Launcher": "VS Code Launcher",
        "Открой редактор только с нужными стеками — остальные "
        "тяжёлые серверы не грузятся, память свободна.": "Open the editor with just the stacks you need — the other "
        "heavy servers stay unloaded and memory stays free.",
        "Не найден CLI VS Code (code.cmd). Добавь его в PATH.": "VS Code CLI (code.cmd) not found. Add it to PATH.",
        "Тёмная": "Dark",
        "Светлая": "Light",
        "тяжёлый": "heavy",
        "средний": "medium",
        "лёгкий": "light",
        "Переключить светлую/тёмную тему": "Toggle light/dark theme",
        "Язык": "Language",
        "Переключить язык интерфейса (RU/EN)": "Switch interface language (RU/EN)",
        "Обновить": "Refresh",
        "Обновить замер памяти запущенного VS Code": "Re-measure memory of running VS Code",
        "VS Code сейчас: замеряю…": "VS Code now: measuring…",
        "VS Code сейчас: {mb} МБ, {n} процессов": "VS Code now: {mb} MB, {n} processes",
        "VS Code сейчас не запущен": "VS Code is not running",
        "Суммарный working set всех процессов VS Code": "Total working set of all VS Code processes",
        # обновления (#8)
        "Доступна новая версия {ver} — открыть страницу релизов": "New version {ver} available — open releases page",
        "Показать": "Show",
        # пресеты
        "Пресет": "Preset",
        "Сохранить…": "Save…",
        "Удалить": "Delete",
        "Экспорт": "Export",
        "Импорт": "Import",
        "Экспортировать все пресеты в файл": "Export all presets to a file",
        "Импортировать пресеты из файла (объединяются с текущими)": "Import presets from a file (merged with current ones)",
        "— выбрать пресет —": "— choose preset —",
        # ярлык пресета (#5)
        "Ярлык": "Shortcut",
        "Создать .cmd-файл, открывающий VS Code с выбранным "
        "пресетом одним двойным кликом (без окна лаунчера)": "Create a .cmd file that opens VS Code with the chosen "
        "preset in one double-click (no launcher window)",
        "Сначала выбери пресет в списке — ярлык открывает VS Code "
        "с ним.": "Pick a preset in the list first — the shortcut opens VS Code with it.",
        "Сохранить ярлык": "Save shortcut",
        "Ярлык создан: {path}": "Shortcut created: {path}",
        "Ошибка": "Error",
        # секция стеков
        "СТЕКИ РАСШИРЕНИЙ": "EXTENSION STACKS",
        "Всё вкл": "All on",
        "Минимум": "Minimum",
        "Поиск стека или расширения…": "Search stack or extension…",
        "Фильтрует карточки по названию, заметке и id расширений. "
        "На выбор не влияет.": "Filters cards by title, note and extension ids. "
        "Does not change the selection.",
        # автодетект (#1)
        "Похоже на проект: {stacks}. Включить эти стеки?": "Looks like a {stacks} project. Enable these stacks?",
        "Включить": "Enable",
        "Скрыть": "Dismiss",
        "Включены стеки по типу проекта: {stacks}": "Enabled stacks by project type: {stacks}",
        # папка проекта
        "ПАПКА ПРОЕКТА (НЕОБЯЗАТЕЛЬНО)": "PROJECT FOLDER (OPTIONAL)",
        "путь к проекту, который открыть": "path to the project to open",
        "Обзор…": "Browse…",
        "— недавние папки —": "— recent folders —",
        "Выбери папку проекта": "Choose project folder",
        # параметры запуска
        "ПАРАМЕТРЫ ЗАПУСКА": "LAUNCH OPTIONS",
        "Закрыть VS Code перед стартом (чтобы память освободилась)": "Close VS Code before start (to actually free memory)",
        "   Мягко: дать VS Code сохранить (иначе принудительно)": "   Soft: let VS Code save (otherwise forced)",
        "Открыть в новом окне (--new-window)": "Open in a new window (--new-window)",
        "Без GPU-ускорения (--disable-gpu) — для слабых видеокарт": "No GPU acceleration (--disable-gpu) — for weak GPUs",
        "Голый режим: полностью без расширений (--disable-extensions)": "Bare mode: no extensions at all (--disable-extensions)",
        "Профиль": "Profile",
        "имя существующего профиля VS Code (необязательно)": "name of an existing VS Code profile (optional)",
        # настройка VS Code
        "НАСТРОЙКА VS CODE": "VS CODE SETUP",
        "Автонастройка settings.json": "Auto-configure settings.json",
        "Добавить рекомендованные настройки для установленных стеков": "Add recommended settings for installed stacks",
        # нижняя панель
        "Показать команду": "Show command",
        "Запустить VS Code": "Launch VS Code",
        "Что выключится": "What gets disabled",
        "Показать список расширений, которые будут выключены": "Show the list of extensions that will be disabled",
        "Здесь появится итоговая команда и статус запуска.": "The resulting command and launch status will appear here.",
        # summary
        "Голый режим: все расширения выключены (--disable-extensions).": "Bare mode: all extensions disabled (--disable-extensions).",
        "Список расширений не получен (нет CLI?).": "Extension list not available (no CLI?).",
        "Включено {en}, выключено {dis} — экономия ~{saved} МБ": "Enabled {en}, disabled {dis} — saving ~{saved} MB",
        " · замерено ранее: {mb} МБ": " · measured before: {mb} MB",
        " · реально сэкономлено ~{mb} МБ": " · actually saved ~{mb} MB",
        # диалог diff (#5)
        "Что будет выключено": "What will be disabled",
        "Выключается {n} расширений из невыбранных стеков. always_on и всё, "
        "чего нет в карте, останется включённым.": "{n} extensions from unselected stacks will be disabled. always_on "
        "and anything not in the map stays enabled.",
        "Ничего не выключается — всё установленное останется включённым.": "Nothing gets disabled — everything installed stays enabled.",
        "Копировать": "Copy",
        "Копировать список": "Copy list",
        "Закрыть": "Close",
        # понятность: карточки, легенда, окно «Подробнее»
        "Отметь стеки, нужные сегодня. Полоска слева — нагрузка на память: "
        "красная тяжёлый, жёлтая средний, зелёная лёгкий; чем тяжелее "
        "выключенный стек, тем больше экономия. Снятые галочки не удаляют "
        "расширения — они просто не грузятся в этот запуск. «Подробнее» — "
        "что внутри стека и установка/удаление.": "Check the stacks you need today. The left strip is memory load: "
        "red heavy, yellow medium, green light; the heavier a disabled "
        "stack, the bigger the saving. Unchecking does not remove "
        "extensions — they just don't load this launch. “Details” "
        "shows what's inside a stack and lets you install/remove.",
        "Галочка ВКЛючает этот стек в запускаемом VS Code. Снятая — расширения "
        "стека уйдут в --disable-extension (не удалятся, только не загрузятся "
        "в этой сессии).": "The checkbox turns this stack ON in the VS Code you launch. "
        "Unchecked — the stack's extensions go to --disable-extension "
        "(not removed, just not loaded this session).",
        "Что за расширения в стеке и зачем они: описание каждого, ссылка на "
        "маркетплейс, установка и удаление.": "What extensions the stack has and why: a description of each, a "
        "marketplace link, install and remove.",
        "Установлено {inst} из {total} расширений стека. Выключение стека "
        "коснётся только этих установленных.": "{inst} of {total} stack extensions installed. Disabling the stack "
        "affects only these installed ones.",
        "нет": "none",
        "Ни одно из {total} расширений стека не установлено.": "None of the {total} stack extensions are installed.",
        "Расширения этого стека не установлены — галочка ни на что не влияет. "
        "Поставить их можно в «Подробнее» → «Установить недостающие».": "This stack's extensions aren't installed — the checkbox has no "
        "effect. Install them via Details → Install missing.",
        "Тяжёлый стек: языковые серверы и анализаторы держат в памяти "
        "сотни МБ, даже когда вы их не трогаете. Наибольшая экономия — "
        "когда он выключен и сегодня не нужен.": "Heavy stack: language servers and analyzers keep hundreds of MB "
        "in memory even when idle. Biggest saving when it's off and not "
        "needed today.",
        "Средний стек: заметный, но умеренный расход памяти. Держите "
        "включённым для своих языков, выключайте на чужих проектах.": "Medium stack: noticeable but moderate memory use. Keep it on for "
        "your languages, off on other projects.",
        "Лёгкий стек: почти не влияет на память. Можно спокойно держать "
        "включённым — на экономию он влияет мало.": "Light stack: barely affects memory. Fine to keep on — it changes "
        "the saving very little.",
        "Ниже — расширения этого стека и что каждое делает. "
        "«Маркетплейс» открывает страницу расширения — прочитать, что это, "
        "перед установкой. «Установить» качает его из маркетплейса VS Code, "
        "«Удалить» стирает с диска (можно поставить заново). Отключение "
        "стека галочкой в главном окне ничего не удаляет — только не грузит "
        "в этой сессии.": "Below are the stack's extensions and what each does. "
        "“Marketplace” opens the extension's page — read what it "
        "is before installing. “Install” downloads it from the "
        "VS Code marketplace, “Remove” deletes it from disk (you "
        "can reinstall). Disabling the stack in the main window removes "
        "nothing — it just doesn't load this session.",
        "{total} расширений · установлено {n} · нагрузка {load} · "
        "выключение освобождает ~{mb} МБ": "{total} extensions · {n} installed · {load} load · disabling "
        "frees ~{mb} MB",
        "установлено": "installed",
        "нет в системе": "not installed",
        "Расширение установлено — грузится в VS Code, пока стек включён.": "Extension installed — loads in VS Code while the stack is on.",
        "Расширения нет на диске. «Установить» скачает его из маркетплейса.": "Not on disk. “Install” downloads it from the marketplace.",
        "Маркетплейс ↗": "Marketplace ↗",
        "Открыть страницу расширения в маркетплейсе VS Code — описание, автор, "
        "рейтинг и что оно запрашивает — перед установкой.": "Open the extension's VS Code marketplace page — description, "
        "author, rating and what it requests — before installing.",
        "Скачать и установить это расширение из маркетплейса VS Code.": "Download and install this extension from the VS Code marketplace.",
        "Удалить расширение с диска. Переустановить можно кнопкой «Установить».": "Remove the extension from disk. Reinstall with the Install button.",
        "Описание не задано — открой «Маркетплейс», чтобы прочитать, что "
        "делает расширение.": "No description set — open Marketplace to read what the extension "
        "does.",
        "Установить": "Install",
        "Подробнее": "Details",
        "Отметить все стеки (с учётом фильтра поиска)": "Check all stacks (respecting the search filter)",
        "Снять все галочки — останется только ядро (always_on) и незамапленные "
        "расширения": "Uncheck all — only the core (always_on) and unmapped extensions remain",
        # per-extension оверрайды (#9)
        "по стеку": "by stack",
        "всегда вкл": "always on",
        "всегда выкл": "always off",
        "Поведение этого расширения независимо от галочки стека": "Behavior of this extension regardless of the stack checkbox",
        # установка расширений: прогресс / отмена / сводка
        "Устанавливаю": "Installing",
        "Удаляю": "Removing",
        "установить": "install",
        "удалить": "remove",
        "Не удалось {verb}": "Could not {verb}",
        "Установлено": "Installed",
        "Удалено": "Removed",
        "{verb}: {ok}, ошибок: {err}": "{verb}: {ok}, errors: {err}",
        ", отменено: {rem}": ", cancelled: {rem}",
        "Готово с ошибками": "Finished with errors",
        "Отмена": "Cancel",
        "Отмена…": "Cancelling…",
        "Прервать пакетную установку (текущее расширение доустановится, следующие — нет)": "Stop the batch install (the current extension finishes, the rest do not)",
        # языки и инструменты (тулчейны)
        "Языки и инструменты…": "Languages & tools…",
        "Языки и инструменты": "Languages & tools",
        "Установить компиляторы и SDK (C/C++, Java, Go, Rust…) через winget и "
        "прописать их в PATH.": "Install compilers and SDKs (C/C++, Java, Go, Rust…) via winget and "
        "add them to PATH.",
        "Расширения VS Code добавляют подсветку и подсказки, но собирать и "
        "запускать код им нечем без самого тулчейна: компилятора C++, JDK, "
        "Go и т.д. Здесь можно поставить недостающее через winget — он сам "
        "скачает пакет и, где нужно, лаунчер пропишет его в PATH. После "
        "установки откройте новый терминал, чтобы PATH подхватился.": "VS Code extensions add highlighting and hints, but they can't build "
        "or run code without the toolchain itself: a C++ compiler, JDK, Go and "
        "so on. Here you can install what's missing via winget — it downloads "
        "the package and, where needed, the launcher adds it to PATH. After "
        "installing, open a new terminal so PATH is picked up.",
        "winget не найден. Установите «App Installer» из Microsoft Store "
        "(входит в состав Windows 10/11) — без него автоматическая "
        "установка недоступна.": "winget not found. Install “App Installer” from the Microsoft Store "
        "(shipped with Windows 10/11) — automatic installation needs it.",
        "установлено ✓ — перезапустите терминал": "installed ✓ — restart the terminal",
        "установлено{ver}": "installed{ver}",
        "Установить через winget?": "Install via winget?",
        "Будут скачаны и установлены пакеты:\n\n{names}\n\nЭто может "
        "занять несколько минут. Продолжить?": "These packages will be downloaded and installed:\n\n{names}\n\nThis "
        "may take a few minutes. Continue?",
        "Устанавливаю…": "Installing…",
        "Устанавливаю {i}/{n}…": "Installing {i}/{n}…",
        "Не удалось установить": "Installation failed",
        "Установлено: {ok}, ошибок: {err}": "Installed: {ok}, errors: {err}",
        "Установить всё ({n})": "Install all ({n})",
        " · доп.": " · optional",
        "winget install --id {id}": "winget install --id {id}",
        "winget upgrade --id {id}": "winget upgrade --id {id}",
        "winget uninstall --id {id}": "winget uninstall --id {id}",
        "Проверить": "Verify",
        "Проверка инструмента": "Tool check",
        "Запустить инструмент и показать его версию.": "Run the tool and show its version.",
        "Обновить через winget?": "Upgrade via winget?",
        "Удалить через winget?": "Uninstall via winget?",
        "Не удалось выполнить": "Operation failed",
        "Готово: {ok}, ошибок: {err}": "Done: {ok}, errors: {err}",
        "Пакеты:\n\n{names}\n\nЭто может занять несколько минут. Продолжить?": "Packages:\n\n{names}\n\nThis may take a few minutes. Continue?",
        "Настроить VS Code": "Configure VS Code",
        "Настройка VS Code": "VS Code setup",
        "Прописать путь к тулчейну (компилятор C++ / интерпретатор "
        "Python) в settings.json VS Code, чтобы IntelliSense и "
        "сборка/запуск заработали без ручной настройки.": "Write the toolchain path (C++ compiler / Python interpreter) into "
        "VS Code settings.json so IntelliSense and build/run work without "
        "manual setup.",
        "Даёт: {tools}": "Provides: {tools}",
        "Добавить в PATH": "Add to PATH",
        "Компилятор найден на диске — добавить его каталог в PATH без повторной "
        "загрузки.": "Compiler found on disk — add its folder to PATH without downloading again.",
        "Поставить": "Install",
        "Для этого проекта не хватает инструментов: {tools}. Установить "
        "компилятор/SDK?": "This project is missing tools: {tools}. Install the compiler/SDK?",
        # доктор окружения, чистка PATH, JAVA_HOME (#8, #3, #4)
        "Проверить окружение": "Check environment",
        "Отчёт: установленные тулчейны и версии, здоровье "
        "PATH (дубли/мёртвые записи), JAVA_HOME.": "Report: installed toolchains and versions, PATH health "
        "(duplicates/dead entries), JAVA_HOME.",
        "Проверяю окружение…": "Checking environment…",
        "Проверка окружения": "Environment check",
        "Не удалось собрать отчёт.": "Could not build the report.",
        "winget: {v}": "winget: {v}",
        "не найден": "not found",
        "Установленные тулчейны ({n}):": "Installed toolchains ({n}):",
        "JAVA_HOME не задан.": "JAVA_HOME is not set.",
        "PATH: {n} записей, длина {l} символов": "PATH: {n} entries, {l} characters long",
        "  Ваш PATH: дублей {d}, мёртвых {m}": "  Your PATH: {d} duplicates, {m} dead",
        "  Системный PATH: дублей {d}, мёртвых {m}  (нужны права админа)": "  System PATH: {d} duplicates, {m} dead  (requires admin rights)",
        "  PATH в порядке: дублей и мёртвых записей не найдено.": "  PATH is clean: no duplicates or dead entries found.",
        "Почистить свой PATH": "Clean your PATH",
        "Почистить системный PATH": "Clean system PATH",
        "Убрать дубли и мёртвые записи из пользовательского PATH (с бэкапом).": "Remove duplicates and dead entries from the user PATH (with a backup).",
        "Убрать дубли и мёртвые записи из системного PATH. "
        "Нужны права администратора — появится запрос UAC.": "Remove duplicates and dead entries from the system PATH. "
        "Requires admin rights — a UAC prompt will appear.",
        "Чистка PATH": "PATH cleanup",
        "Почистить {scope} PATH?": "Clean the {scope} PATH?",
        "системный": "system",
        "ваш": "user",
        "Будут убраны записи (с бэкапом в файл):\n\n{listing}{extra}\n\n"
        "Продолжить?": "These entries will be removed (with a backup file):\n\n"
        "{listing}{extra}\n\nContinue?",
        "\n\nПотребуются права администратора (появится запрос UAC).": "\n\nAdmin rights are required (a UAC prompt will appear).",
        "Исправить JAVA_HOME": "Fix JAVA_HOME",
        "Найти установленный JDK и прописать JAVA_HOME.": "Find the installed JDK and set JAVA_HOME.",
        "JAVA_HOME": "JAVA_HOME",
        # обновления тулчейнов (#5)
        "Проверить обновления": "Check updates",
        "Спросить winget, для каких тулчейнов доступно обновление, и отметить их.": "Ask winget which toolchains have updates and mark them.",
        "Проверяю обновления…": "Checking updates…",
        "Не удалось проверить обновления": "Could not check updates",
        "доступно обновление ↑": "update available ↑",
        "Доступно обновлений: {n}": "Updates available: {n}",
        # установка с правами администратора (#10)
        "Установка с правами администратора…": "Installing with administrator rights…",
        "Нужны права администратора": "Administrator rights required",
        "Повторить установку с правами администратора?": "Retry the installation with administrator rights?",
        "Готово": "Done",
        # редизайн: hero-панель экономии, чипы, адаптивная сетка
        "МБ": "MB",
        "ЭКОНОМИЯ ПАМЯТИ": "MEMORY SAVED",
        "выбрано {n} / {m}": "{n} / {m} selected",
        "Сколько стеков сейчас отмечено из всех.": "How many stacks are checked out of all.",
        "включено {en}": "{en} on",
        "выключится {dis}": "{dis} off",
        "показано {n} из {total}": "showing {n} of {total}",
        "ничего не найдено": "nothing found",
        "Запустить · −{dis}": "Launch · −{dis}",
        "Запустить (голый режим)": "Launch (bare mode)",
        "голый режим": "bare mode",
        "все расширения выключены": "all extensions off",
        "нет списка расширений": "no extension list",
        "считаю расширения…": "counting extensions…",
        "замерено {mb} МБ": "measured {mb} MB",
        "реально · оценка ~{saved}": "actual · est. ~{saved}",
        # сегментированный фильтр установленных/неустановленных
        "Все": "All",
        "Установленные": "Installed",
        "Не установленные": "Not installed",
        "Все ({n})": "All ({n})",
        "Установленные ({n})": "Installed ({n})",
        "Не установленные ({n})": "Not installed ({n})",
    }
}


def set_language(lang: str) -> None:
    global _lang
    _lang = "en" if str(lang).lower().startswith("en") else "ru"


def get_language() -> str:
    return _lang


def _(text: str) -> str:
    """Перевод строки на текущий язык. Нет перевода — возвращаем исходник."""
    if _lang == "ru":
        return text
    return TRANSLATIONS.get(_lang, {}).get(text, text)
