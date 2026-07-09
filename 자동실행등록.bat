@echo off
set PYW=
for /f "delims=" %%i in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW set "PYW=pythonw.exe"

schtasks /Create /F /TN "지원사업 공고 수집" /TR "\"%PYW%\" \"%~dp0scraper.py\"" /SC HOURLY /MO 2 /ST 08:30

echo.
echo 2시간마다 자동 수집이 등록되었습니다. (오전 8시 30분 시작)
echo (해제하려면: schtasks /Delete /TN "지원사업 공고 수집" /F)
pause