#pragma once
#include "common/common_types.h"

namespace Core::HID {

enum class NpadIdType : u32 {
    Player1=0, Player2=1, Player3=2, Player4=3,
    Player5=4, Player6=5, Player7=6, Player8=7,
    Other=0x10, Handheld=0x20
};

// BitField with external backing store
template <u64 Offset, u64 Bits, typename T>
struct BitField {
    static constexpr u64 Mask = ((1ULL << Bits) - 1) << Offset;
    u64& storage;
    BitField(u64& s) : storage(s) {}
    void Assign(int v) { storage = (storage & ~Mask) | ((static_cast<u64>(v) << Offset) & Mask); }
    u64 Value() const { return (storage & Mask) >> Offset; }
    operator u64() const { return Value(); }
};

enum class NpadButton : u64 {
    None=0, A=1ULL<<0, B=1ULL<<1, X=1ULL<<2, Y=1ULL<<3,
    All=~0ULL
};
inline NpadButton operator|(NpadButton a, NpadButton b) {
    return static_cast<NpadButton>(static_cast<u64>(a) | static_cast<u64>(b));
}

struct AnalogStickState { s32 x{0}; s32 y{0}; };

} // namespace Core::HID
