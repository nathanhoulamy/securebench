#include <stdint.h>
#include <stdio.h>

const uint32_t lookup[] = {
    0x01234567, 0x89abcdef, 0x13579bdf, 0x2468ace0,
    0x0badc0de, 0xfeedface, 0xc001d00d, 0x55aa55aa,
};
const char banner[] = "SecureBench ELF section challenge";
volatile uint32_t counters[] = {3, 5, 8, 13, 21, 34, 55, 89};

static uint32_t mix(uint32_t value, uint32_t index) {
  value ^= lookup[index % (sizeof(lookup) / sizeof(lookup[0]))];
  return (value << 7) | (value >> 25);
}

int main(void) {
  uint32_t value = 0;
  for (uint32_t i = 0; i < 8; i++) {
    value = mix(value + counters[i], i);
  }
  printf("%s: %u\n", banner, value);
  return 0;
}
