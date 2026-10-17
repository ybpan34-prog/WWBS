"""Bounded, local Windows OCR for the optional guided boss entrance."""
import base64
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


# One hidden process per entrance; no network service, extra runtime or model.
_WORKER = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] > $null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime] > $null
[Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime] > $null
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
 $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and
 $_.GetParameters().Count -eq 1 -and $_.GetGenericArguments().Count -eq 1
} | Select-Object -First 1
function Await($operation,$resultType) {
 $task=$asTask.MakeGenericMethod($resultType).Invoke($null,@($operation))
 $task.GetAwaiter().GetResult()
}
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('zh-Hans'))
while ($null -ne ($request=[Console]::ReadLine())) {
 $memory=$null; $stream=$null; $bitmap=$null; $response=$null
 try {
  if ($null -eq $engine) { throw 'Windows Chinese OCR language pack is missing.' }
  $path=($request | ConvertFrom-Json).path
  $bytes=[IO.File]::ReadAllBytes($path)
  $memory=[IO.MemoryStream]::new($bytes,$false)
  $stream=[System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($memory)
  $decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $lines=@($result.Lines | ForEach-Object {
   $words=@($_.Words | ForEach-Object {
    $r=$_.BoundingRect
    @{text=$_.Text; x=$r.X; y=$r.Y; width=$r.Width; height=$r.Height}
   })
   @{words=$words}
  })
  $response=@{lines=$lines}
 } catch {
  $response=@{error=$_.Exception.Message}
 } finally {
  if ($null -ne $bitmap) { $bitmap.Dispose() }
  if ($null -ne $stream) { $stream.Dispose() }
  if ($null -ne $memory) { $memory.Dispose() }
 }
 $response | ConvertTo-Json -Depth 6 -Compress | ForEach-Object { [Console]::WriteLine($_) }
}
'''


class WindowsOcr:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('战歌重奏自动进入需要 Windows 中文文字识别。')
        executable = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        encoded = base64.b64encode(_WORKER.encode('utf-16-le')).decode('ascii')
        self.process = subprocess.Popen(
            [str(executable), '-NoProfile', '-NonInteractive', '-STA', '-EncodedCommand', encoded],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.results = queue.Queue(maxsize=2)
        self.reader = threading.Thread(target=self._read, daemon=True, name='wwbs-entrance-ocr')
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.results.put(line)
        finally:
            self.results.put(None)

    def recognize(self, path, *, cancelled=lambda: False, timeout=10):
        if cancelled():
            raise InterruptedError('任务已停止。')
        try:
            self.process.stdin.write(json.dumps({'path':str(Path(path).resolve())})+'\n')
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RuntimeError('Windows 文字识别未能启动，请检查中文语言组件。') from exc
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if cancelled():
                raise InterruptedError('任务已停止。')
            try:
                line = self.results.get(timeout=.1)
            except queue.Empty:
                continue
            if line is None:
                raise RuntimeError('Windows 文字识别已退出，请检查中文语言组件。')
            result = json.loads(line)
            if 'error' in result:
                raise RuntimeError('Windows 中文文字识别失败：'+str(result['error']))
            return result.get('lines', [])
        raise RuntimeError('Windows 文字识别超时，已停止自动进入。')

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=3)
        for stream in (self.process.stdin, self.process.stdout):
            stream.close()
