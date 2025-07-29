:: Creacion de una tarea programada para ejecutar VposREST.bat al iniciar sesión
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if %errorlevel% equ 0 (
    echo La tarea "%TASK_NAME%" ya existe, omitiendo creacion.
) else (
    echo Creando la tarea programada "%TASK_NAME%"...
    schtasks /create /tn "%TASK_NAME%" /tr "C:\vpos\VposRestForSheduleTask.bat" /sc ONLOGON /rl HIGHEST /ru "%USERNAME%" /f
    if %errorlevel% equ 0 (
        echo Tarea creada exitosamente.
    ) else (
        echo Error al crear la tarea. Verifica los permisos o la sintaxis.
    )
)