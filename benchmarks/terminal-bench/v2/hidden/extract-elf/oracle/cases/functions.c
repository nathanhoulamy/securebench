#include <stdint.h>
#include <stdio.h>

static __attribute__((noinline)) uint32_t rotate_left(
    uint32_t value, unsigned bits) {
  return (value << bits) | (value >> (32 - bits));
}

static __attribute__((noinline)) uint32_t round_one(uint32_t value) {
  return rotate_left(value ^ 0xa5c37e19u, 5) + 0x10203040u;
}

static __attribute__((noinline)) uint32_t round_two(uint32_t value) {
  return rotate_left(value + 0x31415926u, 11) ^ 0x27182818u;
}

static __attribute__((noinline)) uint32_t transform(uint32_t value) {
  for (unsigned index = 0; index < 12; index++) {
    value = round_two(round_one(value + index));
  }
  return value;
}

int main(int argc, char **argv) {
  uint32_t seed = (uint32_t)argc;
  for (int index = 0; index < argc; index++) {
    seed += (unsigned char)argv[index][0];
  }
  printf("%08x\n", transform(seed));
  return 0;
}
