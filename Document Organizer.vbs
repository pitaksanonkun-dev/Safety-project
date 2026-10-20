' ============================================================
'  Document Organizer  —  no-console launcher
' ------------------------------------------------------------
'  Double-click this file to open the vault with NO command
'  window: it runs the program with pythonw.exe (the windowless
'  Python), launched hidden, so only the app window appears.
'
'  gui.py anchors its data folder to its own location, so the
'  working directory does not matter here.
'
'  If nothing opens:
'    1) Run  run_gui.bat  once (that window installs the needed
'       libraries and shows any error message).
'    2) Then use this launcher for everyday opening.
' ============================================================

Option Explicit
Dim sh, fso, scriptDir, guiPath

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
guiPath   = scriptDir & "\gui.py"

' Invoke pythonw BY NAME so Windows resolves it (including the
' Microsoft Store launcher). 0 = hidden window, False = don't wait.
sh.Run "pythonw.exe """ & guiPath & """", 0, False

Set sh  = Nothing
Set fso = Nothing
