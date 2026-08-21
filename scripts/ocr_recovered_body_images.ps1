$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime

[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Globalization.Language,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null

function Await-WinRt {
    param(
        [Parameter(Mandatory=$true)] $Operation,
        [Parameter(Mandatory=$true)] [Type] $ResultType
    )
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and
            $_.IsGenericMethod -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        } |
        Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

$workspaceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$manifestPath = Get-ChildItem -LiteralPath $workspaceRoot -Recurse -Filter 'legacy_body_backfill_manifest.json' |
    Where-Object { $_.FullName -like '*v2.2*20260820*' } |
    Select-Object -First 1 -ExpandProperty FullName
if(-not $manifestPath) { throw 'Legacy body backfill manifest was not found.' }
$outputPath = Join-Path (Split-Path -Parent $manifestPath) 'body_image_ocr_results.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$images = $manifest | Where-Object {
    $_.status -eq 'ok' -and $_.local_path -match '\.(gif|jpg|jpeg|png)$'
}

$language = [Windows.Globalization.Language]::new('zh-Hans-CN')
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
if(-not $engine) { throw 'Unable to create the zh-Hans-CN Windows OCR engine.' }

$results = foreach($item in $images) {
    $record = [ordered]@{
        notice_id = $item.notice_id
        source_url = $item.target_url
        image_path = $item.local_path
        image_sha256 = $item.sha256
        ocr_language = 'zh-Hans-CN'
        ocr_status = 'failed'
        ocr_text = $null
        ocr_text_chars = 0
        ocr_lines = 0
        error = $null
        processed_at = (Get-Date).ToString('o')
    }
    try {
        $absolutePath = (Resolve-Path -LiteralPath $item.local_path).Path
        $file = Await-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($absolutePath)) ([Windows.Storage.StorageFile])
        $stream = Await-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Await-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $ocr = Await-WinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $text = $ocr.Text.Trim()
        $record.ocr_status = if($text) { 'ok_requires_manual_review' } else { 'empty_result' }
        $record.ocr_text = $text
        $record.ocr_text_chars = $text.Length
        $record.ocr_lines = $ocr.Lines.Count
        $stream.Dispose()
    } catch {
        $record.error = $_.Exception.Message
    }
    [pscustomobject]$record
}

$results | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $outputPath -Encoding UTF8
$summary = [ordered]@{
    generated_at = (Get-Date).ToString('o')
    attempted = @($results).Count
    ocr_nonempty = @($results | Where-Object { $_.ocr_text_chars -gt 0 }).Count
    total_characters = ($results | Measure-Object ocr_text_chars -Sum).Sum
    output = $outputPath
}
$summary | ConvertTo-Json -Depth 3
