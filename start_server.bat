@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Hospital AI - Docker (PostgreSQL + Mongo + API + Frontend)
color 1F
cls

echo.
echo  ==========================================================
echo     Hospital AI  -  Inicio automatico (Docker Compose)
echo  ==========================================================
echo.

cd /d "%~dp0"

if not exist "docker-compose.yml" (
    echo  [ERROR] No se encontro docker-compose.yml en:
    echo           %CD%
    pause
    exit /b 1
)

:: ── Docker disponible ────────────────────────────────────────────────────────
docker version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Docker no esta disponible o Docker Desktop no esta en marcha.
    echo          https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)
echo  [OK] Docker disponible.

:: ── Compose v2 o v1 ────────────────────────────────────────────────────────
set "DC=docker compose"
docker compose version >nul 2>&1
if errorlevel 1 (
    set "DC=docker-compose"
    docker-compose version >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] No se encontro docker compose ni docker-compose.
        pause
        exit /b 1
    )
)
echo  [OK] Usando: %DC%

:: ── Espejo de imagenes (evita CDN Cloudflare bloqueado en algunas redes) ───
set "MIRROR=docker.m.daocloud.io/library"
set "IMAGES=mongo:7 postgres:15-alpine python:3.11-slim nginx:1.27-alpine"

echo.
echo  Descargando imagenes base via espejo (%MIRROR%)...
echo  (La primera vez puede tardar varios minutos)
echo.

for %%I in (%IMAGES%) do (
    call :pull_and_tag %%I
    if errorlevel 1 (
        echo.
        echo  [ERROR] No se pudo obtener la imagen %%I
        echo          Comprueba tu conexion o ejecuta de nuevo mas tarde.
        pause
        exit /b 1
    )
)

echo.
echo  [OK] Imagenes base listas.

:: ── Contenedor postgres suelto (conflicto de nombre/puerto) ─────────────────
docker inspect hospital-ai-postgres >nul 2>&1
if not errorlevel 1 (
    echo  [INFO] Eliminando contenedor postgres suelto anterior...
    docker stop hospital-ai-postgres >nul 2>&1
    docker rm hospital-ai-postgres >nul 2>&1
)

:: ── Construir y levantar stack ─────────────────────────────────────────────
echo.
echo  Construyendo e iniciando servicios (Postgres, Mongo, backend, nginx)...
echo.

%DC% down >nul 2>&1
%DC% up -d --build --pull=never
if errorlevel 1 (
    echo.
    echo  [ERROR] docker compose up fallo. Ultimos logs del backend:
    %DC% logs backend --tail 40
    echo.
    pause
    exit /b 1
)

:: ── Esperar API saludable ───────────────────────────────────────────────────
echo.
echo  Esperando a que la API responda (hasta 3 min)...
set /a WAIT=0
:wait_health
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 'http://127.0.0.1:8000/api/health').StatusCode } catch { 0 }" 2>nul | findstr "200" >nul
if not errorlevel 1 goto :ready
set /a WAIT+=5
if !WAIT! GEQ 180 (
    echo  [WARN] La API tarda mas de lo habitual. Revisa: %DC% logs -f backend
    goto :ready
)
timeout /t 5 /nobreak >nul
goto :wait_health

:ready
echo.
echo  ==========================================================
echo   Stack en marcha.
echo.
echo   Portal (recomendado) : http://localhost:8888/
echo   API directa          : http://127.0.0.1:8000/api/health
echo   Credenciales demo    : admin / 1234
echo.
echo   Ver logs  : %DC% logs -f
echo   Detener   : %DC% down
echo  ==========================================================
echo.

start "" "http://localhost:8888/"

echo  Abriendo el portal en el navegador...
echo  (Si aun no responde, espera 30-60 s y recarga.)
echo.
pause
exit /b 0

:: ── Subrutina: pull desde espejo y etiquetar como library/xxx ───────────────
:pull_and_tag
set "IMG=%~1"
echo  - %IMG%
docker image inspect %IMG% >nul 2>&1
if not errorlevel 1 (
    echo    [cache] ya existe localmente
    exit /b 0
)
set "SRC=%MIRROR%/%IMG%"
docker pull %SRC%
if errorlevel 1 exit /b 1
docker tag %SRC% %IMG%
if errorlevel 1 exit /b 1
echo    [OK] %IMG%
exit /b 0
