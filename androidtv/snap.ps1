# Capture le rendu d'Alyra sur la TV (la capture systeme sort noire) -> shots\<Name>.png
# Exemple : .\snap.ps1 -Name a1 -Keys 'KEYCODE_DPAD_DOWN KEYCODE_DPAD_DOWN' -Extra '--es q "daft punk"'
param([string]$Name = 'snap', [string]$Keys = '', [string]$Extra = '', [int]$Wait = 2)
$adb = 'D:\Code\_assets\tv\platform-tools\adb.exe'
$s = '192.168.1.55:5555'
$remote = "/sdcard/Android/data/fr.lunatix.alyra/files/$Name.png"
& $adb connect $s | Out-Null
& $adb -s $s shell rm -f $remote
if ($Extra) { & $adb -s $s shell "am start -n fr.lunatix.alyra/.MainActivity $Extra" | Out-Null; Start-Sleep -Seconds 9 }
foreach ($k in ($Keys -split ' ' | Where-Object { $_ })) { & $adb -s $s shell input keyevent $k; Start-Sleep -Milliseconds 600 }
Start-Sleep -Seconds $Wait
& $adb -s $s shell "am start -n fr.lunatix.alyra/.MainActivity --es snap $Name" | Out-Null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if ((& $adb -s $s shell ls $remote 2>$null) -match "$Name.png") { break }
}
New-Item -ItemType Directory -Force "$PSScriptRoot\shots" | Out-Null
$out = "$PSScriptRoot\shots\$Name.png"
& $adb -s $s pull $remote $out | Out-Null
$out
