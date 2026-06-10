' Запуск воркера без консольного окна (для Планировщика заданий)
Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\start_worker.bat"
shell.Run """" & batPath & """", 0, False
