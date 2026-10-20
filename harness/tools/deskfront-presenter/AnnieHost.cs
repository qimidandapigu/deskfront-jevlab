using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Drawing.Drawing2D;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// Resolve the same native caption anchor before the first painted portrait.
// There is no estimated startup position: an unavailable layout stays hidden.
static class PortraitLayout {
  public static bool TryGetBounds(int clientWidth,int clientHeight,double[] subtitle,double[] viewport,out Rectangle result) {
    result=Rectangle.Empty;
    if(clientWidth<1||clientHeight<1||subtitle==null||subtitle.Length!=4||viewport==null||viewport.Length!=2)return false;
    foreach(double value in subtitle)if(double.IsNaN(value)||double.IsInfinity(value))return false;
    foreach(double value in viewport)if(double.IsNaN(value)||double.IsInfinity(value))return false;
    if(viewport[0]<=0||viewport[1]<=0||subtitle[0]<0||subtitle[1]<0||subtitle[2]<=0||subtitle[3]<=0)return false;
    if(subtitle[0]+subtitle[2]>viewport[0]+1||subtitle[1]+subtitle[3]>viewport[1]+1)return false;
    int left=(int)Math.Round(subtitle[0]*clientWidth/viewport[0]);
    int bottom=(int)Math.Round((subtitle[1]+subtitle[3])*clientHeight/viewport[1]);
    int available=left-12;
    if(available<1)return false;
    int portraitWidth=Math.Min(Math.Min(220,Math.Max(140,clientWidth/8)),available);
    int portraitHeight=Math.Min(clientHeight,Math.Max(1,(int)(portraitWidth*1.25)));
    result=new Rectangle(Math.Max(0,left-portraitWidth-8),Math.Max(0,Math.Min(clientHeight-portraitHeight,bottom-portraitHeight)),portraitWidth,portraitHeight);
    return true;
  }
}

