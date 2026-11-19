# Bouwt tvrows.apk zonder Gradle: aapt2 + javac + d8 + zipalign + apksigner
param([string]$FeedUrl = $env:TVROWS_FEED_URL)   # bijv. http://tvfeed.local:8871/recordings.json
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not $FeedUrl) { throw 'Geef het adres van tvfeed op: .\build.ps1 -FeedUrl http://<server>:8871/recordings.json (of zet $env:TVROWS_FEED_URL)' }
"<?xml version=""1.0"" encoding=""utf-8""?>`n<resources><string name=""feed_url"" translatable=""false"">$FeedUrl</string></resources>" | Set-Content "$root\res\values\feed.xml" -Encoding UTF8
$sdk  = 'D:\Android\sdk'
$bt   = "$sdk\build-tools\34.0.0"
$jar  = "$sdk\platforms\android-34\android.jar"
$jdk  = 'D:\Android\jdk\jdk-17.0.21.0.2+1'
$env:JAVA_HOME = $jdk
$env:Path = "$jdk\bin;$env:Path"

$out = "$root\build"
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $out, "$out\compiled", "$out\classes", "$out\gen" | Out-Null

& "$bt\aapt2.exe" compile --dir "$root\res" -o "$out\compiled"
if ($LASTEXITCODE) { throw 'aapt2 compile mislukt' }
$flata = Get-ChildItem "$out\compiled" -Filter *.flat | ForEach-Object { $_.FullName }
& "$bt\aapt2.exe" link -o "$out\base.apk" -I $jar --manifest "$root\AndroidManifest.xml" --java "$out\gen" @flata
if ($LASTEXITCODE) { throw 'aapt2 link mislukt' }

# AIDL (Projectivy-wallpaperplug-in-API) -> Java
New-Item -ItemType Directory "$out\aidlgen" | Out-Null
& "$bt\aidl.exe" -I "$root\aidl" -o "$out\aidlgen" "$root\aidl\tv\projectivy\plugin\wallpaperprovider\api\IWallpaperProviderService.aidl"
if ($LASTEXITCODE) { throw 'aidl mislukt' }

$src = @(Get-ChildItem "$root\src" -Recurse -Filter *.java | ForEach-Object { $_.FullName }) + @(Get-ChildItem "$out\gen" -Recurse -Filter *.java | ForEach-Object { $_.FullName }) + @(Get-ChildItem "$out\aidlgen" -Recurse -Filter *.java | ForEach-Object { $_.FullName })
& javac -encoding UTF-8 -source 8 -target 8 -Xlint:-options -bootclasspath $jar -d "$out\classes" @src
if ($LASTEXITCODE) { throw 'javac mislukt' }

$cls = Get-ChildItem "$out\classes" -Recurse -Filter *.class | ForEach-Object { $_.FullName }
& "$bt\d8.bat" --lib $jar --output $out @cls
if ($LASTEXITCODE) { throw 'd8 mislukt' }

# classes.dex in de apk
Copy-Item "$out\base.apk" "$out\unsigned.apk"
Push-Location $out
& jar uf unsigned.apk classes.dex
Pop-Location
if ($LASTEXITCODE) { throw 'jar uf mislukt' }

& "$bt\zipalign.exe" -f 4 "$out\unsigned.apk" "$out\aligned.apk"
if ($LASTEXITCODE) { throw 'zipalign mislukt' }

$ks = "$root\debug.keystore"
if (-not (Test-Path $ks)) {
    & keytool -genkeypair -keystore $ks -storepass android -keypass android -alias debug -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=Thuis-rijen debug'
    if ($LASTEXITCODE) { throw 'keytool mislukt' }
}
& "$bt\apksigner.bat" sign --ks $ks --ks-pass pass:android --key-pass pass:android --out "$root\tvrows.apk" "$out\aligned.apk"
if ($LASTEXITCODE) { throw 'apksigner mislukt' }
Get-Item "$root\tvrows.apk" | Select-Object FullName, Length
