$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolDirectory = Join-Path $projectRoot '.build-tools'
$innoDirectory = Join-Path $toolDirectory 'inno'
New-Item -ItemType Directory -Path $toolDirectory -Force | Out-Null
$installerPath = Join-Path $toolDirectory 'innosetup-6.7.3.exe'
if (-not (Test-Path -LiteralPath (Join-Path $innoDirectory 'ISCC.exe'))) {
    Invoke-WebRequest -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' -OutFile $installerPath
    $signature = Get-AuthenticodeSignature -LiteralPath $installerPath
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys') {
        throw 'La signature du compilateur Inno Setup est invalide.'
    }
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/PORTABLE=1', '/NOICONS', ('/DIR="' + $innoDirectory + '"'))
    $process = Start-Process -FilePath $installerPath -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Inno Setup : code $($process.ExitCode)" }
}
Write-Output (Join-Path $innoDirectory 'ISCC.exe')
