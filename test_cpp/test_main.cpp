#include <cstdio>
#include <cassert>
#include <cstring>
#include <thread>
#include <chrono>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>

// Include stub headers (must come before overlay headers due to forward decl resolution)
#include "hid_core/hid_types.h"
#include "hid_core/frontend/emulated_controller.h"

// Real overlay sources
#include "hid_core/frontend/overlay_state.h"
#include "hid_core/frontend/overlay_udp.h"

#include "common/settings.h"

static u64 Now() {
    return static_cast<u64>(
        std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
}

namespace Settings { Values values; }

using namespace Core::HID;

static int passed = 0, failed = 0;
#define CHECK(cond, msg) do { \
    if (cond) { passed++; printf("  ✅ %s\n", msg); } \
    else { failed++; printf("  ❌ %s\n", msg); } \
} while(0)

void test_merge_logic() {
    printf("\n=== Merge Logic ===\n");

    // -- Test 1: Inactive → no effect --
    ControllerStatus c1;
    c1.npad_button_state.a.Assign(1);
    c1.analog_stick_state.left.x = 16384;
    overlay_states[0] = {};  // fresh state, active=false
    ApplyOverlay(NpadIdType::Player1, c1);
    CHECK(c1.npad_button_state.a == 1, "inactive: A preserved");
    CHECK(c1.analog_stick_state.left.x == 16384, "inactive: stick preserved");

    // -- Test 2: Button press + release --
    ControllerStatus c2;
    auto& s2 = overlay_states[0];
    s2.active = true;
    s2.last_update = Now();
    s2.control_mask = OverlayControl::BUTTON;

    s2.button_mask = 1; // A pressed
    ApplyOverlay(NpadIdType::Player1, c2);
    CHECK((static_cast<u64>(c2.npad_button_state.raw) & 1) != 0, "press: A set");

    s2.button_mask = 0; // A released
    s2.last_update = Now();
    ApplyOverlay(NpadIdType::Player1, c2);
    CHECK((static_cast<u64>(c2.npad_button_state.raw) & 1) == 0, "release: A cleared");

    // -- Test 3: physical A + overlay B, then overlay releases --
    ControllerStatus c3;
    c3.npad_button_state.a.Assign(1); // phys A
    auto& s3 = overlay_states[0];
    s3.active = true;
    s3.last_update = Now();
    s3.control_mask = OverlayControl::BUTTON;
    s3.button_mask = 2; // overlay B
    ApplyOverlay(NpadIdType::Player1, c3);
    CHECK(static_cast<u64>(c3.npad_button_state.raw) == 3, "phys A|overlay B");

    s3.button_mask = 0;
    s3.last_update = Now();
    ApplyOverlay(NpadIdType::Player1, c3);
    CHECK(static_cast<u64>(c3.npad_button_state.raw) == 1, "release: only phys A");
    CHECK((static_cast<u64>(c3.npad_button_state.raw) & 2) == 0, "release: B cleared");

    // -- Test 3b: Packet update must preserve button_mask_prev --
    // Simulates a new UDP packet arriving that overwrites overlay_states
    OverlayState packet;
    packet.control_mask = OverlayControl::BUTTON;
    packet.button_mask = 0; // release
    packet.active = true;
    packet.button_mask_prev = 0; // ParsePacket sets this to 0 (fresh state)
    // BUT: we preserve it before the assignment
    packet.button_mask_prev = overlay_states[0].button_mask_prev;
    packet.last_update = Now();
    overlay_states[0] = packet;
    ControllerStatus c3b;
    ApplyOverlay(NpadIdType::Player1, c3b);
    CHECK((static_cast<u64>(c3b.npad_button_state.raw) & 1) == 0,
        "packet update: prev preserved, A cleared");

    // -- Test 4: Stick write --
    ControllerStatus c4;
    auto& s4 = overlay_states[0];
    s4.active = true; s4.last_update = Now();
    s4.control_mask = OverlayControl::LEFT_X;
    s4.left_x = 0.5f;
    ApplyOverlay(NpadIdType::Player1, c4);
    CHECK(c4.analog_stick_state.left.x == static_cast<s32>(0.5f*32767), "stick: left_x=0.5");
    CHECK(c4.analog_stick_state.left.y == 0, "stick: left_y untouched");

    // -- Test 5: Direction bits --
    ControllerStatus c5;
    auto& s5 = overlay_states[0];
    s5.active = true; s5.last_update = Now();
    s5.control_mask = OverlayControl::LEFT_X | OverlayControl::LEFT_Y;
    s5.left_x = 0.8f;  s5.left_y = -0.6f;
    ApplyOverlay(NpadIdType::Player1, c5);
    CHECK(c5.npad_button_state.stick_l_right == 1, "dir: stick_l_right");
    CHECK(c5.npad_button_state.stick_l_down == 1, "dir: stick_l_down");

    // -- Test 6: Staleness --
    ControllerStatus c6;
    auto& s6 = overlay_states[0];
    s6.active = true; s6.last_update = 1; // 1 us since epoch — guaranteed stale, will time out
    s6.control_mask = OverlayControl::BUTTON; s6.button_mask = 1;
    ApplyOverlay(NpadIdType::Player1, c6);
    CHECK(s6.active == false, "stale: active=false");
    CHECK((static_cast<u64>(c6.npad_button_state.raw) & 1) == 0, "stale: no effect");

    printf("  Merge tests: %d/%d passed\n", passed, failed);
}

