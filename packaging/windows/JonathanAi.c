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

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmd, int show) {
    wchar_t exe_path[MAX_PATH], root[MAX_PATH], probe[MAX_PATH], cmdbuf[2048];
    (void)inst; (void)prev; (void)cmd; (void)show;
    GetModuleFileNameW(NULL, exe_path, MAX_PATH);
    lstrcpynW(root, exe_path, MAX_PATH);
    PathRemoveFileSpecW(root);

    SetEnvironmentVariableW(L"CLAWD_SOURCE_DIR", root);

    join(probe, MAX_PATH, root, L"desktop\\node_modules\\electron\\dist\\electron.exe");
    if (exists(probe)) {
        wchar_t desktop[MAX_PATH];
        join(desktop, MAX_PATH, root, L"desktop");
        wsprintfW(cmdbuf, L"\"%s\" \"%s\"", probe, desktop);
        if (start_process(probe, cmdbuf, desktop)) {
            return 0;
        }
    }

    join(probe, MAX_PATH, root, L".venv\\Scripts\\pythonw.exe");
    if (!exists(probe)) {
        join(probe, MAX_PATH, root, L".venv\\Scripts\\python.exe");
    }
    if (exists(probe)) {
        wsprintfW(cmdbuf, L"\"%s\" -m src.cli desktop --no-browser", probe);
        if (start_process(probe, cmdbuf, root)) {
            /* Electron may still be installing; open the local UI as a windowed fallback. */
            Sleep(1200);
            ShellExecuteW(NULL, L"open", L"http://127.0.0.1:8765/", NULL, NULL, SW_SHOWNORMAL);
            return 0;
        }
    }

    MessageBoxW(
        NULL,
        L"Jonathan Ai could not find Electron or the local Python venv.\n"
        L"Re-run JonathanAi-Setup.exe.",
        L"Jonathan Ai",
        MB_OK | MB_ICONERROR
    );
    return 1;
}
