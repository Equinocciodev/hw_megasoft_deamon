@echo off
rem Definir variables
set SERVICE_NAME=ApiMerchantVpos
set PYTHON_SCRIPT_PATH=%~dp0main.py
set PYTHON_PATH=%~dp0python\python.exe
set NSSM_PATH=%~dp0nssm.exe

rem Detener e eliminar el servicio si ya existe
%NSSM_PATH% stop %SERVICE_NAME%
%NSSM_PATH% remove %SERVICE_NAME% confirm

rem Instalar el nuevo servicio
%NSSM_PATH% install %SERVICE_NAME% %PYTHON_PATH%

rem Configurar la ruta del script como argumento
%NSSM_PATH% set %SERVICE_NAME% AppParameters "%PYTHON_SCRIPT_PATH%"

rem Configurar el directorio de trabajo
%NSSM_PATH% set %SERVICE_NAME% AppDirectory "%~dp0python"

rem Configurar logs
%NSSM_PATH% set %SERVICE_NAME% AppStdout "%~dp0logs\output.log"
%NSSM_PATH% set %SERVICE_NAME% AppStderr "%~dp0logs\error.log"

rem Configurar el comportamiento de reinicio
%NSSM_PATH% set %SERVICE_NAME% AppRestartDelay 30000
%NSSM_PATH% set %SERVICE_NAME% AppStopMethodSkip 0
%NSSM_PATH% set %SERVICE_NAME% AppStopMethodConsole 1000
%NSSM_PATH% set %SERVICE_NAME% AppStopMethodWindow 1000
%NSSM_PATH% set %SERVICE_NAME% AppStopMethodThreads 1000

rem Iniciar el servicio
%NSSM_PATH% start %SERVICE_NAME%

echo Servicio instalado y configurado correctamente
pause