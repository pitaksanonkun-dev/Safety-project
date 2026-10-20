' ============================================================
'  Document Organizer  —  no-console launcher
' ------------------------------------------------------------
'  Double-click this file to open the app with NO command window.
'  It runs _launch.bat HIDDEN. _launch.bat goes through cmd, which
'  resolves Python reliably (including the Microsoft Store alias
'  that wscript cannot launch directly), installs any missing
'  libraries, then starts the app with pythonw.
'
'  First time on a NEW computer: run  run_gui.bat  once (that window
'  shows the dependency install and any error). After that this
'  launcher opens the app silently.
' ============================================================

Option Explicit
Dim sh, fso, scriptDir, bat

Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = scriptDir
bat = scriptDir & "\_launch.bat"

' 0 = hidden window, False = do not wait
sh.Run """" & bat & """", 0, False

Set sh  = Nothing
Set fso = Nothing
