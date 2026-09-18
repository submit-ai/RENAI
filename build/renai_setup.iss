; RENAI Setup Script
; Requires: Miniconda3-latest-Windows-x86_64.exe placed in build\
; (download from https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe)
; Python env created via venv (no conda channels required)

[Setup]
AppName=RENAI
AppVersion=1.3.0
AppPublisher=Anonymous
DefaultDirName={localappdata}\RENAI
DefaultGroupName=RENAI
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=..\installer
OutputBaseFilename=RENAI_Setup_v1.3.0
SetupIconFile=..\assets\icon_renai.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Code]
procedure InitializeWizard;
begin
  WizardForm.ProgressGauge.Style := npbstMarquee;
end;

// Runs one setup step (Miniconda install / venv creation / pip install) and checks
// its exit code, instead of blindly continuing to the next step on failure (which
// used to produce a confusing "file not found" error several steps downstream
// instead of pointing at the step that actually failed).
function RunStepChecked(const Filename, Params, StatusMsg, StepName: String): Boolean;
var
  ResultCode: Integer;
  ExecOk: Boolean;
begin
  WizardForm.StatusLabel.Caption := StatusMsg;
  WizardForm.StatusLabel.Update;
  ExecOk := Exec(Filename, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if (not ExecOk) or (ResultCode <> 0) then
  begin
    MsgBox(
      StepName + ' failed (exit code ' + IntToStr(ResultCode) + ').' + #13#10 +
      'Setup cannot continue further.' + #13#10#13#10 +
      'Common causes: no internet connection during setup, antivirus blocking the ' +
      'installer, insufficient disk space, or an install path with unusual characters.' + #13#10#13#10 +
      'Command: "' + Filename + '" ' + Params,
      mbCriticalError, MB_OK
    );
    Result := False;
  end
  else
    Result := True;
end;

// Miniconda's silent installer (NSIS-based) can fail with exit code 2 if the
// destination path contains certain characters — confirmed empirically on
// 13/07/2026 for '(' / ')' (e.g. "C:\my (old) tools\RENAI"): file extraction
// and everything else succeeds, only the Python installation step breaks.
// Reject those characters here, on the wizard's directory page, instead of
// letting the user wait through a full install before hitting a cryptic
// failure at Step 1/4.
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir, BadChars: String;
  I: Integer;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    Dir := WizardDirValue;
    BadChars := '()&%!^';
    for I := 1 to Length(BadChars) do
    begin
      if Pos(BadChars[I], Dir) > 0 then
      begin
        MsgBox(
          'The chosen folder contains the character ''' + BadChars[I] + ''', which can make ' +
          'the Python installer used by RENAI fail partway through setup.' + #13#10#13#10 +
          'Please choose a folder path using only letters, numbers, spaces, and basic ' +
          'punctuation (for example C:\RENAI or C:\Users\YourName\RENAI).',
          mbError, MB_OK
        );
        Result := False;
        Exit;
      end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir, MinicondaExe, VenvPython: String;
begin
  if CurStep = ssPostInstall then
  begin
    AppDir       := ExpandConstant('{app}');
    MinicondaExe := ExpandConstant('{tmp}\Miniconda3-latest-Windows-x86_64.exe');
    VenvPython   := AppDir + '\venv\Scripts\python.exe';

    // Miniconda's silent installer fails (exit code 2) if run again against a
    // directory that already has a Miniconda install in it — which happens on
    // any retry/reinstall at the same location (confirmed 12/07/2026). Skip it
    // entirely if python.exe is already there, instead of failing every retry.
    if not FileExists(AppDir + '\miniconda\python.exe') then
    begin
      if not RunStepChecked(MinicondaExe,
          '/S /InstallationType=JustMe /AddToPath=0 /RegisterPython=0 /D=' + AppDir + '\miniconda',
          'Step 1/4 — Installing Python...  (total setup: 15–30 min)',
          'Python installation') then
        Exit;

      if not FileExists(AppDir + '\miniconda\python.exe') then
      begin
        MsgBox(
          'Python installation reported success, but ' + AppDir + '\miniconda\python.exe ' +
          'was not found.' + #13#10 + 'Setup cannot continue.',
          mbCriticalError, MB_OK
        );
        Exit;
      end;
    end;

    if not RunStepChecked(AppDir + '\miniconda\python.exe',
        '-m venv "' + AppDir + '\venv"',
        'Step 2/4 — Creating Python environment...',
        'Python environment creation') then
      Exit;

    if not RunStepChecked(VenvPython,
        '-m pip install torch==2.6.0+cu118 torchvision==0.21.0+cu118 torchaudio==2.6.0+cu118 --index-url https://download.pytorch.org/whl/cu118',
        'Step 3/4 — Downloading PyTorch (~2 GB)  Please wait, this is the longest step...',
        'PyTorch installation') then
      Exit;

    if not RunStepChecked(VenvPython,
        '-m pip install opencv-python pandas openpyxl Pillow pyyaml scikit-learn joblib "transformers==4.51.1" safetensors tqdm numpy "rfdetr==1.1.0" huggingface_hub timm "einops==0.8.1"',
        'Step 4/4 — Installing scientific packages (rfdetr, transformers, sklearn...)...',
        'Scientific packages installation') then
      Exit;
  end;
end;

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Miniconda installer (place Miniconda3-latest-Windows-x86_64.exe in build\ before compiling)
Source: "Miniconda3-latest-Windows-x86_64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

; Main entry point and config
Source: "..\main.py";     DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\config.yaml"; DestDir: "{app}\app"; Flags: ignoreversion

; Pipeline scripts
Source: "..\core\pipeline_runner.py"; DestDir: "{app}\app\core"; Flags: ignoreversion
Source: "..\core\version.py";         DestDir: "{app}\app\core"; Flags: ignoreversion
Source: "..\core\run\*";    DestDir: "{app}\app\core\run"; Excludes: "*.pyc,__pycache__";    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\core\output\*"; DestDir: "{app}\app\core\output"; Excludes: "*.pyc,__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\core\export\*"; DestDir: "{app}\app\core\export"; Excludes: "*.pyc,__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs

; Custom trained models (rfdetr detector + classifier)
Source: "..\core\models\detecteur\rfdetr_model.pth";             DestDir: "{app}\app\core\models\detecteur";    Flags: ignoreversion
; Bundled HuggingFace cache for facebook/dinov2-base (RF-DETR backbone) — avoids any
; network dependency on huggingface.co at runtime (machines behind a restricted network)
Source: "..\core\models\detecteur\hf_cache\*";                   DestDir: "{app}\app\core\models\detecteur\hf_cache"; Excludes: "*.pyc,__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\core\models\classifieur\classifieur.joblib";         DestDir: "{app}\app\core\models\classifieur";  Flags: ignoreversion
Source: "..\core\models\classifieur\label_encoder.npy";          DestDir: "{app}\app\core\models\classifieur";  Flags: ignoreversion
Source: "..\core\models\classifieur\scaler.joblib";              DestDir: "{app}\app\core\models\classifieur";  Flags: ignoreversion
Source: "..\core\models\classifieur\pca.joblib";               DestDir: "{app}\app\core\models\classifieur";  Flags: ignoreversion
; Bundled HuggingFace cache for nvidia/C-RADIOv3-H (weights + trust_remote_code files)
; — same reason as dinov2-base above, avoids any network dependency at runtime
Source: "..\core\models\classifieur\hf_cache\*";                 DestDir: "{app}\app\core\models\classifieur\hf_cache"; Excludes: "*.pyc,__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs

; UI modules (correction + habitat tabs)
Source: "..\ui\correction_tab.py"; DestDir: "{app}\app\ui"; Flags: ignoreversion
Source: "..\ui\habitat_tab.py";    DestDir: "{app}\app\ui"; Flags: ignoreversion
Source: "..\ui\__init__.py";       DestDir: "{app}\app\ui"; Flags: ignoreversion

; Config (species list)
Source: "..\config\species_config.json"; DestDir: "{app}\app\config"; Flags: ignoreversion

; Assets
Source: "..\assets\icon_renai.ico"; DestDir: "{app}\app\assets"; Flags: ignoreversion

[Dirs]
Name: "{app}\app\drops"
Name: "{app}\app\results"

[Icons]
Name: "{group}\RENAI"; \
    Filename: "{app}\venv\Scripts\pythonw.exe"; \
    Parameters: """{app}\app\main.py"""; \
    WorkingDir: "{app}\app"; \
    IconFilename: "{app}\app\assets\icon_renai.ico"
Name: "{group}\Uninstall RENAI"; Filename: "{uninstallexe}"
Name: "{autodesktop}\RENAI"; \
    Filename: "{app}\venv\Scripts\pythonw.exe"; \
    Parameters: """{app}\app\main.py"""; \
    WorkingDir: "{app}\app"; \
    IconFilename: "{app}\app\assets\icon_renai.ico"; \
    Tasks: desktopicon

[Run]
; Steps 1-4 (Miniconda install, venv creation, PyTorch, scientific packages) are now
; run from [Code]'s CurStepChanged(ssPostInstall) with explicit exit-code checking —
; see RunStepChecked. This used to be 4 plain [Run] entries with no error checking,
; so a failure in an early step (e.g. Miniconda) would silently cascade into a
; confusing "file not found" error several steps downstream instead of a clear
; message pointing at what actually failed.

; 5 — Launch after install (optional)
Filename: "{app}\venv\Scripts\pythonw.exe"; \
    Parameters: """{app}\app\main.py"""; \
    WorkingDir: "{app}\app"; \
    Description: "Launch RENAI"; \
    Flags: nowait postinstall skipifsilent
