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
        "Языки и инструменты…": "Languages and tools…",
        "Языки и инструменты": "Languages and tools",
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
        # 1.4: честный замер расширений (code --status)
        "Замерить расширения": "Measure extensions",
        "Замеряю…": "Measuring…",
        "Замер расширений": "Extension memory",
        "Спросить у запущенного VS Code (code --status), сколько "
        "памяти едят именно расширения, а сколько — сам редактор. "
        "Это факт, а не оценка по таблице весов.": "Ask the running VS Code (code --status) how much memory "
        "the extensions use and how much the editor itself does. "
        "A fact, not a guess from a weight table.",
        "VS Code не отвечает на --status. Он запущен? Замер работает "
        "только при открытом редакторе.": "VS Code does not answer --status. Is it running? The measurement "
        "needs an open editor.",
        "Всего процессы VS Code: {mb} МБ": "VS Code processes in total: {mb} MB",
        "Ядро": "Core",
        "стартует сразу": "starts at launch",
        "Расширение активируется при каждом запуске VS Code "
        "(«*» или onStartupFinished), а не когда открыт файл его "
        "языка. Такие держат память даже там, где не нужны, — "
        "их выгоднее всего выключать стеком.": "The extension activates on every VS Code launch ('*' or "
        "onStartupFinished), not when a file of its language is opened. "
        "Such extensions hold memory even where they are not needed — "
        "they pay off most when their stack is off.",
        # --- уборка -------------------------------------------------------
        "Уборка…": "Clean up…",
        "Найти, что VS Code накопил на диске: копии установщиков, "
        "данные удалённых проектов, кэши, старые логи и версии "
        "расширений. Удаление — в Корзину.": "Find what VS Code has piled up on disk: installer copies, data of "
        "deleted projects, caches, old logs and extension versions. "
        "Deletion goes to the Recycle Bin.",
        "Уборка VS Code": "VS Code clean-up",
        "Что VS Code накопил и сам не чистит: копии установщиков, данные "
        "удалённых проектов, кэши движка, старые логи и версии расширений. "
        "Всё это пересоздаётся при необходимости. Удаление — в Корзину, "
        "только при закрытом VS Code.": "What VS Code accumulates and never cleans itself: installer copies, "
        "data of deleted projects, engine caches, old logs and extension "
        "versions. All of it is recreated when needed. Deletion goes to the "
        "Recycle Bin and only while VS Code is closed.",
        "Что": "What",
        "Размер": "Size",
        "Ищу…": "Scanning…",
        "Пересканировать": "Rescan",
        "В Корзину": "To Recycle Bin",
        "Не найдена папка данных VS Code (%APPDATA%).": "VS Code data folder not found (%APPDATA%).",
        "Ошибка поиска: {err}": "Scan error: {err}",
        "Убирать нечего — всё чисто.": "Nothing to clean — all tidy.",
        "Выбрано: {n} · освободится {size}": "Selected: {n} · frees {size}",
        "VS Code запущен. Закройте его: кэши открытого редактора заняты "
        "и удалятся не полностью.": "VS Code is running. Close it: the open editor holds its caches "
        "and they would be removed only partially.",
        "Переместить в Корзину {n} элементов ({size})?": "Move {n} items ({size}) to the Recycle Bin?",
        "Перемещаю в Корзину…": "Moving to the Recycle Bin…",
        "Готово: {size} в Корзине.": "Done: {size} in the Recycle Bin.",
        "Не всё удалось убрать: {err}": "Not everything was removed: {err}",
        "Копии установщиков расширений (CachedExtensionVSIXs)": "Extension installer copies (CachedExtensionVSIXs)",
        "Данные удалённых проектов (workspaceStorage)": "Data of deleted projects (workspaceStorage)",
        "Кэш прошлых версий VS Code (CachedData)": "Cache of previous VS Code versions (CachedData)",
        "Кэши движка (Cache, GPUCache…)": "Engine caches (Cache, GPUCache…)",
        "Логи прошлых сеансов": "Logs of past sessions",
        "Старые версии расширений": "Old extension versions",
        "Дерево процессов VS Code: {mb} МБ": "VS Code process tree: {mb} MB",
        "  расширения и их языковые серверы: {mb} МБ": "  extensions and their language servers: {mb} MB",
        "  сам редактор (окно, хост расширений, GPU): {mb} МБ": "  the editor itself (window, extension host, GPU): {mb} MB",
        "Память по стекам (отдельные процессы расширений):": "Memory by stack (separate extension processes):",
        "По расширениям:": "By extension:",
        "Не входит в замер (терминал и запущенное в нём):": "Not counted (terminal and what runs in it):",
        "Ответ code --status: всего {mb} МБ": "code --status answer: {mb} MB in total",
        "Больше всех в отдельных процессах держит «{title}»: "
        "{mb} МБ. Эта память уходит, когда стек выключен.": "The biggest holder in separate processes is '{title}': "
        "{mb} MB. This memory is freed when the stack is off.",
        "  из них расширения (extensionHost и языковые серверы): {mb} МБ "
        "({share}%)": "  of that, extensions (extensionHost and language servers): {mb} MB "
        "({share}%)",
        "  сам редактор (окно, GPU, терминал, поиск): {mb} МБ": "  the editor itself (window, GPU, terminal, search): {mb} MB",
        "Процессы:": "Processes:",
        "Размер стеков на диске (установленное):": "Stack size on disk (installed):",
        "Расширения занимают {mb} МБ — это {share}% памяти VS Code. "
        "Именно эта часть и уходит, когда стек выключен.": "Extensions take {mb} MB — {share}% of what VS Code uses. "
        "That is exactly the part that goes away when a stack is off.",
        # 1.4: реальный вес стека на диске
        "{mb} МБ": "{mb} MB",
        "Установленные расширения этого стека занимают "
        "{mb} МБ на диске.": "Installed extensions of this stack take {mb} MB on disk.",
        "включён": "on",
        "выключен": "off",
        "установлено {inst} из {total}": "{inst} of {total} installed",
        "{mb} МБ на диске": "{mb} MB on disk",
        # 1.4: откуда взялось число экономии
        "Ничего не выключается — экономить нечего.": "Nothing gets disabled — nothing to save.",
        "Все {n} выключаемых стеков посчитаны по твоим прошлым "
        "замерам памяти — это не прикидка.": "All {n} stacks being disabled are counted from your own past "
        "memory measurements — this is not an estimate.",
        "По твоим замерам посчитано {n} стеков из {total}, "
        "остальные — по таблице нагрузки. Чем чаще запускаешь "
        "разные наборы, тем точнее число.": "{n} of {total} stacks are counted from your own measurements, "
        "the rest from the weight table. The more different sets you "
        "launch, the more accurate the number gets.",
        "Пока это прикидка по таблице нагрузки стеков. После "
        "нескольких запусков разных наборов лаунчер посчитает "
        "цену каждого стека по фактическим замерам.": "For now this is an estimate from the stack weight table. After a "
        "few launches with different sets the launcher will compute each "
        "stack's real cost from actual measurements.",
        # 1.4: исключения по расширениям
        "Исключения по расширениям": "Per-extension exceptions",
        "Исключения: {n}": "Exceptions: {n}",
        "Расширения с личным режимом «всегда включать/выключать» — "
        "показать список и снять лишние.": "Extensions with a personal always-on/always-off mode — "
        "see the list and drop the ones you no longer need.",
        "Эти расширения игнорируют решение своего стека. Исключение "
        "сильнее галочки: «всегда включать» переживёт выключенный стек, "
        "«всегда выключать» — включённый.": "These extensions ignore their stack's decision. An exception beats "
        "the switch: always-on survives a disabled stack, always-off "
        "survives an enabled one.",
        "Исключений нет. Поставить их можно в «Подробнее» у любого "
        "стека — там у каждого расширения есть выбор режима.": "No exceptions yet. You can set them in any stack's Details — every "
        "extension there has a mode selector.",
        "всегда включено": "always on",
        "всегда выключено": "always off",
        "Убрать": "Remove",
        "Убрать все": "Remove all",
        # 1.4: рабочая область и перетаскивание
        "Рабочая область…": "Workspace…",
        "Выбери файл рабочей области": "Choose a workspace file",
        "Открыть файл .code-workspace — многопапочный проект "
        "VS Code.": "Open a .code-workspace file — a multi-root VS Code project.",
        "Выбрать папку проекта. Папку можно и просто "
        "перетащить в окно.": "Pick the project folder. You can also just drag a folder onto the window.",
        "путь к проекту или .code-workspace — можно перетащить сюда": "path to the project or a .code-workspace — you can drop it here",
        "Папка проекта: {folder}": "Project folder: {folder}",
        # 1.4: значок в трее
        "Значок в трее: запускать пресеты без окна": "Tray icon: launch presets without the window",
        "Правый клик по значку — список пресетов; выбрал, и VS Code "
        "открылся нужным набором. Окно нужно только когда набор "
        "действительно меняешь. Применится после перезапуска лаунчера.": "Right-click the icon for the preset list; pick one and VS Code opens "
        "with that set. The window is only needed when you actually change "
        "the set. Takes effect after restarting the launcher.",
        "   Крестик сворачивает в трей, а не закрывает": "   The close button minimises to tray instead of quitting",
        "Лаунчер останется в трее и будет открываться мгновенно. "
        "Выйти совсем — «Выход» в меню значка.": "The launcher stays in the tray and opens instantly. "
        "To quit for real use Quit in the icon menu.",
        "Лаунчер свёрнут в трей. Пресеты — правым кликом по значку.": "The launcher is in the tray. Presets: right-click the icon.",
        "Показать окно": "Show window",
        "Запустить пресет:": "Launch preset:",
        "Пресетов пока нет": "No presets yet",
        "Выход": "Quit",
        "{name} — стеков: {n}": "{name} — stacks: {n}",
        "{name} — голый режим": "{name} — bare mode",
        # 1.4: честное подтверждение закрытия
        "Закрыть VS Code?": "Close VS Code?",
        "Сейчас VS Code получит обычный запрос на закрытие — он "
        "сам спросит про несохранённые файлы. Когда закроется, "
        "откроется новое окно с выбранным набором.\n\n"
        "Продолжить?": "VS Code will get a normal close request and will ask about unsaved "
        "files itself. Once it closes, a new window opens with the "
        "selected set.\n\nContinue?",
        "Сейчас будут ПРИНУДИТЕЛЬНО закрыты все окна VS Code, "
        "затем откроется новое с выбранным набором.\n\n"
        "Сохранил несохранённые файлы? Продолжить?": "All VS Code windows will be FORCE-closed, then a new one opens with "
        "the selected set.\n\nHave you saved your files? Continue?",
        "Приватная память всех процессов VS Code "
        "(неразделяемая — именно она освобождается при закрытии). "
        "Замер нативный, без запуска PowerShell.": "Private memory of all VS Code processes (non-shared — exactly what "
        "is released on close). Measured natively, no PowerShell.",
        "Все ({n})": "All ({n})",
        "Установленные ({n})": "Installed ({n})",
        "Не установленные ({n})": "Not installed ({n})",
        # --- добавлено в 1.4: остаток интерфейса, который был только по-русски
        "Авто (автопоиск)": "Auto (detect)",
        "Обзор… (указать путь вручную)": "Browse… (set the path manually)",
        "Удаляю…": "Removing…",
        "нет CLI VS Code — установка/удаление недоступны": "no VS Code CLI — install/remove unavailable",
        "Установка VS Code": "VS Code installation",
        "Скачиваю обновление…": "Downloading update…",
        "VS Code…": "VS Code…",
        "Выбрать установку VS Code (стабильная/Insiders/портативная) — если автопоиск нашёл не ту или не нашёл вовсе.": "Pick the VS Code installation (stable/Insiders/portable) — if autodetect found the wrong one or none at all.",
        "Профиль…": "Profile…",
        "Экспортировать текущий выбор стеков как нативный профиль VS Code (.code-profile). Импортируется через «Profiles: Import Profile…» — постоянный профиль ровно с включёнными расширениями.": "Export the current stack selection as a native VS Code profile (.code-profile). Import it via 'Profiles: Import Profile…' — a permanent profile with exactly the enabled extensions.",
        "Установленные расширения, которых нет в data/categories.json — лаунчер всегда оставляет их включёнными": "Installed extensions that are missing from data/categories.json — the launcher always keeps them enabled",
        "Автоматически разложить незнакомые расширения по стекам (по их манифесту). Ничего не навязывается — ты подтверждаешь раскладку; categories.json не меняется.": "Sort unknown extensions into stacks automatically, by their manifest. Nothing is forced — you confirm the mapping; categories.json is not changed.",
        "всегда для этой папки": "always for this folder",
        "Запоминать набор для этой папки и включать его при выборе без подсказки": "Remember this set for the folder and turn it on when the folder is picked, without asking",
        "Пошлёт окну обычный запрос на закрытие — VS Code сам спросит про несохранённые файлы. Лаунчер подождёт, пока редактор закроется, и только потом стартует новый. Если оставить открытым диалог сохранения, запуск отменится (ничего не потеряется). Выкл — жёсткое закрытие (/F): быстро и надёжно освобождает память, но несохранённое теряется.": "Sends the window a normal close request — VS Code asks about unsaved files itself. The launcher waits for the editor to quit and only then starts a new one. If a save dialog is left open, the launch is cancelled (nothing is lost). Off — hard close (/F): frees memory fast and reliably, but unsaved work is lost.",
        "Отключает аппаратное ускорение отрисовки. Иногда лечит артефакты/лаги на старых GPU и экономит немного памяти.": "Turns off hardware-accelerated rendering. Sometimes cures artifacts and lag on old GPUs, and saves a little memory.",
        "Отключит ВСЕ расширения, включая ядро — максимальная скорость. Галочки стеков при этом игнорируются.": "Disables ALL extensions, the core ones included — maximum speed. Stack checkboxes are ignored.",
        "Откроет окно с этим профилем (--profile). Профиль нужно заранее создать в VS Code (шестерёнка → Profiles). Пусто — профиль по умолчанию.": "Opens the window with this profile (--profile). Create the profile in VS Code first (gear → Profiles). Empty — the default profile.",
        "Разложить по стекам": "Sort into stacks",
        "Принять отмеченные": "Apply checked",
        "Дубли в categories.json": "Duplicates in categories.json",
        "Расширения в нескольких стеках": "Extensions in several stacks",
        "Расширения не в карте": "Extensions not in the map",
        "Не в data/categories.json": "Not in data/categories.json",
        "Нет рекомендаций для установленных стеков.": "No recommendations for the installed stacks.",
        "Автонастройка VS Code": "VS Code auto-setup",
        "Рекомендованные настройки": "Recommended settings",
        "Применить (бэкап)": "Apply (with backup)",
        "VS Code workspace (*.code-workspace);;Все файлы (*.*)": "VS Code workspace (*.code-workspace);;All files (*.*)",
        "Прошу VS Code закрыться (ответь на запрос сохранения)…": "Asking VS Code to close (answer the save prompt)…",
        "Сохранить пресет": "Save preset",
        "Имя пресета:": "Preset name:",
        "Экспорт пресетов": "Export presets",
        "Импорт пресетов": "Import presets",
        "Экспорт профиля VS Code": "Export VS Code profile",
        "Стек: {title}": "Stack: {title}",
        "Выбери code.cmd или Code.exe": "Pick code.cmd or Code.exe",
        "VS Code CLI (code.cmd code-insiders.cmd Code.exe);;Все файлы (*.*)": "VS Code CLI (code.cmd code-insiders.cmd Code.exe);;All files (*.*)",
        "Обновление": "Update",
        "Авто-набор для этой папки включён.": "Auto set for this folder is on.",
        "Пропишет базовые настройки для установленных стеков (формат при сохранении и т.п.). Существующие настройки не трогаются, перед записью делается бэкап settings.json.": "Writes the basic settings for the installed stacks (format on save and the like). Existing settings are left alone, and settings.json is backed up first.",
        "Разложить по стекам (авто)": "Sort into stacks (auto)",
        "Раскладка": "Mapping",
        "Незнакомых расширений нет.": "There are no unknown extensions.",
        "Не удалось уверенно определить стек ни для одного незнакомого расширения. Разложи вручную в data/categories.json.": "Could not confidently determine a stack for any unknown extension. Sort them by hand in data/categories.json.",
        "Каждое расширение попадёт только в один стек — тот, что стоит последним в data/categories.json. Убери дубли, чтобы галочка работала предсказуемо.": "Each extension goes into one stack only — the one listed last in data/categories.json. Remove the duplicates so the checkbox behaves predictably.",
        "Автонастройка": "Auto-setup",
        "Не найден CLI VS Code (code.cmd).": "VS Code CLI (code.cmd) not found.",
        "Папка не найдена": "Folder not found",
        "Пресетов пока нет.": "No presets yet.",
        "Импорт: в файле нет пресетов.": "Import: the file has no presets.",
        "Импортировано пресетов: {n}": "Presets imported: {n}",
        "Профиль VS Code": "VS Code profile",
        "Список расширений ещё не загружен.": "The extension list has not loaded yet.",
        "Установить недостающие ({n})": "Install missing ({n})",
        "Скачать и установить?": "Download and install?",
        "Удалить расширение:\n\n{ext}\n\nОно будет удалено с диска. Переустановить можно кнопкой «Установить».": "Remove the extension:\n\n{ext}\n\nIt will be deleted from disk. You can reinstall it with 'Install'.",
        "Удалить расширение?": "Remove the extension?",
        "VS Code Launcher {ver} — переключатель нагрузки": "VS Code Launcher {ver} — extension load switcher",
        "Сейчас: {cur}\n\nВыбери установку:": "Current: {cur}\n\nPick an installation:",
        "VS Code CLI: {cli}": "VS Code CLI: {cli}",
        "Доступна новая версия {ver} — скачать и установить": "Version {ver} is available — download and install",
        "Перезапустить сейчас, чтобы применить обновление?": "Restart now to apply the update?",
        "Не удалось получить список расширений.": "Could not get the extension list.",
        "Закроет все окна VS Code ({exe}) перед стартом. Запускай этот тул НЕ из терминала VS Code.": "Closes every VS Code window ({exe}) before starting. Do NOT run this tool from the VS Code terminal.",
        "Не в карте: {n} — показать": "Not in the map: {n} — show",
        "Разложено расширений: {n}": "Extensions sorted: {n}",
        "Применить настройки?": "Apply settings?",
        "Добавить недостающие рекомендованные ключи в settings.json?\nСуществующие настройки не изменятся, будет сделан бэкап.": "Add the missing recommended keys to settings.json?\nExisting settings stay as they are, and a backup will be made.",
        "Эквивалент для cmd (сам лаунчер запускает Code.exe напрямую, без оболочки):": "The cmd equivalent (the launcher itself starts Code.exe directly, without a shell):",
        "Запуск: голый режим (все расширения выкл). OK.": "Launch: bare mode (all extensions off). OK.",
        "Закрываю VS Code…": "Closing VS Code…",
        "VS Code закрыт. Запускаю…": "VS Code is closed. Starting…",
        "VS Code всё ещё открыт — запуск отменён. Закрой окна (или ответь на запрос сохранения) и нажми «Запустить» снова.": "VS Code is still open — launch cancelled. Close the windows (or answer the save prompt) and press 'Launch' again.",
        "Ошибка экспорта": "Export error",
        "ожидается объект вида имя: [категории]": "expected an object of the form name: [categories]",
        "Ошибка импорта": "Import error",
        " (пропущено неизвестных ключей категорий: {n} — {sample}{tail})": " (unknown category keys skipped: {n} — {sample}{tail})",
        "Ошибка экспорта профиля": "Profile export error",
        "Установить расширение:\n\n{ext}\n\nОно будет скачано из маркетплейса VS Code.": "Install the extension:\n\n{ext}\n\nIt will be downloaded from the VS Code marketplace.",
        "Установить {n} недостающих расширений стека «{title}»?\n\nВсе они будут скачаны из маркетплейса.": "Install {n} missing extensions of the '{title}' stack?\n\nAll of them will be downloaded from the marketplace.",
        "Продолжить?": "Continue?",
        "Скачать и установить {ver}? Лаунчер закроется и обновится сам.": "Download and install {ver}? The launcher will close and update itself.",
        "Скачиваю обновление… {pct}%": "Downloading update… {pct}%",
        "Скачиваю обновление… {mb} МБ": "Downloading update… {mb} MB",
        "Авто-набор для папки: {stacks}": "Auto set for the folder: {stacks}",
        "Расширений: {n} (источник: {src}).": "Extensions: {n} (source: {src}).",
        "Обновляю": "Updating",
        "Версия для установки/обновления": "Version to install/update",
        "{n} расширений нет в карте категорий, поэтому лаунчер всегда оставляет их включёнными. Добавь их в нужную категорию в data/categories.json, чтобы управлять ими из окна.": "{n} extensions are missing from the category map, so the launcher always keeps them enabled. Add them to the right category in data/categories.json to control them from this window.",
        "Стеки: {stacks}. «Применить» добавит только НЕДОСТАЮЩИЕ ключи в settings.json и сделает бэкап; существующие настройки не меняются.\nФайл: {path}": "Stacks: {stacks}. 'Apply' adds only the MISSING keys to settings.json and makes a backup; existing settings are not changed.\nFile: {path}",
        "Путь не существует:\n{folder}\n\nОткрыть VS Code без папки?": "The path does not exist:\n{folder}\n\nOpen VS Code without a folder?",
        "Ошибка запуска": "Launch error",
        "Экспортировано пресетов: {n} → {path}": "Presets exported: {n} → {path}",
        "Профиль VS Code сохранён ({n} расш.): {path}": "VS Code profile saved ({n} ext.): {path}",
        "Готово. В VS Code открой палитру команд и выполни «Profiles: Import Profile…», затем выбери этот файл.\n\nРасширений в профиле: {n}": "Done. In VS Code open the command palette, run 'Profiles: Import Profile…' and pick this file.\n\nExtensions in the profile: {n}",
        "Не удалось подготовить обновление: {e}": "Could not prepare the update: {e}",
        "В categories.json дубли расширений: {n}. Расширение попадёт только в один стек — последний по порядку.": "Duplicate extensions in categories.json: {n}. An extension goes into one stack only — the last one listed.",
        "Предлагаю раскладку {n} расширений. Сними галочку, чтобы пропустить; стек можно поменять. Твоя categories.json не меняется — раскладка хранится отдельно и обратима.": "Here is a suggested mapping for {n} extensions. Uncheck one to skip it; the stack can be changed. Your categories.json is not touched — the mapping is stored separately and is reversible.",
        "Запуск: выключено {n} расширений. OK.": "Launch: {n} extensions disabled. OK.",
        "Не удалось получить информацию о релизе (нет сети или в релизе нет .exe).": "Could not get release info (no network, or the release has no .exe).",
        "Не найден CLI VS Code.": "VS Code CLI not found.",
        "Пресет не найден: {name}": "Preset not found: {name}",
        "Пресет «{name}»: голый режим.": "Preset '{name}': bare mode.",
        "Пресет «{name}»: выключено расширений — {n}.": "Preset '{name}': extensions disabled — {n}.",
        "Не удалось запустить VS Code: {err}": "Could not start VS Code: {err}",
        # C++-центр
        "найдено: {n}": "found: {n}",
        "Настроить": "Set up",
        "C/C++-проект без настроек VS Code: сборка (Ctrl+Shift+B), отладка (F5) и подсказки не настроены. Сгенерировать их под ваш компилятор?": "A C/C++ project without VS Code settings: build (Ctrl+Shift+B), debugging (F5) and code intelligence are not set up. Generate them for your compiler?",
        "Всё для C/C++ в одном окне: выбрать и поставить компилятор, подсказки и отладчик, проверить сборку, настроить проект.": "Everything for C/C++ in one window: pick and install a compiler, code intelligence and a debugger, check the build, set up a project.",
        "Открыть C++-центр": "Open the C++ center",
        "Компилятор C++ в PATH не найден.": "No C++ compiler found on PATH.",
        "Стеки мешают друг другу": "Stacks conflict",
        "Запустить как есть": "Launch anyway",
        "Выбрать и поставить": "Choose and install",
        "В PATH: {tools}.": "On PATH: {tools}.",
        "Включены вместе: {pairs}.\n\nДва движка подсказок C++ дублируют подсказки и память. Оставьте один, или настройте проект (кнопка «C++…» → «Проект» с clangd) — там IntelliSense cpptools отключается только для этой папки.": "Enabled together: {pairs}.\n\nTwo C++ code-intelligence engines duplicate suggestions and memory. Keep one, or set up the project (the 'C++…' button → 'Project' with clangd) — that disables cpptools IntelliSense for this folder only.",
        "Это C/C++-проект, а подходящего инструмента нет: {tools}. Открыть C++-центр?": "This is a C/C++ project, but a suitable tool is missing: {tools}. Open the C++ center?",
        "Компиляторы (MinGW, MSYS2, MSVC), CMake и Ninja, подсказки cpptools или clangd, отладчики, библиотеки и vcpkg ставятся в C++-центре одним списком: у каждого пункта написано, за что он отвечает.": "Compilers (MinGW, MSYS2, MSVC), CMake and Ninja, cpptools or clangd code intelligence, debuggers, libraries and vcpkg are installed in the C++ center from one list: each item says what it is for.",
        "{n} МБ": "{n} MB",
        "{n} ГБ": "{n} GB",
        "C++: установка и настройка": "C++: install and set up",
        "Установка": "Install",
        "Проверка": "Check",
        "Проект": "Project",
        "Проверяю, что уже установлено…": "Checking what is already installed…",
        "Проверить заново": "Check again",
        "Что будет сделано": "What will be done",
        "Остановить": "Stop",
        "Остановить после текущего шага.": "Stop after the current step.",
        "Настроить проект": "Set up a project",
        "К выбору": "Back to the list",
        "План": "Plan",
        "Начать?": "Start?",
        "идёт…": "running…",
        "С пробной сборкой (дольше, до минуты)": "With a test build (slower, up to a minute)",
        "Собрать, запустить и отладить маленькую программу на C++20 каждым компилятором — так видны проблемы, которых не видно по версиям.": "Build, run and debug a small C++20 program with each compiler — this reveals problems that version numbers do not.",
        "Найдёт все компиляторы, проверит, не смешаны ли тулчейны в PATH, и соберёт пробную программу. Ничего не меняет.": "Finds all compilers, checks whether toolchains are mixed on PATH and builds a test program. Changes nothing.",
        "Проверяю… Пробная сборка может занять до минуты.": "Checking… The test build may take up to a minute.",
        "Полный отчёт текстом": "Full text report",
        "Проблемы": "Problems",
        "ошибка": "error",
        "внимание": "warning",
        "к сведению": "note",
        "Компиляторы": "Compilers",
        "Пробная сборка C++20": "C++20 test build",
        "компиляция": "compile",
        "линковка": "link",
        "запуск": "run",
        "отладчик": "debugger",
        "Отчёт C++": "C++ report",
        "Скопировать": "Copy",
        "Настроить папку проекта": "Set up a project folder",
        "Папка проекта": "Project folder",
        "Microsoft C/C++: привычно, отладчик gdb встроен.": "Microsoft C/C++: familiar, gdb debugger built in.",
        "Легче и точнее. В проекте IntelliSense cpptools будет отключён, чтобы движки не дрались.": "Lighter and more precise. cpptools IntelliSense is disabled in the project so the engines do not clash.",
        "Одиночные файлы (g++ текущего файла)": "Single files (compile the current file)",
        "Олимпиадный режим: задача «собрать -O2 и запустить на input.txt»": "Contest mode: a 'build -O2 and run on input.txt' task",
        "Файлы стиля: .clang-format и .clang-tidy": "Style files: .clang-format and .clang-tidy",
        "Открыть в лаунчере": "Open in the launcher",
        "Применить": "Apply",
        "Новый проект": "New project",
        "латиница, цифры, _ . -": "Latin letters, digits, _ . -",
        "Создать": "Create",
        "Где создать": "Where to create",
        "Порядок в PATH": "PATH order",
        "Какой компилятор сделать основным?": "Which compiler should be the main one?",
        "Остальные опустить в конец PATH (рекомендуется, ничего не удаляется)": "Move the others to the end of PATH (recommended, nothing is removed)",
        "Остальные убрать из PATH совсем": "Remove the others from PATH entirely",
        "Всё для C/C++ в одном месте: поставить компилятор и инструменты, проверить, что код собирается и запускается, и настроить проект под VS Code.": "Everything for C/C++ in one place: install a compiler and tools, check that code builds and runs, and set up a project for VS Code.",
        "Идёт установка": "Installation in progress",
        "Установка ещё идёт. Прервать после текущего шага и закрыть?": "Installation is still running. Stop after the current step and close?",
        "Готовые наборы:": "Ready-made sets:",
        "Заново найти компиляторы и расширения.": "Find compilers and extensions again.",
        "Отметьте, что нужно. Под каждым пунктом написано, за что он отвечает. Уже установленное помечено и повторно не ставится.": "Check what you need. Each item says what it is for. Already installed items are marked and are not installed again.",
        "Показать шаги по порядку.": "Show the steps in order.",
        "Пакеты скачиваются по очереди — это может занять несколько минут. Окно можно не трогать. После установки откройте новый терминал и перезапустите VS Code, чтобы подхватился PATH.": "Packages download one after another — this may take several minutes. You can leave the window alone. Afterwards open a new terminal and restart VS Code so PATH is picked up.",
        "Всё выбранное уже установлено и настроено.": "Everything selected is already installed and set up.",
        "Будет установлено: {n} · около {size}": "To install: {n} · about {size}",
        "понадобятся права администратора": "administrator rights needed",
        "Делать нечего.": "Nothing to do.",
        "Для MSVC появится запрос прав администратора (UAC).": "MSVC will ask for administrator rights (UAC).",
        "PATH будет изменён, старое значение сохранится в файл.": "PATH will be changed; the old value is saved to a file.",
        "ждёт": "waiting",
        "готово": "done",
        "Готово с замечаниями": "Done with issues",
        "Всё установлено. Откройте новый терминал и перезапустите VS Code.": "All installed. Open a new terminal and restart VS Code.",
        "Остановлю после текущего шага…": "Stopping after the current step…",
        "Проблем не найдено: C++ собирается и запускается.": "No problems found: C++ builds and runs.",
        "Можно скопировать и отправить.": "You can copy and share it.",
        "Не найдено ни одного GCC.": "No GCC found.",
        "Создаст в папке файлы для VS Code: сборка по Ctrl+Shift+B, отладка по F5 и подсказки кода под выбранный компилятор. Ваши файлы без спроса не перезаписываются.": "Creates VS Code files in the folder: build with Ctrl+Shift+B, debug with F5 and code intelligence for the chosen compiler. Your files are never overwritten without asking.",
        "Компилятор": "Compiler",
        "Подсказки кода": "Code intelligence",
        "Сборка": "Build",
        "Стандарт": "Standard",
        "Файлы (снимите галочку, чтобы пропустить):": "Files (uncheck to skip):",
        "Подставить папку в главное окно и подобрать стеки.": "Put the folder into the main window and pick stacks.",
        "Имя": "Name",
        "Шаблон": "Template",
        "Компилятор, подсказки и стандарт берутся из настроек выше.": "Compiler, code intelligence and standard are taken from the settings above.",
        "Сначала нужен компилятор — вкладка «Установка».": "A compiler is needed first — see the 'Install' tab.",
        "Когда в PATH несколько GCC, программа может запуститься с чужой библиотекой libstdc++ и упасть. Выберите основной — он встанет первым.": "With several GCCs on PATH a program can load another build's libstdc++ and crash. Pick the main one — it goes first.",
        "нужен админ": "admin needed",
        "Выберите компилятор MSYS2 (или оставьте свой из MSYS2), чтобы ставить библиотеки через pacman.": "Choose the MSYS2 compiler (or keep your MSYS2 one) to install libraries with pacman.",
        "Установить ({n})": "Install ({n})",
        "Будет сделано:\n\n{steps}{extra}\n\nПродолжить?": "Will be done:\n\n{steps}{extra}\n\nContinue?",
        "Шаг {i} из {n}: {title}": "Step {i} of {n}: {title}",
        "пропущен": "skipped",
        "Навести порядок в PATH…": "Fix PATH order…",
        "Не найдено ни одного компилятора C++.": "No C++ compiler found.",
        "C/C++-файлов не найдено": "no C/C++ files found",
        "настройки VS Code уже есть": "VS Code settings already present",
        "Настройка проекта": "Project setup",
        "Готово: {n} файл(ов). Откройте папку в VS Code: Ctrl+Shift+B — сборка, F5 — отладка.": "Done: {n} file(s). Open the folder in VS Code: Ctrl+Shift+B builds, F5 debugs.",
        "Создан: {path}": "Created: {path}",
        "Не удалось проверить систему: {e}": "Could not check the system: {e}",
        "уже установлена": "already installed",
        "Ставить ничего не нужно. Будет выполнено шагов настройки: {n}.": "Nothing to install. Setup steps to run: {n}.",
        "Успешно: {ok}, с ошибкой: {err}, пропущено: {skip}. Подробности — в журнале ниже и в подсказке у шага.": "Succeeded: {ok}, failed: {err}, skipped: {skip}. Details are in the log below and in each step's tooltip.",
        "Проверка не удалась: {e}": "Check failed: {e}",
        "Найдено: ошибок {e}, предупреждений {w}. Ниже — что это значит и как исправить.": "Found: {e} errors, {w} warnings. Below is what they mean and how to fix them.",
        "Подобрать установку": "Choose what to install",
        "активный": "active",
        "C/C++-файлы": "C/C++ files",
        "Укажите существующую папку.": "Choose an existing folder.",
        "Проект создан:\n{path}\n\nПодставить его в лаунчер, чтобы открыть в VS Code?": "Project created:\n{path}\n\nPut it into the launcher to open it in VS Code?",
        "Вместе с убранными каталогами пропадут: {tools}. Продолжить?": "These will disappear together with the removed folders: {tools}. Continue?",
        "уже есть": "installed",
        "не в PATH": "not on PATH",
        "библиотеки: {libs}": "libraries: {libs}",
        "В папке: {what}": "In the folder: {what}",
        "{path} — все нужные ключи уже заданы": "{path} — all needed keys are already set",
        "{path} — дописать ключей: {n}": "{path} — keys to add: {n}",
        "{path} — уже есть, перезаписать (старый сохранится в .bak)": "{path} — exists, overwrite (the old one is kept as .bak)",
        "{path} — создать": "{path} — create",
        "Сейчас в PATH: {dirs}": "On PATH now: {dirs}",
        "CMake-проект": "CMake project",
        "проект на Makefile": "Makefile project",
        "проект Meson": "Meson project",
        # оболочка окна: навигация и страницы
        "Проверить, обновить или удалить": "Check, update or remove",
        "Прописать путь к интерпретатору в settings.json VS Code.": "Write the interpreter path into VS Code settings.json.",
        "Русский": "Русский",  # самоназвание языка не переводится
        "Настройки": "Settings",
        "Вид, палитра, язык и параметры запуска": "Look, palette, language and launch options",
        "Проект и пресет": "Project and preset",
        "Папка": "Folder",
        "Стеки расширений": "Extension stacks",
        "Полоска слева у карточки — нагрузка на память: красная тяжёлый, жёлтая средний, зелёная лёгкий. Снятые галочки не удаляют расширения — они просто не грузятся в этот запуск. Кнопка «›» — что внутри стека.": "The strip on the left of a card is memory load: red heavy, yellow medium, green light. Unchecked stacks are not removed — they just do not load this time. The '›' button shows what is inside a stack.",
        "Спросить у запущенного VS Code, сколько памяти держит каждое расширение и каждый стек. Это факт, а не оценка.": "Ask the running VS Code how much memory each extension and stack holds. A measurement, not an estimate.",
        "Рекомендованные настройки для установленных стеков и против фоновой нагрузки. Только недостающие ключи, с бэкапом.": "Recommended settings for installed stacks and against background load. Only missing keys, with a backup.",
        "Незнакомые расширения": "Unknown extensions",
        "Все установленные расширения уже в карте.": "All installed extensions are already mapped.",
        "Личные исключения": "Personal overrides",
        "Копии установщиков, данные удалённых проектов, кэши, старые логи и версии расширений. Предпросмотр, удаление в Корзину.": "Installer copies, data of deleted projects, caches, old logs and extension versions. Preview first, deletes to the Recycle Bin.",
        "Тулчейны и версии, дубли и мёртвые записи в PATH, JAVA_HOME.": "Toolchains and versions, duplicate and dead PATH entries, JAVA_HOME.",
        "Выбрать, какой VS Code запускать: стабильный, Insiders или портативный.": "Choose which VS Code to launch: stable, Insiders or portable.",
        "Журнал": "Log",
        "Вид": "Look",
        "Запуск VS Code": "Launching VS Code",
        "Трей": "Tray",
        "Команда запуска": "Launch command",
        "Запуск": "Launch",
        "Стеки расширений, папка проекта и запуск VS Code": "Extension stacks, project folder and launching VS Code",
        "Компилятор, подсказки, отладка, проверка и настройка проекта": "Compiler, code intelligence, debugging, checks and project setup",
        "Языки": "Languages",
        "Компиляторы и SDK других языков через winget": "Compilers and SDKs for other languages via winget",
        "Расширения": "Extensions",
        "Замер памяти, незнакомые расширения, исключения, settings.json": "Memory measurement, unknown extensions, overrides, settings.json",
        "Обслуживание": "Maintenance",
        "Уборка мусора VS Code, проверка PATH, журнал": "VS Code cleanup, PATH check, log",
        "Отметь стеки на сегодня — остальные расширения не загрузятся, и память останется свободной. Ничего не удаляется.": "Pick today's stacks — the other extensions will not load and memory stays free. Nothing is removed.",
        "Выбрать папку…": "Choose a folder…",
        "Открыть рабочую область (.code-workspace)…": "Open a workspace (.code-workspace)…",
        "Выбрать папку, рабочую область или недавний проект. Папку можно и просто перетащить в окно.": "Choose a folder, a workspace or a recent project. You can also drag a folder onto the window.",
        "Пресеты: сохранить, удалить, экспорт, ярлык, профиль": "Presets: save, delete, export, shortcut, profile",
        "Пресеты ▾": "Presets ▾",
        "Закрыть VS Code перед стартом": "Close VS Code first",
        "Голый режим": "Bare mode",
        "Сколько на самом деле весит каждое расширение, что делать с незнакомыми и какие настройки VS Code снимают фоновую нагрузку.": "How much each extension really costs, what to do with unknown ones and which VS Code settings cut background load.",
        "Расширения, которых нет в data/categories.json, лаунчер всегда оставляет включёнными. Их можно разложить по стекам автоматически — по манифесту; сама карта при этом не меняется.": "Extensions missing from data/categories.json always stay enabled. They can be sorted into stacks automatically by their manifest; the map itself is not changed.",
        "Режим «всегда включать / всегда выключать» для отдельных расширений задаётся в «›» у стека и сильнее галочек.": "The 'always enable / always disable' mode for single extensions is set via a stack's '›' and beats the stack checkboxes.",
        "Дубли в карте": "Duplicates in the map",
        "Уборка того, что VS Code копит на диске, проверка PATH и журнал.": "Clean up what VS Code piles up on disk, check PATH, read the log.",
        "Вид и поведение — всё меняется сразу.": "Look and behaviour — changes apply immediately.",
        "Тема": "Theme",
        "Палитра — цвета окна и пейзаж на баннере запуска.": "Palette — window colours and the landscape on the launch banner.",
        "В светлой теме палитра меняет только акцент.": "In the light theme the palette changes only the accent.",
        "Закрывать мягко": "Close gently",
        "VS Code получит обычный запрос на закрытие и сам спросит про несохранённое; лаунчер дождётся выхода. Выключено — принудительно (/F): быстро, но несохранённое теряется.": "VS Code gets a normal close request and asks about unsaved files itself; the launcher waits for it to exit. Off — forced (/F): fast, but unsaved work is lost.",
        "Открывать в новом окне": "Open in a new window",
        "Без GPU-ускорения": "No GPU acceleration",
        "--disable-gpu: лечит артефакты на старых видеокартах, экономит немного памяти.": "--disable-gpu: fixes artifacts on old graphics cards and saves a little memory.",
        "Значок в трее": "Tray icon",
        "Правый клик по значку — список пресетов: VS Code открывается нужным набором без окна. Применится после перезапуска.": "Right-click the icon for the preset list: VS Code opens with a set without the window. Applies after a restart.",
        "Крестик сворачивает в трей": "Close button hides to tray",
        "Лаунчер останется в трее; выйти совсем — «Выход» в меню значка.": "The launcher stays in the tray; to quit, use 'Exit' in the icon menu.",
        "Сохранить текущий выбор как пресет…": "Save the current selection as a preset…",
        "Удалить выбранный пресет": "Delete the selected preset",
        "Экспорт пресетов в файл…": "Export presets to a file…",
        "Импорт пресетов из файла…": "Import presets from a file…",
        "Ярлык .cmd для пресета…": ".cmd shortcut for the preset…",
        "Файл, открывающий VS Code с пресетом двойным кликом": "A file that opens VS Code with the preset on double-click",
        "Экспорт профиля VS Code…": "Export a VS Code profile…",
        "Нативный профиль .code-profile ровно с включёнными расширениями": "A native .code-profile with exactly the enabled extensions",
        "Быстрый выбор стеков": "Quick stack selection",
        "Что выключится, команда запуска": "What gets disabled, launch command",
        "Включить все (с учётом поиска)": "Enable all (respecting search)",
        "Оставить минимум (только ядро)": "Minimum (core only)",
        "Закроет все окна VS Code ({exe}) перед стартом, чтобы память освободилась. Запускай этот тул НЕ из терминала VS Code. Как закрывать (мягко или принудительно) — в «Настройках».": "Closes all VS Code windows ({exe}) before starting so memory is freed. Do NOT run this tool from the VS Code terminal. How to close (gently or forced) is in 'Settings'.",
        "Список расширений, которые будут выключены": "List of extensions that will be disabled",
        "Эквивалентная команда для cmd/ярлыка": "Equivalent command for cmd/shortcuts",
        # починка PATH
        "Починить PATH": "Fix PATH",
        "Мусор, мёртвые записи и главное — кто кого перекрывает: заглушка Microsoft Store вместо Python, компилятор вместо ваших python/cmake, чужой java. С предпросмотром и откатом.": "Junk, dead entries and above all what overrides what: the Microsoft Store stub instead of Python, a compiler instead of your python/cmake, a foreign java. With preview and undo.",
        "Починить PATH…": "Fix PATH…",
        "Кто что перекрывает": "What overrides what",
        "Мёртвые записи": "Dead entries",
        "Дубли и мусор": "Duplicates and junk",
        "Подсказки": "Hints",
        "Починка PATH": "PATH repair",
        "Проверяю системный и ваш PATH…": "Checking the system and user PATH…",
        "Windows ищет команду сначала в системном PATH, потом в вашем — слева направо. Здесь видно, что мешает, и что именно изменится. Каждое исправление можно снять галочкой; перед записью делается бэкап, откат — в меню «···».": "Windows looks for a command in the system PATH first, then in yours — left to right. Here you see what gets in the way and exactly what will change. Any fix can be unchecked; a backup is made before writing, undo is in the '···' menu.",
        "Что изменится": "What will change",
        "Починить": "Fix",
        "Показать итоговый PATH": "Show the resulting PATH",
        "Итоговый PATH": "Resulting PATH",
        "Починить PATH?": "Fix PATH?",
        "Записываю…": "Writing…",
        "Откатить PATH?": "Undo PATH change?",
        "Итоговый PATH и откат прошлых правок": "Resulting PATH and undo of earlier changes",
        "PATH в порядке: мусора и конфликтов нет.": "PATH is fine: no junk and no conflicts.",
        "Меняется системный PATH — нужны права администратора.": "The system PATH changes — administrator rights are needed.",
        "Внимание: после починки пропадут команды — снимите лишние галочки.": "Warning: some commands will disappear after the fix — uncheck the extra items.",
        "Откатить к бэкапу": "Restore a backup",
        "Ваш PATH:": "User PATH:",
        "Будет исправлено пунктов: {n}.\n\n{msg}\n\nПеред записью сохранится бэкап. Продолжить?": "Items to fix: {n}.\n\n{msg}\n\nA backup is saved before writing. Continue?",
        "Вернуть PATH из бэкапа?\n{f}\n\nТекущее значение тоже сохранится в бэкап.": "Restore PATH from this backup?\n{f}\n\nThe current value is backed up too.",
        "Найдено: {n}. Исправить можно {f}, по умолчанию отмечено {s}.": "Found: {n}. Fixable: {f}, checked by default: {s}.",
        "Починить ({n})": "Fix ({n})",
        "Пропадут команды: {t}.": "Commands that disappear: {t}.",
        "Системный PATH:": "System PATH:",
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