// External Harness component. The form is a real WS_CHILD of the native game.
// It owns no gameplay state, model key or independent audio playback.
class AnnieWindow : Form {
  [DllImport("user32.dll")] static extern IntPtr SetParent(IntPtr child, IntPtr parent);
  [DllImport("user32.dll")] static extern IntPtr GetParent(IntPtr child);
  [DllImport("user32.dll")] static extern bool IsWindow(IntPtr window);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr window);
  [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr window, out Rect rect);
  [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int w, int h, uint flags);
  [DllImport("user32.dll", EntryPoint="GetWindowLongPtrW")] static extern IntPtr GetWindowLongPtr(IntPtr window, int index);
  [DllImport("user32.dll", EntryPoint="SetWindowLongPtrW")] static extern IntPtr SetWindowLongPtr(IntPtr window, int index, IntPtr value);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc proc, IntPtr parameter);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr window,int command);
  [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr awareness);
  [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr CreateToolhelp32Snapshot(uint flags,uint pid);
  [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern bool Process32First(IntPtr snapshot,ref ProcessEntry entry);
  [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern bool Process32Next(IntPtr snapshot,ref ProcessEntry entry);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
  [DllImport("user32.dll",SetLastError=true)] static extern bool UpdateLayeredWindow(IntPtr window,IntPtr screen,IntPtr destination,ref PixelSize size,IntPtr source,ref PixelPoint origin,uint color,ref Blend blend,uint flags);
  [DllImport("user32.dll")] static extern IntPtr GetDC(IntPtr window);
  [DllImport("user32.dll")] static extern int ReleaseDC(IntPtr window,IntPtr dc);
  [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleDC(IntPtr dc);
  [DllImport("gdi32.dll")] static extern bool DeleteDC(IntPtr dc);
  [DllImport("gdi32.dll")] static extern IntPtr SelectObject(IntPtr dc,IntPtr value);
  [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr value);
  [DllImport("gdi32.dll")] static extern IntPtr CreateDIBSection(IntPtr dc,ref BitmapInfo info,uint usage,out IntPtr pixels,IntPtr section,uint offset);
  [StructLayout(LayoutKind.Sequential)] struct PixelPoint { public int x,y; }
  [StructLayout(LayoutKind.Sequential)] struct PixelSize { public int width,height; }
  [StructLayout(LayoutKind.Sequential,Pack=1)] struct Blend { public byte operation,flags,opacity,alpha; }
  [StructLayout(LayoutKind.Sequential)] struct BitmapInfo {
    public uint size;public int width,height;public ushort planes,bits;public uint compression,imageSize;public int xppm,yppm;public uint colors,important;
  }
  [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct ProcessEntry {
    public uint size,usage,pid;public IntPtr heap;public uint module,threads,parent;public int priority;public uint flags;
    [MarshalAs(UnmanagedType.ByValTStr,SizeConst=260)] public string exe;
  }
  delegate bool EnumProc(IntPtr window, IntPtr parameter);
  [StructLayout(LayoutKind.Sequential)] struct Rect { public int Left, Top, Right, Bottom; }
  readonly int pid; readonly string url, folder; readonly JavaScriptSerializer json = new JavaScriptSerializer();
  readonly WebView2 browser = new WebView2(); readonly Timer timer = new Timer();
  readonly Form renderHost = new Form();
  IntPtr parent; bool attached, initialized, subtitleVisible; int width, height,nativePid,layoutRevision;
  double[] subtitleRect,viewportSize;
  DateTime lastPresentation=DateTime.MinValue;
  Rectangle lastBounds=Rectangle.Empty;
  bool lastVisible,portraitShown;
  string presentationPhase="hidden",lastPhase="";
  string presentationEntryId,lastEntryId;
  string capturedSpeech;
  string capturedAlpha;
  int alphaFrames;
  protected override bool ShowWithoutActivation { get { return true; } }
  // Per-pixel alpha, non-activating and input-transparent. The browser itself
  // lives offscreen: a normal WebView HWND would cover the layered bitmap.
  protected override CreateParams CreateParams { get { var p=base.CreateParams; p.ExStyle|=0x08080020; return p; } }
  void Record(string kind, object data) {
    try { File.AppendAllText(Path.Combine(folder,"host.jsonl"),json.Serialize(new { type=kind, time=DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), data=data })+"\n",Encoding.UTF8); } catch {}
  }
  public AnnieWindow(int process, string address, string output) {
    pid=process;url=address;folder=output;Directory.CreateDirectory(folder);
    FormBorderStyle=FormBorderStyle.None;ShowInTaskbar=false;
    StartPosition=FormStartPosition.Manual;Location=new Point(-32000,-32000);
    AutoScaleMode=AutoScaleMode.None;ClientSize=new Size(144,170);browser.Dock=DockStyle.Fill;
    renderHost.FormBorderStyle=FormBorderStyle.None;renderHost.ShowInTaskbar=false;
    renderHost.StartPosition=FormStartPosition.Manual;renderHost.Location=new Point(-32000,-32000);
    renderHost.AutoScaleMode=AutoScaleMode.None;renderHost.ClientSize=ClientSize;
    browser.DefaultBackgroundColor=Color.Transparent;renderHost.Controls.Add(browser);
    timer.Interval=400;timer.Tick+=(s,e)=>AttachAndPosition();timer.Start();
  }
  IntPtr FindGame() {
    // Frozen Deskfront.exe owns the SDK, while its DeskfrontGame.exe child owns
    // the actual window. Resolve only this launcher's known game child.
    nativePid=pid;var snapshot=CreateToolhelp32Snapshot(2,0);
    if(snapshot!=new IntPtr(-1)){
      var entry=new ProcessEntry();entry.size=(uint)Marshal.SizeOf(typeof(ProcessEntry));
      if(Process32First(snapshot,ref entry)){do{if(entry.parent==(uint)pid&&(string.Equals(entry.exe,"DeskfrontGame.exe",StringComparison.OrdinalIgnoreCase)||(entry.exe.StartsWith("Godot_",StringComparison.OrdinalIgnoreCase)&&entry.exe.EndsWith("_win64.exe",StringComparison.OrdinalIgnoreCase)))){nativePid=(int)entry.pid;break;}}while(Process32Next(snapshot,ref entry));}
      CloseHandle(snapshot);
    }
    IntPtr found=IntPtr.Zero;
    EnumWindows((window,p)=> { uint candidate;GetWindowThreadProcessId(window,out candidate);Rect r;
      if(candidate==(uint)nativePid&&IsWindowVisible(window)&&GetClientRect(window,out r)&&r.Right>200&&r.Bottom>200){found=window;return false;}return true;
    },IntPtr.Zero);return found;
  }
  void AttachAndPosition() {
    try { if(Process.GetProcessById(pid).HasExited){Close();return;} } catch { Close();return; }
    if(parent==IntPtr.Zero)parent=FindGame();
    if(parent==IntPtr.Zero)return;
    if(!IsWindow(parent)){Close();return;}
    if(!attached){
      ShowWindow(Handle,0);
      long style=GetWindowLongPtr(Handle,-16).ToInt64();style=(style&~0x80000000L)|0x40000000L;
      SetWindowLongPtr(Handle,-16,new IntPtr(style));SetParent(Handle,parent);
      if(GetParent(Handle)!=parent){Record("embed-failed",new { parent=parent.ToInt64() });Close();return;}
      attached=true;Record("embedded",new { bridgePid=pid, gamePid=nativePid, parentHwnd=parent.ToInt64(), childHwnd=Handle.ToInt64(), isChild=true });
      InitializeBrowser();
    }
    if(IsIconic(parent)){lastVisible=false;HidePortrait();return;}
    Rect bounds;if(!GetClientRect(parent,out bounds)){lastVisible=false;HidePortrait();return;}
    Rectangle next;
    bool exact=PortraitLayout.TryGetBounds(bounds.Right,bounds.Bottom,subtitleRect,viewportSize,out next);
    bool visible=exact && subtitleVisible && (DateTime.UtcNow-lastPresentation).TotalMilliseconds<1600;
    // The game owns the caption. Fit its portrait in the free space immediately
    // to the left and align the bottom edges, including DPI/viewport scaling.
    bool entryChanged=presentationEntryId!=lastEntryId;
    if(!visible||!lastVisible||entryChanged||next.Size!=lastBounds.Size)HidePortrait();
    if(next!=lastBounds || visible!=lastVisible || presentationPhase!=lastPhase || entryChanged){
      if(exact){
        if(width!=next.Width||height!=next.Height)layoutRevision++;
        width=next.Width;height=next.Height;
        if(renderHost.ClientSize.Width!=width||renderHost.ClientSize.Height!=height)renderHost.ClientSize=new Size(width,height);
        // Position without SWP_SHOWWINDOW. PresentAlpha reveals the first fresh
        // frame only after this final client-space position has been installed.
        SetWindowPos(Handle,new IntPtr(0),next.X,next.Y,width,height,0x0010);
      }
      Record("subtitle-layout",new {visible=visible,phase=presentationPhase,placement="left-of-native-subtitle",exact=exact,portrait=new[]{next.X,next.Y,next.Width,next.Height},subtitle=subtitleRect,viewport=viewportSize,client=new[]{bounds.Right,bounds.Bottom},painted=portraitShown});
      lastBounds=next;lastVisible=visible;lastPhase=presentationPhase;lastEntryId=presentationEntryId;
    }
    // WebView CSS pixels vary with Windows scale. Give the renderer explicit
    // native frame dimensions and reject any image from a previous layout.
    if(exact&&browser.CoreWebView2!=null)browser.CoreWebView2.PostWebMessageAsJson(json.Serialize(new {action="frame-layout",revision=layoutRevision,width=width,height=height}));
  }
  void HidePortrait(){if(portraitShown){ShowWindow(Handle,0);portraitShown=false;}}
  void ReceiveAlphaFrame(System.Collections.Generic.Dictionary<string,object> message){
    var renderSize=Numbers(message,"renderSize",2);
    var entry=Convert.ToString(message["entryId"]);
    object revision;int frameRevision=message.TryGetValue("layoutRevision",out revision)?Convert.ToInt32(revision):-1;
    if(lastVisible && entry==presentationEntryId && frameRevision==layoutRevision && renderSize!=null && renderSize[0]==width && renderSize[1]==height)PresentAlpha(Convert.ToString(message["png"]),entry);
  }
  double[] Numbers(System.Collections.Generic.Dictionary<string,object> message,string key,int count){
    object value;if(!message.TryGetValue(key,out value))return null;
    var array=value as object[];if(array==null||array.Length!=count)return null;
    var result=new double[count];for(int i=0;i<count;i++){result[i]=Convert.ToDouble(array[i]);if(double.IsNaN(result[i])||double.IsInfinity(result[i]))return null;}
    return result;
  }
  async void InitializeBrowser() {
    if(initialized)return;initialized=true;
    try {
      // WS_EX_NOACTIVATE prevents the offscreen renderer from taking game focus.
      SetWindowLongPtr(renderHost.Handle,-20,new IntPtr(GetWindowLongPtr(renderHost.Handle,-20).ToInt64()|0x08000000L));
      renderHost.Show();
      var env=await CoreWebView2Environment.CreateAsync(null,Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Deskfront","AnnieWebView"));
      await browser.EnsureCoreWebView2Async(env);
      browser.CoreWebView2.Settings.AreDevToolsEnabled=false;browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled=false;
      browser.CoreWebView2.Settings.IsStatusBarEnabled=false;
      var allowed=new Uri(url);
      browser.CoreWebView2.NavigationStarting+=(s,e)=> { Uri next;if(!Uri.TryCreate(e.Uri,UriKind.Absolute,out next)||next.Scheme!="http"||next.Host!="127.0.0.1"||next.Port!=allowed.Port)e.Cancel=true; };
      browser.CoreWebView2.NewWindowRequested+=(s,e)=>e.Handled=true;
      browser.CoreWebView2.PermissionRequested+=(s,e)=>e.State=CoreWebView2PermissionState.Deny;
      browser.CoreWebView2.WebMessageReceived+=async(s,e)=> {
        try {
          var message=json.DeserializeObject(e.WebMessageAsJson) as System.Collections.Generic.Dictionary<string,object>;
          if(message==null)return;
          object action;if(!message.TryGetValue("action",out action))return;
          if(action.ToString()=="rgba-frame"){
            try{ReceiveAlphaFrame(message);}
            finally{browser.CoreWebView2.PostWebMessageAsJson("{\"action\":\"frame-presented\"}");}
            return;
          }
          if(action.ToString()=="presentation"){
            subtitleVisible=Convert.ToBoolean(message["visible"]);lastPresentation=DateTime.UtcNow;
            object phase;presentationPhase=message.TryGetValue("phase",out phase)?Convert.ToString(phase):"hidden";
            object entry;presentationEntryId=message.TryGetValue("entryId",out entry)?Convert.ToString(entry):null;
            subtitleRect=Numbers(message,"subtitleRect",4);viewportSize=Numbers(message,"viewportSize",2);
            AttachAndPosition();return;
          }
          Record("page-"+action.ToString(),message);
          if(action.ToString()=="ready")await CaptureFrame("presenter-ready.png");
          if(action.ToString()=="decision")await CaptureFrame("presenter-speaking.png");
          if(action.ToString()=="playback" && Convert.ToBoolean(message["speaking"]) && Convert.ToDouble(message["mouthOpen"])>.05){
            var entry=Convert.ToString(message["entryId"]);
            if(capturedSpeech!=entry){capturedSpeech=entry;await CaptureFrame("presenter-mouth.png");}
          }
        }catch(Exception error){Record("page-message-error",new { error=error.GetType().Name });}
      };
      browser.Source=allowed;Record("renderer-started",new { url=url,runtime=CoreWebView2Environment.GetAvailableBrowserVersionString() });
    }catch(Exception error){Record("renderer-failed",new { error=error.GetType().Name,message=error.Message });Close();}
  }
  async Task CaptureFrame(string name) {
    try { using(var f=File.Create(Path.Combine(folder,name)))await browser.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png,f); }catch {}
  }
  void PresentAlpha(string encoded,string entry){
    if(!lastVisible||lastBounds.IsEmpty||entry!=presentationEntryId)return;
    if(encoded.Length>1024*1024)throw new InvalidDataException("portrait-frame-too-large");
    var started=Stopwatch.StartNew();var png=Convert.FromBase64String(encoded);
    using(var input=new MemoryStream(png))using(var decoded=new Bitmap(input))using(var pixels=new Bitmap(width,height,PixelFormat.Format32bppPArgb)){
      using(var g=Graphics.FromImage(pixels)){g.CompositingMode=CompositingMode.SourceCopy;g.InterpolationMode=InterpolationMode.HighQualityBilinear;g.DrawImage(decoded,new Rectangle(0,0,width,height));}
      var data=pixels.LockBits(new Rectangle(0,0,width,height),ImageLockMode.ReadOnly,PixelFormat.Format32bppPArgb);
      IntPtr screen=GetDC(IntPtr.Zero),dc=CreateCompatibleDC(screen),bits,bitmap=IntPtr.Zero,previous=IntPtr.Zero;
      try{
        var info=new BitmapInfo{size=40,width=width,height=-height,planes=1,bits=32};
        bitmap=CreateDIBSection(screen,ref info,0,out bits,IntPtr.Zero,0);
        if(bitmap==IntPtr.Zero)throw new InvalidOperationException("portrait-dib-failed");
        var row=new byte[width*4];int transparent=0,partial=0,opaque=0;
        for(int y=0;y<height;y++){
          Marshal.Copy(IntPtr.Add(data.Scan0,y*data.Stride),row,0,row.Length);
          for(int x=3;x<row.Length;x+=4){if(row[x]==0)transparent++;else if(row[x]==255)opaque++;else partial++;}
          Marshal.Copy(row,0,IntPtr.Add(bits,y*row.Length),row.Length);
        }
        previous=SelectObject(dc,bitmap);var size=new PixelSize{width=width,height=height};var origin=new PixelPoint();var blend=new Blend{opacity=255,alpha=1};
        if(!UpdateLayeredWindow(Handle,screen,IntPtr.Zero,ref size,dc,ref origin,0,ref blend,2))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        if(!portraitShown){ShowWindow(Handle,4);portraitShown=true;Record("portrait-revealed",new {entryId=entry,phase=presentationPhase,portrait=new[]{lastBounds.X,lastBounds.Y,width,height},afterFreshAlpha=true});}
        alphaFrames++;
        if(capturedAlpha!=entry&&opaque>0&&transparent>0){capturedAlpha=entry;pixels.Save(Path.Combine(folder,"presenter-transparent.png"),ImageFormat.Png);}
        if(alphaFrames==1||alphaFrames%40==0)Record("alpha-presented",new {frames=alphaFrames,transparentPixels=transparent,partialPixels=partial,opaquePixels=opaque,paintMs=started.Elapsed.TotalMilliseconds,layeredChild=true});
      }finally{
        if(previous!=IntPtr.Zero)SelectObject(dc,previous);if(bitmap!=IntPtr.Zero)DeleteObject(bitmap);if(dc!=IntPtr.Zero)DeleteDC(dc);if(screen!=IntPtr.Zero)ReleaseDC(IntPtr.Zero,screen);pixels.UnlockBits(data);
      }
    }
  }
  protected override void OnFormClosed(FormClosedEventArgs e){timer.Stop();renderHost.Close();renderHost.Dispose();Record("closed",new { gamePid=pid });base.OnFormClosed(e);}
  [STAThread] static void Main(string[] args) {
    if(args.Length!=3)return;int target;Uri address;
    if(!int.TryParse(args[0],out target)||target<1||!Uri.TryCreate(args[1],UriKind.Absolute,out address)||address.Scheme!="http"||address.Host!="127.0.0.1"||address.AbsolutePath!="/runtime/deskfront/annie")return;
    try{SetProcessDpiAwarenessContext(new IntPtr(-4));}catch{}
    Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
    Application.Run(new AnnieWindow(target,address.ToString(),Path.GetFullPath(args[2])));
  }
}
