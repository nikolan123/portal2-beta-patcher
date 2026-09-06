#include <windows.h>

#include <cstdint>
#include <cstring>

namespace {

constexpr DWORD kEngineTimestamp = 0x4A6F766D;
constexpr DWORD kEngineImageSize = 0x006A3000;
constexpr DWORD kServerTimestamp = 0x4A6F96C4;
constexpr DWORD kServerImageSize = 0x0072C000;

constexpr std::uintptr_t kCreateConnectionRva = 0x000823E6;
constexpr std::uintptr_t kCreateConnectionContinueRva = 0x000823EC;
constexpr std::uintptr_t kCreateConnectionMissingRva = 0x00082430;
constexpr std::uintptr_t kInitRva = 0x000788F0;
constexpr std::uintptr_t kNetOpenSocketsRva = 0x00087DA0;
constexpr std::uintptr_t kGetPlayerNameRva = 0x000DB310;
constexpr std::uintptr_t kEntIndexRva = 0x001A150;
constexpr std::uintptr_t kEngineServerPointerRva = 0x005FCDA8;

constexpr unsigned char kCreateConnectionBytes[] = {
    0x8B, 0x8E, 0x84, 0x00, 0x00, 0x00,
};
constexpr unsigned char kInitBytes[] = {
    0xC6, 0x81, 0xBC, 0x00, 0x00, 0x00, 0x01,
};
constexpr unsigned char kGetPlayerNameBytes[] = {
    0x8D, 0x81, 0x25, 0x0F, 0x00, 0x00, 0xC3,
};
constexpr unsigned char kEntIndexBytes[] = {
    0x8B, 0x41, 0x1C, 0x85, 0xC0, 0x75, 0x01, 0xC3,
};

std::uintptr_t g_create_connection_continue = 0;
std::uintptr_t g_create_connection_missing = 0;
std::uintptr_t g_init_trampoline = 0;
std::uintptr_t g_net_open_sockets = 0;
std::uintptr_t g_server_base = 0;

bool MatchesModule(HMODULE module, DWORD timestamp, DWORD image_size) {
    if (module == nullptr) {
        return false;
    }
    const auto base = reinterpret_cast<const unsigned char*>(module);
    const auto dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
        return false;
    }
    const auto nt = reinterpret_cast<const IMAGE_NT_HEADERS32*>(base + dos->e_lfanew);
    return nt->Signature == IMAGE_NT_SIGNATURE &&
           nt->FileHeader.Machine == IMAGE_FILE_MACHINE_I386 &&
           nt->FileHeader.TimeDateStamp == timestamp &&
           nt->OptionalHeader.SizeOfImage == image_size;
}

bool MatchesBytes(std::uintptr_t address, const unsigned char* expected, SIZE_T length) {
    return std::memcmp(reinterpret_cast<const void*>(address), expected, length) == 0;
}

bool WriteJump(std::uintptr_t source, const void* destination, SIZE_T length) {
    if (length < 5) {
        return false;
    }
    DWORD old_protection = 0;
    auto bytes = reinterpret_cast<unsigned char*>(source);
    if (!VirtualProtect(bytes, length, PAGE_EXECUTE_READWRITE, &old_protection)) {
        return false;
    }
    bytes[0] = 0xE9;
    *reinterpret_cast<std::int32_t*>(bytes + 1) =
        static_cast<std::int32_t>(reinterpret_cast<std::uintptr_t>(destination) - source - 5);
    for (SIZE_T index = 5; index < length; ++index) {
        bytes[index] = 0x90;
    }
    FlushInstructionCache(GetCurrentProcess(), bytes, length);
    DWORD ignored = 0;
    VirtualProtect(bytes, length, old_protection, &ignored);
    return true;
}