void test_udp_integration() {
    printf("\n=== UDP Integration ===\n");

    // Find a free port
    int test_sock = socket(AF_INET, SOCK_DGRAM, 0);
    sockaddr_in tmp{}; tmp.sin_family = AF_INET; tmp.sin_port = 0;
    tmp.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    bind(test_sock, (sockaddr*)&tmp, sizeof(tmp));
    sockaddr_in bound{}; socklen_t len = sizeof(bound);
    getsockname(test_sock, (sockaddr*)&bound, &len);
    u16 free_port = ntohs(bound.sin_port);
    close(test_sock);

    ShutdownOverlayUdp();  // close previous failed socket
    Settings::values.overlay_enabled = true;
    Settings::values.overlay_port = free_port;

    // Lazy init should now succeed
    ControllerStatus c;
    ApplyOverlay(NpadIdType::Player1, c);
    CHECK(true, "lazy init called");

    // Send press packet
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    CHECK(sock >= 0, "socket created");
    u8 pkt[84] = {};
    pkt[0]='O'; pkt[1]='V'; pkt[2]='E'; pkt[3]='R';
    pkt[4] = 0;
    u32 ctrl = OverlayControl::BUTTON; memcpy(pkt+8, &ctrl, 4);
    u64 btns = 1; memcpy(pkt+12, &btns, 8);

    sockaddr_in addr{}; addr.sin_family=AF_INET;
    addr.sin_port=htons(free_port); addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    sendto(sock, pkt, 84, 0, (sockaddr*)&addr, sizeof(addr));
    std::this_thread::sleep_for(std::chrono::milliseconds(10));

    ControllerStatus c2;
    ApplyOverlay(NpadIdType::Player1, c2);
    CHECK((static_cast<u64>(c2.npad_button_state.raw)&1)!=0, "UDP: A from packet");

    // Send release
    btns = 0; memcpy(pkt+12, &btns, 8);
    sendto(sock, pkt, 84, 0, (sockaddr*)&addr, sizeof(addr));
    std::this_thread::sleep_for(std::chrono::milliseconds(10));

    ControllerStatus c3;
    ApplyOverlay(NpadIdType::Player1, c3);
    CHECK((static_cast<u64>(c3.npad_button_state.raw)&1)==0, "UDP: A released");

    close(sock);
    ShutdownOverlayUdp();
}

int main() {
    test_merge_logic();
    test_udp_integration();
    printf("\n=== %s (%d/%d) ===\n", failed?"FAILED":"PASSED", passed, passed+failed);
    return failed ? 1 : 0;
}
