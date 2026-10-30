# Genere res/drawable-nodpi/icon.png (logo officiel alyra.) et banner.png (bandeau TV 320x180).
# Entree : D:\Code\_assets\alyra\icon-512.png (web/icons/icon-512.png du repo, branche master).
Add-Type -AssemblyName System.Drawing
$root = $PSScriptRoot
$logo = [System.Drawing.Image]::FromFile('D:\Code\_assets\alyra\icon-512.png')
$pfc = New-Object System.Drawing.Text.PrivateFontCollection
$pfc.AddFontFile("$root\assets\fonts\InterTight-Bold.ttf")
$fam = $pfc.Families[0]
New-Item -ItemType Directory -Force "$root\res\drawable-nodpi" | Out-Null

# icone carree
$b = New-Object System.Drawing.Bitmap 256, 256
$g = [System.Drawing.Graphics]::FromImage($b)
$g.InterpolationMode = 'HighQualityBicubic'
$g.DrawImage($logo, 0, 0, 256, 256)
$b.Save("$root\res\drawable-nodpi\icon.png", [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $b.Dispose()

# banniere : fond graphite + taches, logo, nom
$w = 320; $h = 180
$b = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($b)
$g.SmoothingMode = 'AntiAlias'; $g.TextRenderingHint = 'AntiAliasGridFit'; $g.InterpolationMode = 'HighQualityBicubic'
$g.Clear([System.Drawing.ColorTranslator]::FromHtml('#0e1014'))
function Blob($cx, $cy, $r, $a, $r8, $g8, $b8) {
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddEllipse($cx - $r, $cy - $r, 2 * $r, 2 * $r)
    $br = New-Object System.Drawing.Drawing2D.PathGradientBrush $path
    $br.CenterColor = [System.Drawing.Color]::FromArgb($a, $r8, $g8, $b8)
    $br.SurroundColors = @([System.Drawing.Color]::FromArgb(0, $r8, $g8, $b8))
    $g.FillEllipse($br, $cx - $r, $cy - $r, 2 * $r, 2 * $r)
}
Blob 20 -20 200 215 61 90 153
Blob 330 30 170 180 122 74 126
Blob 130 200 190 128 185 133 87
$g.DrawImage($logo, 38, 50, 76, 76)
$f = New-Object System.Drawing.Font $fam, 44, ([System.Drawing.FontStyle]::Regular), ([System.Drawing.GraphicsUnit]::Pixel)
$white = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#f4f6f8'))
$g.DrawString('alyra.', $f, $white, 118, 62)
$b.Save("$root\res\drawable-nodpi\banner.png", [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $b.Dispose(); $logo.Dispose()
