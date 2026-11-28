@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
REM 공급사 가격 매핑 하루치 실행 (크롤러 직후). 작업 스케줄러가 register_mapping_task.bat 로 08:15 에 부른다.
REM 판정 → 오늘 가격 → Neo4j Recipe 노드에 공급사별 kg당 가격 반영(--graph)
REM 오늘 단가표가 아직 없으면(종료 코드 3) 15분 뒤 다시, 최대 4번 시도한다.
cd /d "%~dp0.."
set PYTHONUTF8=1
set PY=python
if exist "venv-win\Scripts\python.exe" (
  set PY=venv-win\Scripts\python.exe
) else (
  where py >nul 2>nul && set PY=py -3
)
if not exist "mapping\_logs" mkdir "mapping\_logs"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set TODAY=%%i
set LOG=mapping\_logs\%TODAY%.log

for /l %%n in (1,1,4) do (
  echo [%date% %time%] 시도 %%n >> "%LOG%"
  %PY% -m mapping.run --graph %* >> "%LOG%" 2>&1
  set CODE=!ERRORLEVEL!
  if !CODE!==0 goto done
  if not !CODE!==3 goto fail
  echo 오늘 단가표 없음 - 15분 뒤 다시 >> "%LOG%"
  powershell -NoProfile -Command "Start-Sleep -Seconds 900"
)

:fail
powershell -NoProfile -WindowStyle Hidden -Command "Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; $n.Icon=[System.Drawing.SystemIcons]::Warning; $n.Visible=$true; $n.ShowBalloonTip(10000,'가격 매핑 실패','backend\mapping\_logs 를 확인하세요','Warning'); Start-Sleep 11; $n.Dispose()"
exit /b 1

:done
exit /b 0
