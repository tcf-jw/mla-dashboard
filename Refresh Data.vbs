' Double-click to pull/update MLA data (incremental) with NO terminal window.
' First-ever run: use "Refresh Data (Full Backfill).bat" instead to load all history.
' A popup confirms when the refresh finishes.

Dim fso, dir, sh, rc
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = dir
' True = wait for completion so we can report the result.
rc = sh.Run("cmd /c set PYTHONPATH=src&& python -m mla_dashboard.refresh", 0, True)

If rc = 0 Then
    MsgBox "MLA data refresh complete.", 64, "MLA Dashboard"
Else
    MsgBox "Refresh finished with errors (code " & rc & "). Run the .bat to see details.", 48, "MLA Dashboard"
End If
