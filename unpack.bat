@echo off 
powershell -command "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-Clipboard | Out-File -Encoding utf8 main.py" 
echo [OK] main.py をクリップボードの内容で上書きしました。
