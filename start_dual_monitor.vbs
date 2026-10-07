Option Explicit
Dim sh, fso, base, ps1, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = fso.BuildPath(base, "start_dual.ps1")

cmd = "powershell.exe -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File """ & ps1 & """"
sh.CurrentDirectory = base
sh.Run cmd, 0, False
