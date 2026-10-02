# Диагностика окружения C/C++ и VS Code. Только чтение: ничего не ставит и не меняет.
param([string]$Project = "")

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = $PSScriptRoot
try { [IO.File]::WriteAllText((Join-Path $outDir ".w"), ""); Remove-Item (Join-Path $outDir ".w") }
catch { $outDir = [Environment]::GetFolderPath("Desktop") }
$out = Join-Path $outDir "vscl_diag_$stamp.txt"
$lines = New-Object System.Collections.Generic.List[string]

function Say([string]$s = "") { $lines.Add($s); Write-Host $s }
function Head([string]$s) { Say ""; Say ("=== " + $s + " ===") }
function Decode([byte[]]$b) {
    if (-not $b -or $b.Length -eq 0) { return "" }
    try { return (New-Object Text.UTF8Encoding($false, $true)).GetString($b) }
    catch { return [Text.Encoding]::Default.GetString($b) }
}
function Run([string]$exe, [string[]]$a, [int]$timeoutSec = 60, [hashtable]$env = @{}) {
    # Запуск программы с ограничением по времени; возвращает код выхода и вывод.
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = ($a | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join " "
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    foreach ($k in $env.Keys) { $psi.EnvironmentVariables[$k] = [string]$env[$k] }
    try {
        $p = [Diagnostics.Process]::Start($psi)
        # Вывод читаем байтами: одни программы пишут в UTF-8, другие (py.exe) — в
        # кодировке Windows, и русские пути иначе превращаются в кракозябры.
        $mo = New-Object IO.MemoryStream; $me = New-Object IO.MemoryStream
        $to = $p.StandardOutput.BaseStream.CopyToAsync($mo); $te = $p.StandardError.BaseStream.CopyToAsync($me)
        if (-not $p.WaitForExit($timeoutSec * 1000)) { try { $p.Kill() } catch {}; return @{ code = "таймаут"; text = "" } }
        $null = $to.Wait(3000); $null = $te.Wait(3000)
        return @{ code = $p.ExitCode; text = (((Decode $mo.ToArray()) + "`n" + (Decode $me.ToArray())).Trim()) }
    } catch { return @{ code = "не запустился"; text = $_.Exception.Message } }
}
function First([string]$t, [int]$n = 1) { (($t -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -First $n) -join "`n    " }
function Where-All([string]$name) {
    $r = & where.exe $name 2>$null
    if ($LASTEXITCODE -eq 0) { @($r) } else { @() }
}

Say "Диагностика VS Code Launcher / C++  $stamp"
Head "Система"
$os = Get-CimInstance Win32_OperatingSystem
Say ("Windows: " + $os.Caption + " " + $os.Version + ", " + $os.OSArchitecture)
Say ("Пользователь: " + $env:USERNAME + "   профиль: " + $env:USERPROFILE)
Say ("Кодовые страницы: ANSI " + [Text.Encoding]::Default.CodePage + ", OEM " + [Console]::OutputEncoding.CodePage)
Say ("Права администратора: " + ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
Say ("Служебные переменные VS Code в окружении: " + ((Get-ChildItem env: | Where-Object { $_.Name -match '^(VSCODE_|ELECTRON_RUN_AS_NODE)' } | ForEach-Object { $_.Name }) -join ", "))

Head "Лаунчер"
$repo = Split-Path $PSScriptRoot -Parent
$init = Join-Path $repo "launcher\__init__.py"
if (Test-Path $init) { Say ("Исходники: " + ((Select-String -Path $init -Pattern '__version__').Line)) }
foreach ($exe in @((Join-Path $repo "dist\VSCodeLauncher.exe"), (Join-Path $repo "VSCodeLauncher.exe"), (Join-Path $PSScriptRoot "VSCodeLauncher.exe"))) {
    if (Test-Path $exe) { $i = Get-Item $exe; Say ("exe: " + $exe + "  собран " + $i.LastWriteTime + "  версия " + $i.VersionInfo.FileVersion) }
}
foreach ($log in @((Join-Path $repo "launcher.log"), (Join-Path $repo "dist\launcher.log"), (Join-Path $env:LOCALAPPDATA "VSCodeLauncher\launcher.log"))) {
    if (Test-Path $log) { Say ("Журнал " + $log + " (последние 15 строк):"); Get-Content $log -Tail 15 -Encoding UTF8 | ForEach-Object { Say ("    " + $_) } }
}

Head "PATH (как увидит новый терминал)"
$mp = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment').Path
$up = (Get-ItemProperty 'HKCU:\Environment' -ErrorAction SilentlyContinue).Path
Say "Системный:"; ($mp -split ";") | Where-Object { $_ } | ForEach-Object { Say ("    " + $_ + $(if (-not (Test-Path ([Environment]::ExpandEnvironmentVariables($_)))) { "   <-- нет такой папки" })) }
Say "Пользовательский:"; ($up -split ";") | Where-Object { $_ } | ForEach-Object { Say ("    " + $_ + $(if (-not (Test-Path ([Environment]::ExpandEnvironmentVariables($_)))) { "   <-- нет такой папки" })) }

Head "Инструменты (все копии в PATH по порядку; первая и запускается)"
foreach ($t in "g++", "gcc", "gdb", "mingw32-make", "make", "cmake", "ninja", "clang++", "clangd", "clang-format", "lldb", "cl", "python", "py", "git", "code", "winget") {
    $all = @(Where-All $t)
    if (-not $all.Count) { Say ("{0,-13} не найден" -f $t); continue }
    $v = ""
    if ($t -notin "code", "py", "cl", "lldb") { $r = Run $all[0] @("--version") 20; $v = "  [" + (First $r.text) + "]" }
    Say ("{0,-13} {1}{2}" -f $t, $all[0], $v)
    $all | Select-Object -Skip 1 | ForEach-Object { Say ("{0,-13} (дальше в PATH) {1}" -f "", $_) }
}
Say "libstdc++-6.dll в PATH по порядку (программа возьмёт первую):"
foreach ($d in ($env:PATH -split ";")) { if ($d -and (Test-Path (Join-Path $d "libstdc++-6.dll"))) { Say ("    " + $d) } }

Head "Python"
$r = Run "py" @("-0p") 20; Say ("py -0p:`n    " + (First $r.text 12))
$pyHomes = @{}
foreach ($hive in "HKCU:", "HKLM:") {
    Get-ChildItem "$hive\Software\Python\PythonCore" -ErrorAction SilentlyContinue | ForEach-Object {
        $ip = (Get-ItemProperty ($_.PSPath + "\InstallPath") -ErrorAction SilentlyContinue).'(default)'
        Say ("реестр {0} {1}: {2}" -f $hive, $_.PSChildName, $ip)
        if ($ip -and (Test-Path (Join-Path $ip "Lib\encodings"))) { $pyHomes[$_.PSChildName] = $ip.TrimEnd("\") }
    }
}
Say ("PYTHONHOME=" + $env:PYTHONHOME + "   PYTHONPATH=" + $env:PYTHONPATH)

Head "lldb из LLVM"
$lldb = (Where-All "lldb" | Select-Object -First 1)
if (-not $lldb) { Say "lldb не найден в PATH." }
else {
    $dir = Split-Path $lldb -Parent
    Say ("lldb: " + $lldb)
    Say ("python*.dll рядом: " + ((Get-ChildItem $dir -Filter "python*.dll" -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }) -join ", "))
    Say ("папки Lib / lib\site-packages рядом с LLVM: " + ((Get-ChildItem (Split-Path $dir -Parent) -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }) -join ", "))
    $need = ""
    foreach ($f in "liblldb.dll", "lldb.exe") {
        $fp = Join-Path $dir $f
        if (-not (Test-Path $fp)) { continue }
        $txt = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($fp))
        $ms = [regex]::Matches($txt, '(?i)python3\d{0,2}\.dll') | ForEach-Object { $_.Value.ToLower() } | Sort-Object -Unique
        Say ("{0} ссылается на: {1}" -f $f, ($ms -join ", "))
        foreach ($m in $ms) { if ($m -match 'python3(\d{1,2})\.dll') { $need = "3." + $Matches[1] } }
        $txt = $null
    }
    if (-not $need) { Get-ChildItem $dir -Filter "python3*.dll" | ForEach-Object { if ($_.Name -match 'python3(\d{1,2})\.dll') { $need = "3." + $Matches[1] } } }
    Say ("Нужная lldb версия Python: " + $(if ($need) { $need } else { "не определена" }))
    $r = Run $lldb @("--version") 30
    Say ("lldb --version: код " + $r.code + "`n    " + (First $r.text 3))
    foreach ($ver in $pyHomes.Keys) {
        $r = Run $lldb @("--version") 30 @{ PYTHONHOME = $pyHomes[$ver] }
        Say ("с PYTHONHOME=" + $pyHomes[$ver] + " (Python " + $ver + "): код " + $r.code + "  " + (First $r.text))
        $r = Run $lldb @("--version") 30 @{ PATH = ($env:PATH + ";" + $pyHomes[$ver]) }
        Say ("с папкой Python " + $ver + " в конце PATH: код " + $r.code + "  " + (First $r.text))
    }
}

Head "Пробная сборка g++"
$gxx = (Where-All "g++" | Select-Object -First 1)
if (-not $gxx) { Say "g++ не найден - сборку пропускаю." }
else {
    $src = "#include <iostream>`n#include <vector>`n#include <ranges>`n#include <algorithm>`nint main(){ std::vector<int> v{3,1,2}; std::ranges::sort(v); std::cout << `"ok `" << v.front() << std::endl; return 0; }`n"
    foreach ($name in "vscl_diag", "vscl диаг c++") {
        $tmp = Join-Path $env:TEMP $name
        New-Item -ItemType Directory -Force $tmp | Out-Null
        [IO.File]::WriteAllText((Join-Path $tmp "main.cpp"), $src)
        Say ("Папка: " + $tmp)
        $r = Run $gxx @("-std=c++20", "-g", (Join-Path $tmp "main.cpp"), "-o", (Join-Path $tmp "main.exe")) 180
        Say ("  компиляция: код " + $r.code + "  " + (First $r.text 4))
        if (Test-Path (Join-Path $tmp "main.exe")) {
            $r = Run (Join-Path $tmp "main.exe") @() 20
            Say ("  запуск: код " + $r.code + "  вывод: " + (First $r.text))
            $gdb = (Where-All "gdb" | Select-Object -First 1)
            if ($gdb) { $r = Run $gdb @("-batch", "-nx", "-ex", "run", (Join-Path $tmp "main.exe")) 60; Say ("  gdb: код " + $r.code + "  " + $(if ($r.text -match "exited normally|ok 1") { "программа отработала под отладчиком" } else { First $r.text 4 })) }
        }
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Head "VS Code"
$code = (Where-All "code" | Select-Object -First 1)
if ($code) {
    $r = Run "cmd.exe" @("/c", "code", "--version") 40; Say ("версия: " + (First $r.text 3))
    $r = Run "cmd.exe" @("/c", "code", "--list-extensions", "--show-versions") 60
    Say "Расширения C/C++ и запуска:"
    ($r.text -split "`r?`n") | Where-Object { $_ -match 'cpptools|clangd|lldb|cmake|makefile|c-cpp-runner|code-runner|cpp' } | ForEach-Object { Say ("    " + $_) }
    Say ("Всего расширений: " + (($r.text -split "`r?`n") | Where-Object { $_.Trim() }).Count)
} else { Say "Команда code не найдена в PATH." }
Say ("Запущено процессов Code.exe: " + @(Get-Process Code -ErrorAction SilentlyContinue).Count)
$us = Join-Path $env:APPDATA "Code\User\settings.json"
if (Test-Path $us) {
    Say ("Настройки пользователя (" + $us + "), строки про C/C++:")
    Get-Content $us -Encoding UTF8 | Where-Object { $_ -match 'C_Cpp|clangd|cmake\.|code-runner|terminal\.integrated\.(env|defaultProfile)' } | ForEach-Object { Say ("    " + $_.Trim()) }
}

if ($Project -and (Test-Path $Project)) {
    Head ("Проект: " + $Project)
    Get-ChildItem $Project -File -ErrorAction SilentlyContinue | Select-Object -First 40 | ForEach-Object { Say ("    " + $_.Name) }
    $vs = Join-Path $Project ".vscode"
    if (Test-Path $vs) {
        Get-ChildItem $vs -File | ForEach-Object { Say ""; Say ("--- .vscode\" + $_.Name + " ---"); Get-Content $_.FullName -Encoding UTF8 | ForEach-Object { Say $_ } }
    } else { Say "Папки .vscode в проекте нет." }
}

[IO.File]::WriteAllLines($out, $lines, (New-Object Text.UTF8Encoding($true)))
Write-Host ""
Write-Host ("Отчёт сохранён: " + $out)
Start-Process notepad.exe $out
