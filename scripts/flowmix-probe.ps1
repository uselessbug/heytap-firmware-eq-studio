# Uses only the explicitly selected Flowmix Beta 5-10 APK and curl.exe.
# No credential is printed or written to the output file.
param(
    [Parameter(Mandatory=$true)][string]$Apk,
    [ValidateSet('fr-api.ykload.cn','fr-api.ykload.com')]
    [string]$BaseHost = 'fr-api.ykload.cn',
    [string]$Output = 'flowmix-sources-diagnostic.json',
    [switch]$Anonymous
)
$ErrorActionPreference = 'Stop'
$flowmixExpectedHash = '79777621b8dd6643f7ab2c0c0c7e77f846a2cb2d6c4ed23b59ac8858798412e2'
if ((Get-FileHash -LiteralPath $Apk -Algorithm SHA256).Hash.ToLower() -ne $flowmixExpectedHash) {
    throw 'APK does not match the studied Flowmix Beta 5-10. No request sent.'
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$flowmixZip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $Apk))
try {
    $flowmixEntry = $flowmixZip.GetEntry('classes.dex')
    $flowmixStream = $flowmixEntry.Open()
    $flowmixMemory = New-Object System.IO.MemoryStream
    try { $flowmixStream.CopyTo($flowmixMemory); $flowmixBytes = $flowmixMemory.ToArray() }
    finally { $flowmixStream.Dispose(); $flowmixMemory.Dispose() }
} finally { $flowmixZip.Dispose() }
$flowmixCount = [BitConverter]::ToUInt32($flowmixBytes, 56)
$flowmixOffset = [BitConverter]::ToUInt32($flowmixBytes, 60)
$flowmixCandidates = @()
for ($flowmixI = 0; $flowmixI -lt $flowmixCount; $flowmixI++) {
    $flowmixPos = [int][BitConverter]::ToUInt32($flowmixBytes, $flowmixOffset + 4*$flowmixI)
    do { $flowmixByte = $flowmixBytes[$flowmixPos]; $flowmixPos++ } while ($flowmixByte -band 128)
    $flowmixEnd = $flowmixPos
    while ($flowmixBytes[$flowmixEnd] -ne 0) { $flowmixEnd++ }
    $flowmixValue = [Text.Encoding]::UTF8.GetString($flowmixBytes, $flowmixPos, $flowmixEnd-$flowmixPos)
    if ($flowmixValue.StartsWith('Bearer ') -and $flowmixValue.Length -gt 7) { $flowmixCandidates += $flowmixValue }
}
if ($flowmixCandidates.Count -ne 1) { throw 'Measurement credential could not be uniquely located. No request sent.' }
$flowmixAuth = $flowmixCandidates[0]
# Pass the header on stdin rather than in the process command line.
$flowmixConfig = 'header = "Accept: application/json"' + "`n" + 'user-agent = "okhttp/5.3.2"'
if (!$Anonymous) { $flowmixConfig += "`n" + ('header = "Authorization: {0}"' -f $flowmixAuth) }
$flowmixTemp = [IO.Path]::GetTempFileName()
try {
    $flowmixStatus = $flowmixConfig | & curl.exe --config - --connect-timeout 10 --max-time 30 --max-filesize 2097152 -sS -o $flowmixTemp -w '%{http_code}' ('https://'+$BaseHost+'/api/sources')
    if ($LASTEXITCODE -ne 0) { throw ('curl transport failed with exit '+$LASTEXITCODE) }
    $flowmixBody = [IO.File]::ReadAllText($flowmixTemp)
    $flowmixBody = $flowmixBody.Replace($flowmixAuth, '[REDACTED]').Replace($flowmixAuth.Substring(7), '[REDACTED]')
    $flowmixResult = [ordered]@{
        http_status = [int]$flowmixStatus
        host = $BaseHost
        authentication = $(if ($Anonymous) { 'anonymous' } else { 'APK measurement Bearer' })
        user_agent = 'okhttp/5.3.2'
        body = $flowmixBody
    }
    $flowmixJson = $flowmixResult | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($Output), $flowmixJson, (New-Object Text.UTF8Encoding($false)))
    Write-Host ('HTTP '+$flowmixStatus+'; diagnostic saved: '+$Output)
} finally {
    Remove-Item -LiteralPath $flowmixTemp -ErrorAction SilentlyContinue
    $flowmixAuth = $null
    $flowmixCandidates = $null
    $flowmixConfig = $null
}
