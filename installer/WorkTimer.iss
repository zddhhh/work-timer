; 下班倒计时安装包。由 scripts\build_release.py 调 ISCC 编译，参数从命令行 /D 传入：
;   AppVersion  版本号（version.py）
;   SourceDir   PyInstaller 目录版输出（含 WorkTimer.exe 与 _internal）
;   OutputDir   安装包输出目录
;   OutputName  安装包文件名（不带 .exe）
;   Win7        定义了就是 Python 3.8 的 Win7 包
; 按用户安装到 %LOCALAPPDATA%\Programs\WorkTimer，不要管理员权限。

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\release\WorkTimer"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif
#ifndef OutputName
  #define OutputName "WorkTimer-Setup"
#endif

#define AppExe "WorkTimer.exe"
#define AppMutex "Local\WorkTimer.SingleInstance"
#define LnkName "下班倒计时.lnk"

[Setup]
; AppId 定了就别改，改了会被当成另一个程序装两份
AppId={{8E3B6C1A-5D2F-4B7E-9A41-6C0F2D7E9B53}
AppName=下班倒计时
AppVersion={#AppVersion}
AppVerName=下班倒计时 {#AppVersion}
AppPublisher=mdslanruo
AppPublisherURL=https://gitcode.com/mdslanruo/work-timer
AppSupportURL=https://gitcode.com/mdslanruo/work-timer/issues
AppUpdatesURL=https://gitcode.com/mdslanruo/work-timer/releases
VersionInfoVersion={#AppVersion}
VersionInfoCompany=mdslanruo
VersionInfoDescription=WorkTimer 下班倒计时 安装程序
VersionInfoProductName=WorkTimer 下班倒计时
VersionInfoProductVersion={#AppVersion}
VersionInfoCopyright=© mdslanruo
PrivilegesRequired=lowest
DefaultDirName={autopf}\WorkTimer
; 手动安装给人选文件夹；检查更新是静默的，会沿用上次装的位置
DisableDirPage=no
DisableWelcomePage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
UsePreviousAppDir=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName=下班倒计时
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 静默更新失败时在 %TEMP% 留一份日志，方便看是哪一步没换成
SetupLogging=yes
; 进程等待在 [Code] 里自己做：OTA 时老进程正在退出，Inno 自带的检测在静默模式下会直接失败
CloseApplications=no
RestartApplications=no
#ifdef Win7
MinVersion=6.1sp1
#else
MinVersion=6.3
#endif

[Languages]
Name: "chs"; MessagesFile: "ChineseSimplified.isl"

[Messages]
chs.WizardSelectDir=安装到哪里
chs.SelectDirDesc=可以改成你想放的文件夹。以后检查更新还会装回这里。
chs.SelectDirLabel3=默认装在当前用户自己的目录，不需要管理员。请不要选「程序文件」或 Program Files（那个要管理员权限）。
chs.SelectDirBrowseLabel=用这个位置就点「下一步」，想换地方点「浏览」。
#ifndef Win7
chs.WindowsVersionNotSupported=这个安装包需要 Windows 8.1 或更高版本。%n%nWindows 7 请到发布页下载 WorkTimer-Win7-Setup.exe。
#endif

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "{code:RunParams}"; Description: "启动下班倒计时"; Flags: nowait postinstall; Check: ShouldLaunch

[UninstallDelete]
; 快捷方式由程序自己按当前 exe 路径维护，安装包不建，只在卸载时清
Type: files; Name: "{userdesktop}\{#LnkName}"
Type: files; Name: "{userprograms}\{#LnkName}"
Type: files; Name: "{userstartup}\WorkTimer.lnk"
Type: filesandordirs; Name: "{localappdata}\WorkTimer"
Type: filesandordirs; Name: "{app}"

[Code]
var
  LegacyTarget: String;
  LegacyMode: Boolean;
  RuntimeBackedUp: Boolean;
  InstallCommitted: Boolean;

function RuntimeDir: String;
begin
  Result := ExpandConstant('{app}\_internal');
end;

function RuntimeBackup: String;
begin
  Result := ExpandConstant('{app}\_internal.old');
end;

function RuntimeReady(const Dir: String): Boolean;
begin
#ifdef Win7
  Result := FileExists(Dir + '\python38.dll') and FileExists(Dir + '\vcruntime140.dll');
#else
  Result := FileExists(Dir + '\python312.dll') and FileExists(Dir + '\vcruntime140.dll');
#endif
end;

procedure RestoreRuntime;
begin
  if not RuntimeBackedUp then
    Exit;
  { 新库没就位就不要留半截，把刚挪走的旧库放回来 }
  DelTree(RuntimeDir, True, True, True);
  if RenameFile(RuntimeBackup, RuntimeDir) then
    RuntimeBackedUp := False;
end;

procedure RelaunchCurrent;
var
  Code: Integer;
begin
  ShellExec('', ExpandConstant('{app}\{#AppExe}'), '', ExpandConstant('{app}'), SW_SHOWNORMAL, ewNoWait, Code);
end;

function HasParam(const Flag: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Flag) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

function ParamAfter(const Flag: String): String;
var
  I: Integer;
begin
  Result := '';
  for I := 1 to ParamCount - 1 do
    if CompareText(ParamStr(I), Flag) = 0 then
    begin
      Result := ParamStr(I + 1);
      Exit;
    end;
end;

procedure WaitAppClosed(Seconds: Integer);
var
  N: Integer;
begin
  N := 0;
  while CheckForMutexes('{#AppMutex}') and (N < Seconds * 4) do
  begin
    Sleep(250);
    N := N + 1;
  end;
end;

{ 1.3.34 及更早的单文件版自更新时，把下载到的文件当成新 exe 拉起（隐藏窗口、不带静默参数）：
    - 原地替换：带 --ota-replace --wait-pid ... --target <老 exe>
    - 微信目录搬家：拷成 %LOCALAPPDATA%\WorkTimer\WorkTimer.exe 后无参数运行
  安装包运行时独占锁着自身文件，没法再拉起一份静默的；只能在本进程里跳过所有页面直接装。 }
function LegacyLaunchTarget: String;
begin
  Result := '';
  if HasParam('--ota-replace') then
    Result := ParamAfter('--target')
  else if CompareText(ExpandConstant('{srcexe}'), ExpandConstant('{localappdata}\WorkTimer\{#AppExe}')) = 0 then
    Result := ExpandConstant('{srcexe}');
end;

{ /WTNOLAUNCH=1 只给本地测试用：装完不拉起程序 }
function ShouldLaunch: Boolean;
begin
  Result := ExpandConstant('{param:WTNOLAUNCH|0}') = '0';
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  LegacyTarget := LegacyLaunchTarget;
  LegacyMode := LegacyTarget <> '';
  if not LegacyMode then
    LegacyTarget := ExpandConstant('{param:WTLEGACY}');
  Log('WorkTimer legacy mode: ' + IntToStr(Ord(LegacyMode)) + ', cleanup target: ' + LegacyTarget);
  if WizardSilent or LegacyMode then
  begin
    { OTA：老进程刚发起更新正在退出。等不到就中止，绝不能接着去动 _internal。 }
    WaitAppClosed(15);
    if CheckForMutexes('{#AppMutex}') then
    begin
      Log('WorkTimer still running after wait, abort before touching files');
      Result := False;
    end;
    Exit;
  end;
  while CheckForMutexes('{#AppMutex}') do
    if MsgBox('下班倒计时正在运行。' + #13#10 + '请右键它选「退出」，然后点「重试」继续安装。',
              mbError, MB_RETRYCANCEL) <> IDRETRY then
    begin
      Result := False;
      Exit;
    end;
end;

{ 老版本拉起时窗口是隐藏的：所有页面都跳过（含完成页，postinstall 照常执行），不能停在任何需要点的地方 }
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := LegacyMode;
end;

function RunParams(Param: String): String;
begin
  Result := '';
  if LegacyTarget <> '' then
    Result := '--legacy-cleanup "' + LegacyTarget + '"';
end;

function InitializeUninstall: Boolean;
begin
  { 应用内卸载会先拉起本程序再退出，等它退干净 }
  WaitAppClosed(15);
  Result := True;
  if CheckForMutexes('{#AppMutex}') then
  begin
    if not UninstallSilent then
      MsgBox('下班倒计时还在运行，请先在托盘或右键菜单里退出它，再卸载。', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    { 上次换到一半：能用的库在 .old，残缺的在 _internal }
    if (not RuntimeReady(RuntimeDir)) and RuntimeReady(RuntimeBackup) then
    begin
      DelTree(RuntimeDir, True, True, True);
      RenameFile(RuntimeBackup, RuntimeDir);
    end;
    if DirExists(RuntimeBackup) then
      DelTree(RuntimeBackup, True, True, True);
    if DirExists(RuntimeDir) then
    begin
      if not RenameFile(RuntimeDir, RuntimeBackup) then
      begin
        Log('cannot move _internal aside, leave the installed files untouched');
        if not WizardSilent then
          MsgBox('更新没能换掉正在使用的文件，已保持当前版本。', mbError, MB_OK);
        RelaunchCurrent;
        Abort;
      end;
      RuntimeBackedUp := True;
    end;
  end
  else if CurStep = ssPostInstall then
  begin
    if RuntimeReady(RuntimeDir) then
    begin
      InstallCommitted := True;
      DelTree(RuntimeBackup, True, True, True);
      RuntimeBackedUp := False;
    end
    else
      RestoreRuntime;
  end;
end;

procedure DeinitializeSetup;
begin
  if RuntimeBackedUp and not InstallCommitted then
  begin
    RestoreRuntime;
    if not RuntimeBackedUp then
      RelaunchCurrent;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'WorkTimer');
  Data := ExpandConstant('{userappdata}\WorkTimer');
  if DirExists(Data) and not UninstallSilent then
    if MsgBox('要同时删除日程、备忘和设置吗？' + #13#10 + '（不删的话，以后重装还能接着用）',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(Data, True, True, True);
end;
