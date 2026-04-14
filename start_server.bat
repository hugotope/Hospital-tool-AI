@echo off
chcp 65001 >nul 2>&1
title Hospital AI - Sistema de Gestion Medica

color 1F
cls

echo.
echo  ==========================================================
echo     Hospital AI  -  Sistema de Gestion Medica  v2.0
echo  ==========================================================
echo.

:: ── Buscar Python ──────────────────────────────────────────────────────────
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY (
    where py >nul 2>&1 && set "PY=py"
)
if not defined PY (
    echo  [ERROR] Python no encontrado en el sistema.
    echo          Descargalo en: https://python.org/downloads
    echo.
    pause
    exit /b 1
)
echo  [OK] Python detectado: %PY%

:: ── Ir a la carpeta back-end ───────────────────────────────────────────────
cd /d "%~dp0back-end"
if not exist "app.py" (
    echo  [ERROR] No se encontro app.py en la carpeta back-end
    pause
    exit /b 1
)

:: ── Instalar dependencias ──────────────────────────────────────────────────
echo  [1/3] Instalando / verificando dependencias...
%PY% -m pip install -r requirements.txt -q --disable-pip-version-check
if %ERRORLEVEL% NEQ 0 (
    echo  [WARN] Algunas dependencias pueden no haberse instalado correctamente.
)
echo  [OK] Dependencias listas.

:: ── Abrir frontend en el navegador ────────────────────────────────────────
echo  [2/3] Abriendo frontend en el navegador...
start "" "%~dp0front-end\index.html"

:: ── Iniciar servidor Flask ─────────────────────────────────────────────────
echo  [3/3] Iniciando servidor Flask...
echo.
echo  ==========================================================
echo   URL del servidor : http://127.0.0.1:8000
echo   Credenciales     : admin / 1234
echo   Frontend         : front-end\index.html
echo  ==========================================================
echo.
echo  Presiona Ctrl+C para detener el servidor.
echo.

%PY% app.py

echo.
echo  [INFO] Servidor detenido.
pause
