@echo off
rem Склеивает части в целые архивы и печатает SHA256 (сверьте с SHA256SUMS)
cd /d "%~dp0"
if exist moneygraph-win-x64.zip.part00 copy /b moneygraph-win-x64.zip.part00+moneygraph-win-x64.zip.part01+moneygraph-win-x64.zip.part02+moneygraph-win-x64.zip.part03+moneygraph-win-x64.zip.part04+moneygraph-win-x64.zip.part05+moneygraph-win-x64.zip.part06 moneygraph-win-x64.zip >nul
if exist moneygraph-win-x64.zip certutil -hashfile moneygraph-win-x64.zip SHA256
if exist moneygraph-linux-x64.tar.gz.part00 copy /b moneygraph-linux-x64.tar.gz.part00+moneygraph-linux-x64.tar.gz.part01+moneygraph-linux-x64.tar.gz.part02+moneygraph-linux-x64.tar.gz.part03+moneygraph-linux-x64.tar.gz.part04+moneygraph-linux-x64.tar.gz.part05+moneygraph-linux-x64.tar.gz.part06+moneygraph-linux-x64.tar.gz.part07 moneygraph-linux-x64.tar.gz >nul
if exist moneygraph-linux-x64.tar.gz certutil -hashfile moneygraph-linux-x64.tar.gz SHA256
type SHA256SUMS
pause
