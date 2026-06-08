CXX ?= clang++
CXXFLAGS = -std=c++20 -Wall -Wextra -g -O0 \
           -I../overlay \
           -Istubs \
           -Istubs/common \
           -Istubs/hid_core \
           -Istubs/hid_core/frontend

SRCS = test_main.cpp ../overlay/overlay_udp.cpp
OBJS = $(SRCS:.cpp=.o)
TARGET = overlay_test

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CXX) $(CXXFLAGS) -o $@ $^

%.o: %.cpp
	$(CXX) $(CXXFLAGS) -c -o $@ $<

clean:
	rm -f $(OBJS) $(TARGET)

test: $(TARGET)
	./$(TARGET)

.PHONY: all clean test
