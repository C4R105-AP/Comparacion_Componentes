@echo off
cd /d "%~dp0"
echo Instalando PyInstaller y dependencias...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail
echo Generando ComparadorBOM.exe...
python -m PyInstaller --noconfirm comparador.spec
if errorlevel 1 goto :fail
echo.
echo Listo: dist\ComparadorBOM\ComparadorBOM.exe
echo Copia toda la carpeta dist\ComparadorBOM a otros PCs y abre el exe.
pause
exit /b 0
:fail
echo Error al generar el exe.
pause
exit /b 1
