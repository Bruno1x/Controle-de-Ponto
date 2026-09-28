@echo off
setlocal
cd /d "%~dp0"
title Controle de Ponto

set "PYTHON_CMD="

where py.exe >nul 2>nul
if not errorlevel 1 (
  py.exe -c "import sys" >nul 2>nul
  if errorlevel 1 (
    echo Instalando o interpretador Python 3.14...
    py.exe install 3.14
  )
  py.exe -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py.exe"
)

if not defined PYTHON_CMD (
  where python.exe >nul 2>nul
  if not errorlevel 1 (
    python.exe -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python.exe"
  )
)

if not defined PYTHON_CMD (
  echo Nao encontrei um interpretador Python que possa ser iniciado.
  echo No CMD, execute: py install 3.14
  echo Aguarde a instalacao terminar e abra este arquivo novamente.
  pause
  exit /b 1
)

set "VENV_DIR=%LOCALAPPDATA%\ControlePonto\venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Preparando o ambiente do sistema...
  "%PYTHON_CMD%" -m venv "%VENV_DIR%"
  if errorlevel 1 goto :erro
)

echo Conferindo dependencias do sistema...
"%VENV_DIR%\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :erro

"%VENV_DIR%\Scripts\python.exe" -c "import xlrd, openpyxl, reportlab" >nul 2>nul
if errorlevel 1 (
  echo As bibliotecas nao foram instaladas corretamente.
  echo Confira a conexao com a internet e execute o inicializador novamente.
  pause
  exit /b 1
)

echo Abrindo Controle de Ponto em http://127.0.0.1:8766
echo Para encerrar, feche esta janela.
"%VENV_DIR%\Scripts\python.exe" app.py
exit /b 0

:erro
echo.
echo Nao foi possivel preparar o sistema. Confira a mensagem acima.
pause
exit /b 1
