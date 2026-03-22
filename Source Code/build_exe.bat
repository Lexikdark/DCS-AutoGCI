@echo off
echo ============================================
echo   DCS Auto-GCI - Build EXE + Installer
echo ============================================
echo.

:: Source Code lives in this folder; output goes to parent (project root)
set "SRC=%~dp0"
set "ROOT=%~dp0..\\"

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    pause
    exit /b 1
)

:: Install build dependencies
echo Installing build dependencies...
pip install pyinstaller comtypes

echo.
echo [1/3] Building DCS Auto-GCI.exe ...
echo.

pyinstaller --noconfirm --onefile --windowed ^
    --name "DCS Auto-GCI" ^
    --icon "%SRC%app_icon.ico" ^
    --hidden-import comtypes ^
    --hidden-import comtypes.client ^
    --hidden-import comtypes.gen ^
    "%SRC%auto_gci.py"

if errorlevel 1 (
    echo.
    echo BUILD FAILED. See errors above.
    pause
    exit /b 1
)

:: Prepare clean release folder (in project root)
if exist "%ROOT%release" rmdir /S /Q "%ROOT%release"
mkdir "%ROOT%release"
mkdir "%ROOT%release\dcs_lua"

:: Move EXE to release folder
move /Y "%SRC%dist\DCS Auto-GCI.exe" "%ROOT%release\" >nul
rmdir /S /Q "%SRC%dist" 2>nul

echo.
echo EXE built: %ROOT%release\DCS Auto-GCI.exe
echo.

:: Build the MSI installer with WiX
echo [2/3] Building MSI installer...
where wix >nul 2>&1
if errorlevel 1 (
    echo.
    echo WiX toolset not found. Skipping installer build.
    echo To install: dotnet tool install --global wix
    echo Then run:   wix extension add WixToolset.UI.wixext
    echo             wix extension add WixToolset.Bal.wixext
    echo.
    echo The standalone EXE is still available in release\
    goto :package
)

set "UI_EXT=%ROOT%.wix\extensions\WixToolset.UI.wixext\6.0.2\wixext6\WixToolset.UI.wixext.dll"
wix build -o "%ROOT%release\DCS_AutoGCI_Setup.msi" "%SRC%Package.wxs" -ext "%UI_EXT%"
if errorlevel 1 (
    echo WARNING: MSI installer build failed.
    goto :package
)
echo.
echo MSI built (intermediate)

:: Build the setup.exe bootstrapper (wraps MSI with Install/Uninstall UI)
echo.
echo [3/3] Building Setup.exe bootstrapper...
set "BAL_EXT=%ROOT%.wix\extensions\WixToolset.Bal.wixext\6.0.2\wixext6\WixToolset.BootstrapperApplications.wixext.dll"
if exist "%BAL_EXT%" (
    wix build -o "%ROOT%release\DCS_AutoGCI_Setup.exe" "%SRC%Bundle.wxs" -ext "%BAL_EXT%"
    if errorlevel 1 (
        echo WARNING: Setup.exe bootstrapper build failed.
    ) else (
        echo.
        echo Setup.exe built: %ROOT%release\DCS_AutoGCI_Setup.exe
    )
) else (
    echo WARNING: WixToolset.Bal.wixext not found. Run: wix extension add WixToolset.Bal.wixext
)

:: ── Package release folder ──────────────────────────────────────
:package
echo.
echo [*] Packaging release folder...

:: Copy documentation and Lua scripts
copy /Y "%ROOT%README.txt" "%ROOT%release\" >nul
copy /Y "%ROOT%DCS_AutoGCI_README.html" "%ROOT%release\" >nul
copy /Y "%SRC%dcs_lua\ThreatWarnerExport.lua" "%ROOT%release\dcs_lua\" >nul
copy /Y "%SRC%dcs_lua\ThreatWarnerHook.lua" "%ROOT%release\dcs_lua\" >nul

:: Remove intermediate build artifacts from release
del /Q "%ROOT%release\DCS_AutoGCI_Setup.msi" 2>nul
del /Q "%ROOT%release\DCS_AutoGCI_Setup.wixpdb" 2>nul
del /Q "%ROOT%release\*.wixpdb" 2>nul

:: Clean up build temp folders
rmdir /S /Q "%SRC%build" 2>nul
del /Q "%SRC%DCS Auto-GCI.spec" 2>nul

echo.
echo ============================================
echo   Build complete!  release\ contents:
echo ============================================
echo.
dir /B "%ROOT%release"
echo.
