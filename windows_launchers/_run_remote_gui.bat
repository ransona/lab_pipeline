@echo off
setlocal EnableExtensions

rem Shared launcher for running lab_pipeline GUIs on dream from Windows.
rem Edit SSH_ALIAS or CODE_HOME below if your SSH config uses a different name/path.

set "SSH_ALIAS=dream"
set "REMOTE_USER="
set "CODE_HOME="
set "REMOTE_USER_INFERRED=0"

if "%~1"=="" (
    echo Usage: _run_remote_gui.bat APP_FILE.py [CONDA_ENV]
    exit /b 2
)

set "APP_FILE=%~1"
set "CONDA_ENV=%~2"
if "%CONDA_ENV%"=="" set "CONDA_ENV=sci"

for /f "usebackq delims=" %%U in (`ssh %SSH_ALIAS% "whoami" 2^>nul`) do (
    if not defined REMOTE_USER set "REMOTE_USER=%%U"
)

if not "%REMOTE_USER%"=="" set "REMOTE_USER_INFERRED=1"

if "%CODE_HOME%"=="" (
    if "%REMOTE_USER%"=="" set "REMOTE_USER=[username]"
    set "CODE_HOME=/home/%REMOTE_USER%/code/lab_pipeline"
)

if "%REMOTE_USER_INFERRED%"=="0" if "%REMOTE_USER%"=="[username]" (
    echo Could not infer remote username from: ssh %SSH_ALIAS% "whoami"
    echo Edit this file and set CODE_HOME to your remote lab_pipeline path.
    echo Current CODE_HOME is: %CODE_HOME%
    pause
    exit /b 1
)

echo Running %APP_FILE% on %SSH_ALIAS% as %REMOTE_USER%
echo Remote path: %CODE_HOME%/apps/%APP_FILE%
echo.
echo This requires SSH X forwarding or another remote GUI display setup.
echo.

ssh -Y %SSH_ALIAS% "bash -lc '/opt/scripts/conda-run.sh %CONDA_ENV% python %CODE_HOME%/apps/%APP_FILE%'"

endlocal
