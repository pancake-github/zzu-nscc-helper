; 安装器只部署所选组件，平台联网和Clash应用仍由使用者主动操作。
#include "..\build\hashes.iss"
#ifdef Online
  #define InstallerKind "online"
#else
  #define InstallerKind "offline"
#endif
[Setup]
AppId={{B632E1EA-7D56-45E9-AC56-557839E0DC05}
AppName=郑州超算助手
AppVersion={#ReleaseVersion}
AppPublisher=pancake-github
AppPublisherURL=https://github.com/pancake-github/zzu-nscc-helper
DefaultDirName={localappdata}\Programs\ZZU-NSCC-Helper
DefaultGroupName=郑州超算助手
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
OutputDir={#OutputFolder}
OutputBaseFilename=zzu-nscc-helper-{#InstallerKind}-{#ReleaseVersion}-x64
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
ArchiveExtraction=full
WizardStyle=modern
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\zzu-nscc-helper.exe
; 同一产品升级保留组件选择；不为使用者添加开机启动。
[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
[Types]
Name: "full"; Description: "全部安装"
Name: "keepaliveonly"; Description: "仅 VPN 保活"
Name: "routingonly"; Description: "仅 Clash 分流"
Name: "sftponly"; Description: "仅 SFTP 传输"
Name: "custom"; Description: "自定义"; Flags: iscustom
[Components]
Name: "keepalive"; Description: "VPN 保活和 Edge 标签页连接器"; Types: full keepaliveonly
Name: "routing"; Description: "Clash 检测、分流、备份与回滚"; Types: full routingonly
Name: "sftp"; Description: "SFTP 上传、下载与校验"; Types: full sftponly
[Files]
#include "..\build\payloads.iss"
[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked
[Icons]
Name: "{group}\郑州超算助手"; Filename: "{app}\zzu-nscc-helper.exe"
Name: "{autodesktop}\郑州超算助手"; Filename: "{app}\zzu-nscc-helper.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\zzu-nscc-helper.exe"; Description: "打开郑州超算助手"; Flags: nowait postinstall skipifsilent unchecked
[Code]
var DownloadPage: TDownloadWizardPage; PayloadCache: String; { 仅为选中组件显示下载进度。 }
function Chosen: String; { 安装清单与GUI使用相同的三个编号。 }
begin
  Result := WizardSelectedComponents(False);
end;
function IdleAt(const Root: String): Boolean; { 不强制结束助手或浏览器。 }
var Code: Integer; Tool: String;
begin
  Tool := AddBackslash(Root) + 'zzu-nscc-maintenance.exe';
  Result := not FileExists(Tool);
  if not Result then Result := Exec(Tool, 'check-idle', Root, SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;
procedure Fetch(const UnitName, Digest: String); { 不接受远程提供的任意校验值。 }
  var Target, Source: String;
  begin
    if (UnitName <> 'core') and not WizardIsComponentSelected(UnitName) then Exit;
    Target := ExpandConstant('{tmp}\') + UnitName + '.zip';
    if PayloadCache <> '' then begin { 支持已校验的离线缓存及相同安装器的自动验收。 }
      Source := AddBackslash(PayloadCache) + UnitName + '.zip';
      if not FileCopy(Source, Target, False) then RaiseException('无法读取组件缓存。');
      if CompareText(GetSHA256OfFile(Target), Digest) <> 0 then RaiseException('组件缓存 SHA-256 不符，安装已停止。');
    end else begin
#ifdef Online
      DownloadPage.Add('https://github.com/pancake-github/zzu-nscc-helper/releases/download/{#ReleaseTag}/' + UnitName + '.zip', UnitName + '.zip', Digest);
#else
      ExtractTemporaryFile(UnitName + '.zip');
      if CompareText(GetSHA256OfFile(Target), Digest) <> 0 then RaiseException('内置组件 SHA-256 不符，安装已停止。');
#endif
    end;
  end;
function PrepareToInstall(var NeedsRestart: Boolean): String; { 全部下载和校验完成后才写入安装目录。 }
begin
  Result := '';
  if Chosen = '' then begin Result := '请至少选择一项安装组件。'; Exit; end;
  if not IdleAt(ExpandConstant('{app}')) then begin Result := '请先停止任务并退出当前助手，再继续安装。'; Exit; end;
  try
    PayloadCache := ExpandConstant('{param:PAYLOADDIR|}');
    DownloadPage.Clear;
    Fetch('core', '{#Payload_core}');
    Fetch('keepalive', '{#Payload_keepalive}');
    Fetch('routing', '{#Payload_routing}');
    Fetch('sftp', '{#Payload_sftp}');
#ifdef Online
    if PayloadCache = '' then begin
      DownloadPage.Show;
      try DownloadPage.Download; finally DownloadPage.Hide; end;
    end;
#endif
  except
    Result := GetExceptionMessage;
  end;
end;
procedure InitializeWizard; { 普通安装过程不调用平台、Clash或SSH。 }
begin
  DownloadPage := CreateDownloadPage('下载所选组件', '下载并校验 SHA-256 后才开始安装。', nil);
end;
function NextButtonClick(CurPageID: Integer): Boolean; { 空选择和升级时移除已装组件都需明确处理。 }
var Previous: String;
begin
  Result := True;
  if CurPageID = wpSelectComponents then begin
    if Chosen = '' then begin MsgBox('请至少选择一项功能。', mbError, MB_OK); Result := False; Exit; end;
    Previous := GetPreviousData('InstalledComponents', '');
    if ((Pos('keepalive', Previous) > 0) and not WizardIsComponentSelected('keepalive')) or ((Pos('routing', Previous) > 0) and not WizardIsComponentSelected('routing')) or ((Pos('sftp', Previous) > 0) and not WizardIsComponentSelected('sftp')) then begin
      MsgBox('本版升级支持添加组件。若要移除已有组件，请先卸载后重新选择；个人日志和备份会保留。', mbInformation, MB_OK);
      Result := False;
    end;
  end;
end;
procedure RegisterPreviousData(PreviousDataKey: Integer); { 只保存功能编号，不保存账号或密码。 }
begin
  SetPreviousData(PreviousDataKey, 'InstalledComponents', Chosen);
end;
procedure CurStepChanged(CurStep: TSetupStep); { 所有载荷就绪后才提交安装清单与连接迁移。 }
var Code: Integer;
begin
  if CurStep = ssPostInstall then begin
    if not Exec(ExpandConstant('{app}\zzu-nscc-maintenance.exe'), 'configure --components "' + Chosen + '"', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then RaiseException('安装组件或连接迁移未完成，请查看本机保留的备份并修复安装。');
  end;
end;
function InitializeUninstall: Boolean; { 不终止浏览器或任何正在进行的传输。 }
var Code: Integer;
begin
  Result := IdleAt(ExpandConstant('{app}'));
  if Result then Result := Exec(ExpandConstant('{app}\zzu-nscc-maintenance.exe'), 'unregister', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  if not Result then MsgBox('请退出助手；若连接注册已被其他安装修改，请先处理迁移冲突。当前未强制退出程序。', mbError, MB_OK);
end;
[UninstallDelete]
; 仅删除安装器自己生成的组件清单，保留AppData中的日志、回执和规则备份。
Type: files; Name: "{app}\components.json"
