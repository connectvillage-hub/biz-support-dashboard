@echo off
cd /d "%~dp0"
python -c "import requests, bs4" 2>nul || python -m pip install -r requirements.txt
echo.
echo ===== 지원사업 대시보드 앱을 시작합니다 =====
echo 브라우저가 자동으로 열립니다. 이 검은 창은 닫지 마세요.
echo (창을 닫으면 '사이트 추가' 기능이 꺼집니다)
echo.
python server.py
pause