@echo off
cd /d "%~dp0"
python -c "import requests, bs4" 2>nul || python -m pip install -r requirements.txt
echo.
echo ===== 공고 수집을 시작합니다 =====
python scraper.py
echo.
echo ===== 완료. index.html 을 새로고침하세요 =====
pause