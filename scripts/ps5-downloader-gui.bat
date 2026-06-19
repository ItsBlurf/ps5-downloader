@echo off
setlocal
cd /d "%~dp0\.."
set PYTHONPATH=src
py -m ps5_downloader.desktop.app
