@echo off
cd /d "%~dp0"
python -c "import requests, bs4" 2>nul || python -m pip install -r requirements.txt
echo.
echo ===== 이전에 실행 중이던 앱을 정리합니다 =====
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8765" ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
echo.
echo ===== 지원사업 대시보드 앱을 시작합니다 =====
echo 브라우저가 자동으로 열립니다. 이 검은 창은 닫지 마세요.
echo (창을 닫으면 사이트 추가/상세보기 기능이 꺼집니다)
echo.
python server.py
echo.
echo (서버가 종료되었습니다. 창을 닫아도 됩니다.)
pause