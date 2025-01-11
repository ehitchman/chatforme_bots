@echo off
setlocal enabledelayedexpansion

:: Check if parameters are provided
if "%~1"=="" (
    echo No port provided.
    exit /b
)
if "%~2"=="" (
    echo No root directory provided.
    exit /b
)
if "%~3"=="" (
    echo No yaml file name provided.
    exit /b
)
if "%~4"=="" (
    echo No config dirpath provided.
    exit /b
)
if "%~5"=="" (
    echo No env filename provided.
    exit /b
)
if "%~6"=="" (
    echo No keys dirpath provided.
    exit /b
)
if "%~7"=="" (
    echo No keys filename provided.
    exit /b
)

:: Validate MINICONDA_HOME
if "%MINICONDA_HOME%"=="" (
    echo MINICONDA_HOME is not set. Please configure your system environment variables.
    exit /b
) else (
    if not exist "%MINICONDA_HOME%" (
        echo MINICONDA_HOME directory does not exist. Please check the path.
        exit /b
    )
)

:: Environment and Port
set "CHATZILLA_PORT_NUMBER=%~1"
set "CHATZILLA_ROOT_DIRECTORY=%~2"
set "CHATZILLA_YAML_FILE=%~3"
set "CHATZILLA_CONFIG_DIRPATH=%~4"
set "CHATZILLA_ENV_FILENAME=%~5"
set "CHATZILLA_KEYS_ENV_DIRPATH=%~6"
set "CHATZILLA_KEYS_ENV_FILENAME=%~7"


:: Debugging - Print the variables
echo MINICONDA_HOME=!MINICONDA_HOME!
echo CHATZILLA_YAML_FILE=!CHATZILLA_YAML_FILE!
echo CHATZILLA_PORT_NUMBER=!CHATZILLA_PORT_NUMBER!
echo CHATZILLA_ROOT_DIRECTORY=!CHATZILLA_ROOT_DIRECTORY!
echo CHATZILLA_CONFIG_DIRPATH=!CHATZILLA_CONFIG_DIRPATH!
echo CHATZILLA_ENV_FILENAME=!CHATZILLA_ENV_FILENAME!
echo CHATZILLA_KEYS_ENV_DIRPATH=!CHATZILLA_KEYS_ENV_DIRPATH!
echo CHATZILLA_KEYS_ENV_FILENAME=!CHATZILLA_KEYS_ENV_FILENAME!

:: Switch directory 
cd "!CHATZILLA_ROOT_DIRECTORY!" || (
    echo Directory not found: !CHATZILLA_ROOT_DIRECTORY!
    exit /b
)
echo ...current directory: %cd%

:: Set the game to be played
set /p CHATZILLA_SELECTED_GAME=What game are you playing today? (default:'no_game_selected'):

:: Activate Conda environment
call "%MINICONDA_HOME%\condabin\conda.bat" activate openai_chatzilla_ai_env || (
    echo Failed to activate Conda environment.
    exit /b
)

:: Run preflight audio setup
python config/startup_audio_devices.py || (
    echo Audio setup failed. Exiting.
    exit /b
)

:: Set configuration path
set "CHATZILLA_YAML_PATH=.\config\bot_user_configs\!CHATZILLA_YAML_FILE!"

echo ...starting twitch_bot.py
python twitch_bot.py
pause