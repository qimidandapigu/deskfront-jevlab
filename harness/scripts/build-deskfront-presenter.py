"""Build the Windows WebView2 child-window host with the installed .NET compiler."""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, urllib.request, zipfile

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'tools/deskfront-presenter/bin')
a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
version='1.0.3856.49'
cache=ROOT/'output/dependencies';cache.mkdir(parents=True,exist_ok=True)
package=cache/f'microsoft.web.webview2.{version}.nupkg'
if not package.exists():
    with urllib.request.urlopen(f'https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/{version}/microsoft.web.webview2.{version}.nupkg',timeout=60) as response:
        package.write_bytes(response.read())
expected='bc0f76eb911b569838dc4aa8f8d325269b966bedb592863d26211aef3a099f1a'
if hashlib.sha256(package.read_bytes()).hexdigest()!=expected:raise ValueError('WebView2 dependency checksum mismatch')
with zipfile.ZipFile(package) as z:
    for name in ['Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll']:
        (out/name).write_bytes(z.read('lib/net462/'+name))
    (out/'WebView2Loader.dll').write_bytes(z.read('runtimes/win-x64/native/WebView2Loader.dll'))
    for name in z.namelist():
        if name.lower().endswith('license.txt'):(out/'WEBVIEW2-LICENSE.txt').write_bytes(z.read(name));break
compiler=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64',f'/out:{out}/DeskfrontAnnieHost.exe',
    f'/win32manifest:{ROOT}/tools/deskfront-presenter/app.manifest',
    '/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Web.Extensions.dll',
    f'/r:{out}/Microsoft.Web.WebView2.Core.dll',f'/r:{out}/Microsoft.Web.WebView2.WinForms.dll',
    str(ROOT/'tools/deskfront-presenter/AnnieHost.cs')],check=True)
(out/'build.json').write_text(json.dumps(dict(sdkVersion=version,dependencySHA256=hashlib.sha256(package.read_bytes()).hexdigest(),
    executable='DeskfrontAnnieHost.exe',kind='native-game-child-window',requires='Windows .NET Framework 4.6.2+ and Edge WebView2 Runtime'),indent=2),encoding='utf-8')
print(json.dumps(dict(host=str(out/'DeskfrontAnnieHost.exe'),sdkVersion=version)))
