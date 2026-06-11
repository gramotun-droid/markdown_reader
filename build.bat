@echo off
set APP_NAME=MdReader

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

python -m pip install -r requirements.txt

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

pyinstaller mdreader.spec

if exist dist\%APP_NAME%\%APP_NAME%.exe (
    echo.
    echo Build complete.
    echo Run this file:
    echo dist\%APP_NAME%\%APP_NAME%.exe
    echo.
    echo Do not run build\mdreader\%APP_NAME%.exe - it is an intermediate PyInstaller file.
) else (
    echo.
    echo Build failed: dist\%APP_NAME%\%APP_NAME%.exe was not created.
)
pause
