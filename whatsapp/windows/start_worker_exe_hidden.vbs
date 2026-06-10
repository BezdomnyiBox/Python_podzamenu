Set shell = CreateObject("WScript.Shell")
appDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
exePath = appDir & "\PodzamenuWhatsAppWorker.exe"
shell.Run """" & exePath & """", 0, False
