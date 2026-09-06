#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <shlwapi.h>

#pragma comment(lib, "shell32")
#pragma comment(lib, "shlwapi")

static void join(wchar_t *out, size_t cap, const wchar_t *a, const wchar_t *b) {
    lstrcpynW(out, a, (int)cap);
    PathAppendW(out, b);
}

static int exists(const wchar_t *path) {
    DWORD attr = GetFileAttributesW(path);
    return attr != INVALID_FILE_ATTRIBUTES;
}

static int is_app_root(const wchar_t *dir) {
    wchar_t probe[MAX_PATH];
    if (!dir || !dir[0]) return 0;
    join(probe, MAX_PATH, dir, L"src\\cli.py");
    if (!exists(probe)) return 0;
    join(probe, MAX_PATH, dir, L".venv\\Scripts\\python.exe");
    if (exists(probe)) return 1;
    join(probe, MAX_PATH, dir, L".venv\\Scripts\\pythonw.exe");
    if (exists(probe)) return 1;
    join(probe, MAX_PATH, dir, L"desktop\\node_modules\\electron\\dist\\electron.exe");
    return exists(probe);
}

static int try_copy_root(wchar_t *out, const wchar_t *cand) {
    if (!is_app_root(cand)) return 0;
    lstrcpynW(out, cand, MAX_PATH);
    return 1;
}

static int pick_root(wchar_t *out) {
    wchar_t cand[MAX_PATH], exe_path[MAX_PATH];

    if (GetEnvironmentVariableW(L"CLAWD_SOURCE_DIR", cand, MAX_PATH) > 0) {
        if (try_copy_root(out, cand)) return 1;
    }

    GetModuleFileNameW(NULL, exe_path, MAX_PATH);
    lstrcpynW(cand, exe_path, MAX_PATH);
    PathRemoveFileSpecW(cand);
    if (try_copy_root(out, cand)) return 1;

    if (GetEnvironmentVariableW(L"USERPROFILE", cand, MAX_PATH) > 0) {
        PathAppendW(cand, L"Jonathan\\Jonathan-Ai");
        if (try_copy_root(out, cand)) return 1;
    }

    if (GetCurrentDirectoryW(MAX_PATH, cand) > 0) {
        if (try_copy_root(out, cand)) return 1;
    }
    return 0;
}

static BOOL run_and_wait(const wchar_t *exe, const wchar_t *args, const wchar_t *cwd) {
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    wchar_t cmdline[2048];
    DWORD code = 1;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    lstrcpynW(cmdline, args, 2048);
    if (!CreateProcessW(exe, cmdline, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, cwd, &si, &pi)) {
        return FALSE;
    }
    /* First-run repair installs Jonathan's native image-engine packages and
       prepares its private model/output directories. */
    WaitForSingleObject(pi.hProcess, 7200000);
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return code == 0;
}

static void run_bootstrap(const wchar_t *root) {
    wchar_t python[MAX_PATH], cmdbuf[2048];
    join(python, MAX_PATH, root, L".venv\\Scripts\\python.exe");
    if (exists(python)) {
        wsprintfW(cmdbuf, L"\"%s\" -m src.install.bootstrap --source-dir \"%s\"", python, root);
        if (run_and_wait(python, cmdbuf, root)) return;
    }
    wsprintfW(cmdbuf, L"python -m src.install.bootstrap --source-dir \"%s\"", root);
    if (run_and_wait(L"python", cmdbuf, root)) return;
    wsprintfW(cmdbuf, L"py -3 -m src.install.bootstrap --source-dir \"%s\"", root);
    run_and_wait(L"py", cmdbuf, root);
}

static int runtime_ready(const wchar_t *root) {
    wchar_t probe[MAX_PATH];
    join(probe, MAX_PATH, root, L".venv\\Scripts\\python.exe");
    if (!exists(probe)) return 0;
    join(probe, MAX_PATH, root, L"desktop\\node_modules\\electron\\dist\\electron.exe");
    if (!exists(probe)) return 0;
    /* Version-specific marker: Setup/bootstrap creates this only after all
       required dependencies are healthy. A future upgrade changes the marker
       name and automatically performs one repair on its first launch. */
    join(probe, MAX_PATH, root, L".jonathan-ai-runtime-0.4.6.ready");
    return exists(probe);
}

