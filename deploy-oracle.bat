@echo off
chcp 65001 >nul
setlocal

set KEY=%USERPROFILE%\.ssh\drivebot-oracle.key
set HOST=ubuntu@141.253.108.13

echo === Deploiement sona sur Oracle ===
ssh -i "%KEY%" %HOST% "~/sona/deploy.sh"

if %errorlevel% neq 0 (
    echo.
    echo Le deploiement a echoue ^(code %errorlevel%^).
) else (
    echo.
    echo Deploiement termine.
)

pause
