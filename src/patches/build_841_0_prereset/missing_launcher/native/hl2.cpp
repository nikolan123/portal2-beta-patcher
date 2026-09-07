// Minimal Portal 2 executable used by the missing hl2.exe fix for 841_0

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

using LauncherMain = int (*)(HINSTANCE, HINSTANCE, LPSTR, int);

static void show_last_error(const char* prefix) {
    char* system_message = nullptr;
    FormatMessageA(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
            FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr,
        GetLastError(),
        MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
        reinterpret_cast<char*>(&system_message),
        0,
        nullptr
    );

    char message[2048];
    wsprintfA(message, "%s\n\n%s", prefix, system_message ? system_message : "Unknown error");
    MessageBoxA(nullptr, message, "Portal 2 Launcher Test", MB_OK | MB_ICONERROR);
    if (system_message) {
        LocalFree(system_message);
    }
}

int APIENTRY WinMain(HINSTANCE instance, HINSTANCE previous, LPSTR command_line, int show) {
    char module_path[MAX_PATH];
    const DWORD module_length = GetModuleFileNameA(nullptr, module_path, MAX_PATH);
    if (module_length == 0 || module_length == MAX_PATH) {
        show_last_error("Could not determine the launcher path.");
        return 1;
    }

    char* separator = module_path + module_length;
    while (separator > module_path && separator[-1] != '\\' && separator[-1] != '/') {
        --separator;
    }
    if (separator == module_path) {
        MessageBoxA(nullptr, "Could not determine the game directory.", "Portal 2 Launcher Test", MB_OK | MB_ICONERROR);
        return 1;
    }
    separator[-1] = '\0';
    const char* root = module_path;

    if (!SetCurrentDirectoryA(root)) {
        show_last_error("Could not set the game working directory.");
        return 1;
    }
    SetEnvironmentVariableA("SDK_EXEC_DIR", root);

    const DWORD old_path_length = GetEnvironmentVariableA("PATH", nullptr, 0);
    const SIZE_T path_capacity = lstrlenA(root) + 6 + old_path_length + 1;
    char* updated_path = static_cast<char*>(HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, path_capacity));
    if (!updated_path) {
        MessageBoxA(nullptr, "Could not allocate the DLL search path.", "Portal 2 Launcher Test", MB_OK | MB_ICONERROR);
        return 1;
    }
    lstrcpyA(updated_path, root);
    lstrcatA(updated_path, "\\bin;");
    if (old_path_length > 1) {
        GetEnvironmentVariableA("PATH", updated_path + lstrlenA(updated_path), old_path_length);
    }
    SetEnvironmentVariableA("PATH", updated_path);
    HeapFree(GetProcessHeap(), 0, updated_path);

    char launcher_path[MAX_PATH];
    lstrcpyA(launcher_path, root);
    lstrcatA(launcher_path, "\\bin\\launcher.dll");
    HMODULE launcher = LoadLibraryExA(launcher_path, nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!launcher) {
        show_last_error("Failed to load bin\\launcher.dll.");
        return 1;
    }

    auto launcher_main = reinterpret_cast<LauncherMain>(GetProcAddress(launcher, "LauncherMain"));
    if (!launcher_main) {
        show_last_error("bin\\launcher.dll does not export LauncherMain.");
        FreeLibrary(launcher);
        return 1;
    }

    return launcher_main(instance, previous, command_line, show);
}
