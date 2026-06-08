#pragma once
#include <array>
#include "common/common_types.h"
#include "common/vector_math.h"
#include "hid_core/hid_types.h"

namespace Core::HID {

struct NpadButtonState {
    u64 storage{0};
    NpadButton& raw;
    BitField<0,1,u64>  a{storage};       BitField<1,1,u64>  b{storage};
    BitField<2,1,u64>  x{storage};       BitField<3,1,u64>  y{storage};
    BitField<4,1,u64>  stick_l{storage}; BitField<5,1,u64>  stick_r{storage};
    BitField<6,1,u64>  l{storage};       BitField<7,1,u64>  r{storage};
    BitField<8,1,u64>  zl{storage};      BitField<9,1,u64>  zr{storage};
    BitField<10,1,u64> plus{storage};    BitField<11,1,u64> minus{storage};
    BitField<12,1,u64> left{storage};    BitField<13,1,u64> up{storage};
    BitField<14,1,u64> right{storage};   BitField<15,1,u64> down{storage};
    BitField<16,1,u64> stick_l_left{storage};   BitField<17,1,u64> stick_l_up{storage};
    BitField<18,1,u64> stick_l_right{storage};  BitField<19,1,u64> stick_l_down{storage};
    BitField<20,1,u64> stick_r_left{storage};   BitField<21,1,u64> stick_r_up{storage};
    BitField<22,1,u64> stick_r_right{storage};  BitField<23,1,u64> stick_r_down{storage};
    NpadButtonState() : raw(reinterpret_cast<NpadButton&>(storage)) {}
};

struct AnalogSticks { AnalogStickState left{}; AnalogStickState right{}; };
struct ControllerMotion { Common::Vec3f accel{}; Common::Vec3f gyro{}; };
using MotionState = std::array<ControllerMotion, 2>;

struct ControllerStatus {
    NpadButtonState npad_button_state{};
    AnalogSticks analog_stick_state{};
    MotionState motion_state{};
};

} // namespace Core::HID
