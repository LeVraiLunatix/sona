$ErrorActionPreference = 'Stop'
function Check($n) { if ($LASTEXITCODE -ne 0) { throw "$n a echoue ($LASTEXITCODE)" } }
$root = $PSScriptRoot
$sdk  = 'D:\Code\_assets\tv\sdk'
$bt   = "$sdk\build-tools\34.0.0"
$jar  = "$sdk\platforms\android-30\android.jar"
$jdk  = 'D:\Tools\jdk-25'
$out  = "$root\build"

Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$out\classes", "$out\res" | Out-Null

# 1. Compile les ressources et lie le manifest
if (Test-Path "$root\res\*") { & "$bt\aapt2.exe" compile --dir "$root\res" -o "$out\res.zip" }
$link = @('link', '-o', "$out\base.apk", '-I', $jar, '--manifest', "$root\AndroidManifest.xml", '--min-sdk-version', '21', '--target-sdk-version', '30')
if (Test-Path "$out\res.zip") { $link += "$out\res.zip" }
& "$bt\aapt2.exe" @link
Check "aapt2"

# 2. Java -> classes
$src = Get-ChildItem "$root\src" -Filter *.java -Recurse | ForEach-Object FullName
& "$jdk\bin\javac.exe" --release 8 -g:none -Xlint:-options -classpath $jar -d "$out\classes" $src
Check "javac"

# 3. classes -> dex
$cls = Get-ChildItem "$out\classes" -Filter *.class -Recurse | ForEach-Object FullName
& "$bt\d8.bat" --lib $jar --min-api 21 --output $out @cls
Check "d8"

# 4. Ajoute le dex et les assets a l'APK
# (pas aapt2 -A : sous Windows il ecrit des chemins avec "\" qu'Android ne retrouve pas)
Push-Location $out
& "$jdk\bin\jar.exe" uf base.apk classes.dex
Check "jar dex"
if (Test-Path "$root\assets") {
    & "$jdk\bin\jar.exe" uf base.apk -C $root assets
    Check "jar assets"
}
Pop-Location

# 5. Aligne + signe
& "$bt\zipalign.exe" -f 4 "$out\base.apk" "$out\aligned.apk"
$ks = "$root\debug.keystore"
if (-not (Test-Path $ks)) {
    & "$jdk\bin\keytool.exe" -genkeypair -keystore $ks -storepass android -keypass android -alias alyra -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=Alyra'
}
& "$bt\apksigner.bat" sign --ks $ks --ks-pass pass:android --key-pass pass:android --out "$root\Alyra.apk" "$out\aligned.apk"
Get-Item "$root\Alyra.apk" | Select-Object Name, Length
