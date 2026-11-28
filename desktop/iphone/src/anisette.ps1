# Code a usage unique d'Apple, demande aux composants iCloud installes sur ce PC (comme Sideloadly et AltServer).
# AOSKit.dll est en 32 bits : a lancer avec le PowerShell 32 bits. Sortie : {"md": "...", "md_m": "..."}.
$ErrorActionPreference = "Stop"
$common = "${env:ProgramFiles(x86)}\Common Files\Apple"
if ([IntPtr]::Size -ne 4) { throw "PowerShell 32 bits requis" }
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class Aos {
  [DllImport("kernel32", CharSet=CharSet.Unicode)] public static extern bool SetDllDirectory(string path);
  [DllImport("kernel32", SetLastError=true, CharSet=CharSet.Unicode)] public static extern IntPtr LoadLibraryEx(string path, IntPtr f, uint flags);
  [DllImport("objc.dll", CallingConvention=CallingConvention.Cdecl)] public static extern IntPtr objc_getClass(string n);
  [DllImport("objc.dll", CallingConvention=CallingConvention.Cdecl)] public static extern IntPtr sel_registerName(string n);
  [DllImport("objc.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="objc_msgSend")] public static extern IntPtr Send(IntPtr self, IntPtr sel);
  [DllImport("objc.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="objc_msgSend")] public static extern IntPtr Send1(IntPtr self, IntPtr sel, IntPtr a);
}
"@
[void][Aos]::SetDllDirectory("$common\Apple Application Support")
foreach ($dll in "$common\Apple Application Support\objc.dll", "$common\Apple Application Support\Foundation.dll", "$common\Internet Services\AOSKit.dll") {
  if ([Aos]::LoadLibraryEx($dll, [IntPtr]::Zero, 8) -eq [IntPtr]::Zero) { throw "chargement impossible : $dll" }
}
function Sel($n) { [Aos]::sel_registerName($n) }
function NsString($s) {
  [Aos]::Send1([Aos]::objc_getClass("NSString"), (Sel "stringWithUTF8String:"), [Runtime.InteropServices.Marshal]::StringToHGlobalAnsi($s))
}
$utils = [Aos]::objc_getClass("AOSUtilities")
if ($utils -eq [IntPtr]::Zero) { throw "AOSUtilities introuvable" }
$headers = [Aos]::Send1($utils, (Sel "retrieveOTPHeadersForDSID:"), (NsString "-2"))
if ($headers -eq [IntPtr]::Zero) { throw "aucun code" }
function Header($k) {
  $o = [Aos]::Send1($headers, (Sel "objectForKey:"), (NsString $k))
  if ($o -eq [IntPtr]::Zero) { throw "code absent : $k" }
  [Runtime.InteropServices.Marshal]::PtrToStringAnsi([Aos]::Send($o, (Sel "UTF8String")))
}
@{ md = Header "X-Apple-MD"; md_m = Header "X-Apple-MD-M" } | ConvertTo-Json -Compress