static BOOL start_process(const wchar_t *exe, const wchar_t *args, const wchar_t *cwd) {
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    wchar_t cmdline[2048];
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    lstrcpynW(cmdline, args, 2048);
    if (!CreateProcessW(exe, cmdline, NULL, NULL, FALSE, 0, NULL, cwd, &si, &pi)) {
        return FALSE;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return TRUE;
}

static BOOL start_process_checked(const wchar_t *exe, const wchar_t *args, const wchar_t *cwd, DWORD settle_ms) {
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    wchar_t cmdline[2048];
    DWORD code = STILL_ACTIVE;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    lstrcpynW(cmdline, args, 2048);
    if (!CreateProcessW(exe, cmdline, NULL, NULL, FALSE, 0, NULL, cwd, &si, &pi)) {
        return FALSE;
    }
    CloseHandle(pi.hThread);
    if (WaitForSingleObject(pi.hProcess, settle_ms) == WAIT_OBJECT_0) {
        GetExitCodeProcess(pi.hProcess, &code);
    }
    CloseHandle(pi.hProcess);
    /* A second Electron process exits cleanly after handing focus to the
       existing single-instance window. Treat exit code 0 as success so the
       launcher does not also start the browser fallback. */
    return code == STILL_ACTIVE || code == 0;
}

static int start_electron(const wchar_t *root) {
    wchar_t electron[MAX_PATH], desktop[MAX_PATH], cmdbuf[2048];
    join(electron, MAX_PATH, root, L"desktop\\node_modules\\electron\\dist\\electron.exe");
    if (!exists(electron)) return 0;
    join(desktop, MAX_PATH, root, L"desktop");
    wsprintfW(cmdbuf, L"\"%s\" \"%s\"", electron, desktop);
    /* A loader/crashpad failure can exit immediately after CreateProcess.
       Only suppress the Python fallback once Electron remains alive. */
    return start_process_checked(electron, cmdbuf, desktop, 1800) ? 1 : 0;
}

static int start_pythonw(const wchar_t *root) {
    wchar_t python[MAX_PATH], cmdbuf[2048];
    join(python, MAX_PATH, root, L".venv\\Scripts\\pythonw.exe");
    if (!exists(python)) {
        join(python, MAX_PATH, root, L".venv\\Scripts\\python.exe");
    }
    if (!exists(python)) return 0;
    /* Electron is optional. A working venv is enough to open the UI. */
    SetEnvironmentVariableW(L"CLAWD_DESKTOP_MANAGED_BY_LAUNCHER", L"1");
    wsprintfW(cmdbuf, L"\"%s\" -m src.cli desktop --no-browser", python);
    if (!start_process(python, cmdbuf, root)) {
        SetEnvironmentVariableW(L"CLAWD_DESKTOP_MANAGED_BY_LAUNCHER", NULL);
        return 0;
    }
    SetEnvironmentVariableW(L"CLAWD_DESKTOP_MANAGED_BY_LAUNCHER", NULL);
    Sleep(1200);
    ShellExecuteW(NULL, L"open", L"http://127.0.0.1:8765/", NULL, NULL, SW_SHOWNORMAL);
    return 1;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmd, int show) {
    wchar_t root[MAX_PATH];
    (void)inst; (void)prev; (void)cmd; (void)show;

    if (!pick_root(root)) {
        MessageBoxW(
            NULL,
            L"Jonathan Ai could not find the app folder or the local Python venv.\n"
            L"Re-run JonathanAi-Setup.exe. It upgrades the existing install in place\n"
            L"(%USERPROFILE%\\Jonathan\\Jonathan-Ai).",
            L"Jonathan Ai",
            MB_OK | MB_ICONERROR
        );
        return 1;
    }

    SetEnvironmentVariableW(L"CLAWD_SOURCE_DIR", root);
    if (!runtime_ready(root)) {
        run_bootstrap(root);
    }

    if (start_electron(root)) {
        return 0;
    }
    if (start_pythonw(root)) {
        return 0;
    }

    MessageBoxW(
        NULL,
        L"Jonathan Ai found the app folder but could not start Python.\n"
        L"Re-run JonathanAi-Setup.exe to repair the venv.",
        L"Jonathan Ai",
        MB_OK | MB_ICONERROR
    );
    return 1;
}
