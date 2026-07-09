@echo off
cd /d "%~dp0"
python -c "import requests, bs4" 2>nul || python -m pip install -r requirements.txt
echo.
echo ===== 이전에 실행 중이던 앱(8765/8770)을 정리합니다 =====
powershell -NoProfile -Command "8765,8770 | ForEach-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }"
echo.
echo ===== 지원사업 대시보드 앱을 시작합니다 =====
echo 브라우저가 자동으로 열립니다. 이 검은 창은 닫지 마세요.
echo.
python server.py
echo.
echo (서버가 종료되었습니다. 창을 닫아도 됩니다.)
pause