std::uintptr_t MakeTrampoline(std::uintptr_t source, SIZE_T length) {
    auto memory = static_cast<unsigned char*>(VirtualAlloc(
        nullptr, length + 5, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (memory == nullptr) {
        return 0;
    }
    std::memcpy(memory, reinterpret_cast<const void*>(source), length);
    memory[length] = 0xE9;
    *reinterpret_cast<std::int32_t*>(memory + length + 1) = static_cast<std::int32_t>(
        source + length - reinterpret_cast<std::uintptr_t>(memory + length) - 5);
    FlushInstructionCache(GetCurrentProcess(), memory, length + 5);
    return reinterpret_cast<std::uintptr_t>(memory);
}

__declspec(naked) void CreateConnectionGuard() {
    __asm {
        mov ecx, dword ptr [esi + 084h]
        test ecx, ecx
        jz missing_connection
        jmp dword ptr [g_create_connection_continue]
    missing_connection:
        mov dword ptr [esp + 02Ch], 0
        jmp dword ptr [g_create_connection_missing]
    }
}

__declspec(naked) void InitWithNetworkSockets() {
    __asm {
        call dword ptr [g_init_trampoline]
        call dword ptr [g_net_open_sockets]
        ret
    }
}

using EntIndexFunction = int(__thiscall*)(void* player);
using GetClientConVarValueFunction = const char*(__thiscall*)(
    void* engine_server, int player_index, const char* variable);

const char* __fastcall GetPlayerNameFromEngine(void* player, void*) {
    auto fallback = static_cast<char*>(player) + 0x0F25;
    auto engine_server = *reinterpret_cast<void**>(g_server_base + kEngineServerPointerRva);
    if (engine_server == nullptr) {
        return fallback;
    }

    const int player_index = reinterpret_cast<EntIndexFunction>(
        g_server_base + kEntIndexRva)(player);
    if (player_index < 1) {
        return fallback;
    }

    auto vtable = *reinterpret_cast<std::uintptr_t**>(engine_server);
    const char* name = reinterpret_cast<GetClientConVarValueFunction>(vtable[0xE0 / 4])(
        engine_server, player_index, "name");
    if (name == nullptr || name[0] == '\0') {
        return fallback;
    }

    unsigned index = 0;
    while (index < 31 && name[index] != '\0') {
        fallback[index] = name[index];
        ++index;
    }
    fallback[index] = '\0';
    return fallback;
}

bool InstallEngineFixes(HMODULE module) {
    if (!MatchesModule(module, kEngineTimestamp, kEngineImageSize)) {
        return false;
    }
    const auto base = reinterpret_cast<std::uintptr_t>(module);
    const auto create_connection = base + kCreateConnectionRva;
    const auto init = base + kInitRva;
    if (!MatchesBytes(create_connection, kCreateConnectionBytes, sizeof(kCreateConnectionBytes)) ||
        !MatchesBytes(init, kInitBytes, sizeof(kInitBytes))) {
        return false;
    }

    g_create_connection_continue = base + kCreateConnectionContinueRva;
    g_create_connection_missing = base + kCreateConnectionMissingRva;
    g_net_open_sockets = base + kNetOpenSocketsRva;
    g_init_trampoline = MakeTrampoline(init, sizeof(kInitBytes));
    if (g_init_trampoline == 0) {
        return false;
    }
    return WriteJump(create_connection, CreateConnectionGuard, sizeof(kCreateConnectionBytes)) &&
           WriteJump(init, InitWithNetworkSockets, sizeof(kInitBytes));
}

bool InstallServerFix(HMODULE module) {
    if (!MatchesModule(module, kServerTimestamp, kServerImageSize)) {
        return false;
    }
    const auto base = reinterpret_cast<std::uintptr_t>(module);
    if (!MatchesBytes(base + kGetPlayerNameRva, kGetPlayerNameBytes, sizeof(kGetPlayerNameBytes)) ||
        !MatchesBytes(base + kEntIndexRva, kEntIndexBytes, sizeof(kEntIndexBytes))) {
        return false;
    }
    g_server_base = base;
    return WriteJump(
        base + kGetPlayerNameRva,
        reinterpret_cast<const void*>(GetPlayerNameFromEngine),
        sizeof(kGetPlayerNameBytes));
}

DWORD WINAPI InstallFixes(void*) {
    bool engine_installed = false;
    bool server_installed = false;
    for (unsigned attempt = 0; attempt < 2400 && (!engine_installed || !server_installed); ++attempt) {
        if (!engine_installed) {
            HMODULE engine = GetModuleHandleW(L"engine.dll");
            if (engine != nullptr) {
                engine_installed = InstallEngineFixes(engine);
            }
        }
        if (!server_installed) {
            HMODULE server = GetModuleHandleW(L"server.dll");
            if (server != nullptr) {
                server_installed = InstallServerFix(server);
            }
        }
        Sleep(50);
    }
    return 0;
}

}  // namespace

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(instance);
        HANDLE thread = CreateThread(nullptr, 0, InstallFixes, nullptr, 0, nullptr);
        if (thread != nullptr) {
            CloseHandle(thread);
        }
    }
    return TRUE;
}
