' run-hidden.vbs - run a PowerShell script with NO console window.
' Task Scheduler launcher: a plain "powershell -File ..." action allocates a visible console for
' every tick (the 3-minute ZargarWatchdog flashed a cmd window on the desktop, 2026-09-08).
' wscript has no console of its own and Run(..., 0) starts PowerShell hidden.
'   wscript.exe //B //Nologo run-hidden.vbs <script.ps1> [args...]
' Exit code = the script's exit code; each run appends one line to run-hidden.log next to this file.
' install-watchdog.ps1 copies this file to C:\ProgramData\Zargar (machine-wide, outside any checkout and
' outside the per-user profile, which an assistant's sandbox virtualizes - a task cannot see files there).
Option Explicit
Dim sh, fso, args, i, cmd, rc, logf, logPath, errText
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
If WScript.Arguments.Count = 0 Then WScript.Quit 2
args = ""
For i = 0 To WScript.Arguments.Count - 1
  args = args & " """ & WScript.Arguments(i) & """"
Next
cmd = sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe" _
  & " -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File" & args
On Error Resume Next
rc = sh.Run(cmd, 0, True)
If Err.Number <> 0 Then
  errText = " ERR " & Err.Number & " " & Err.Description
  rc = 1
End If
Err.Clear
logPath = fso.GetParentFolderName(WScript.ScriptFullName) & "\run-hidden.log"
' keep the log small: one line per 3-minute tick, start over past 512 KB
If fso.FileExists(logPath) Then If fso.GetFile(logPath).Size > 524288 Then fso.DeleteFile logPath
Set logf = fso.OpenTextFile(logPath, 8, True)
If Err.Number = 0 Then
  logf.WriteLine Now & " rc=" & rc & errText & " :: " & cmd
  logf.Close
End If
WScript.Quit rc
