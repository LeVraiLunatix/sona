# Genere res/drawable-nodpi/icon.png et banner.png (police Source Serif 4, couleurs Encre)
Add-Type -AssemblyName System.Drawing
$root = $PSScriptRoot
$pfc = New-Object System.Drawing.Text.PrivateFontCollection
$pfc.AddFontFile("$root\assets\fonts\SourceSerif4-SemiBold.ttf")
$fam = $pfc.Families[0]
function Make($w, $h, $size, $out, $dots) {
    $b = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($b)
    $g.SmoothingMode = 'AntiAlias'; $g.TextRenderingHint = 'AntiAlias'
    $g.Clear([System.Drawing.ColorTranslator]::FromHtml('#121112'))
    $cy = [System.Drawing.ColorTranslator]::FromHtml('#28B8E0')
    $mg = [System.Drawing.ColorTranslator]::FromHtml('#FF4FA0')
    $r = [int]($h * 0.34)
    $g.FillEllipse((New-Object System.Drawing.SolidBrush $cy), [int]($w*0.5 - $r*1.1), [int]($h*0.5 - $r), 2*$r, 2*$r)
    $g.FillEllipse((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(205, $mg))), [int]($w*0.5 - $r*0.1), [int]($h*0.5 - $r*0.9), 2*$r, 2*$r)
    $f = New-Object System.Drawing.Font $fam, $size, ([System.Drawing.FontStyle]::Regular), ([System.Drawing.GraphicsUnit]::Pixel)
    $sf = New-Object System.Drawing.StringFormat; $sf.Alignment = 'Center'; $sf.LineAlignment = 'Center'
    $rect = New-Object System.Drawing.RectangleF 0, 0, $w, $h
    if ($dots) { $g.DrawString('Alyra', $f, (New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#F4F1EF'))), $rect, $sf) }
    else { $g.DrawString('A', $f, (New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#121112'))), $rect, $sf) }
    $b.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $b.Dispose()
}
New-Item -ItemType Directory -Force "$root\res\drawable-nodpi" | Out-Null
Make 320 180 64 "$root\res\drawable-nodpi\banner.png" $true
Make 256 256 150 "$root\res\drawable-nodpi\icon.png" $false
