#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_SIGNALS 32000
#define MAX_LINES 31999
#define MAX_LINE_BYTES 255
#define MAX_STEPS 32000

typedef enum {
    OP_CONST_0,
    OP_CONST_1,
    OP_COPY,
    OP_NOT,
    OP_AND,
    OP_OR,
    OP_XOR
} OpType;

typedef struct {
    OpType type;
    uint32_t source_1;
    uint32_t source_2;
} Gate;

typedef struct {
    uint32_t *items;
    size_t size;
    size_t capacity;
} MinHeap;

static Gate gates[MAX_SIGNALS];
static uint8_t defined[MAX_SIGNALS];
static uint8_t values[MAX_SIGNALS];

static int candidate_error(const char *code) {
    (void)fprintf(stderr, "%s\n", code);
    return 10;
}

static void skip_horizontal_space(const char **cursor, const char *end) {
    while (*cursor < end && (**cursor == ' ' || **cursor == '\t')) {
        *cursor += 1;
    }
}

static int parse_index(const char **cursor, const char *end, uint32_t *value) {
    uint32_t parsed = 0;
    int digits = 0;
    while (*cursor < end && **cursor >= '0' && **cursor <= '9') {
        uint32_t digit = (uint32_t)(**cursor - '0');
        if (parsed > (MAX_SIGNALS - 1U - digit) / 10U) {
            return -1;
        }
        parsed = parsed * 10U + digit;
        *cursor += 1;
        digits += 1;
    }
    if (!digits || parsed >= MAX_SIGNALS) {
        return -1;
    }
    *value = parsed;
    return 0;
}

static int parse_out_index(const char **cursor, const char *end, uint32_t *value) {
    if ((size_t)(end - *cursor) < 4U || memcmp(*cursor, "out", 3U) != 0) {
        return -1;
    }
    *cursor += 3;
    return parse_index(cursor, end, value);
}

static int parse_expression(const char *cursor, const char *end, Gate *gate) {
    skip_horizontal_space(&cursor, end);
    if (cursor < end && (*cursor == '0' || *cursor == '1')) {
        char constant = *cursor++;
        skip_horizontal_space(&cursor, end);
        if (cursor != end) {
            return -1;
        }
        gate->type = constant == '0' ? OP_CONST_0 : OP_CONST_1;
        return 0;
    }

    if (cursor < end && *cursor == '~') {
        cursor += 1;
        if (parse_out_index(&cursor, end, &gate->source_1) != 0) {
            return -1;
        }
        skip_horizontal_space(&cursor, end);
        if (cursor != end) {
            return -1;
        }
        gate->type = OP_NOT;
        return 0;
    }

    if (parse_out_index(&cursor, end, &gate->source_1) != 0) {
        return -1;
    }
    skip_horizontal_space(&cursor, end);
    if (cursor == end) {
        gate->type = OP_COPY;
        return 0;
    }

    char operator = *cursor++;
    if (operator != '&' && operator != '|' && operator != '^') {
        return -1;
    }
    skip_horizontal_space(&cursor, end);
    if (parse_out_index(&cursor, end, &gate->source_2) != 0) {
        return -1;
    }
    skip_horizontal_space(&cursor, end);
    if (cursor != end) {
        return -1;
    }
    gate->type = operator == '&' ? OP_AND : operator == '|' ? OP_OR : OP_XOR;
    return 0;
}

static int parse_line(char *line, size_t length, uint32_t *output) {
    const char *cursor = line;
    const char *end = line + length;
    if (parse_out_index(&cursor, end, output) != 0) {
        return -1;
    }
    skip_horizontal_space(&cursor, end);
    if (cursor == end || *cursor++ != '=') {
        return -1;
    }
    return parse_expression(cursor, end, &gates[*output]);
}

static int parse_gates(const char *path, uint32_t *signal_count) {
    FILE *stream = fopen(path, "rb");
    if (stream == NULL) {
        return candidate_error("circuit_unavailable");
    }

    char *line = NULL;
    size_t capacity = 0;
    ssize_t length;
    uint32_t line_count = 0;
    uint32_t maximum_output = 0;
    int saw_definition = 0;
    int status = 0;

    while ((length = getline(&line, &capacity, stream)) >= 0) {
        line_count += 1U;
        if (line_count > MAX_LINES) {
            status = candidate_error("too_many_gates");
            break;
        }
        if (memchr(line, '\0', (size_t)length) != NULL) {
            status = candidate_error("invalid_gate");
            break;
        }
        while (length > 0 && (line[length - 1] == '\n' || line[length - 1] == '\r')) {
            length -= 1;
        }
        if (length > MAX_LINE_BYTES) {
            status = candidate_error("gate_line_too_long");
            break;
        }
        if (length == 0) {
            continue;
        }

        uint32_t output;
        if (parse_line(line, (size_t)length, &output) != 0) {
            status = candidate_error("invalid_gate");
            break;
        }
        if (defined[output]) {
            status = candidate_error("duplicate_signal");
            break;
        }
        defined[output] = 1U;
        saw_definition = 1;
        if (output > maximum_output) {
            maximum_output = output;
        }
    }
    if (ferror(stream) && status == 0) {
        status = candidate_error("circuit_unavailable");
    }
    free(line);
    (void)fclose(stream);
    if (status != 0) {
        return status;
    }
    if (!saw_definition) {
        return candidate_error("empty_circuit");
    }
    *signal_count = maximum_output + 1U;
    if (*signal_count < 32U) {
        return candidate_error("insufficient_outputs");
    }
    return 0;
}

static int heap_initialize(MinHeap *heap, size_t capacity) {
    heap->items = calloc(capacity, sizeof(*heap->items));
    heap->size = 0;
    heap->capacity = capacity;
    return heap->items == NULL ? -1 : 0;
}

static int heap_push(MinHeap *heap, uint32_t value) {
    if (heap->size >= heap->capacity) {
        return -1;
    }
    size_t index = heap->size++;
    heap->items[index] = value;
    while (index > 0U) {
        size_t parent = (index - 1U) / 2U;
        if (heap->items[parent] <= heap->items[index]) {
            break;
        }
        uint32_t temporary = heap->items[parent];
        heap->items[parent] = heap->items[index];
        heap->items[index] = temporary;
        index = parent;
    }
    return 0;
}

static uint32_t heap_pop(MinHeap *heap) {
    uint32_t result = heap->items[0];
    heap->size -= 1U;
    if (heap->size == 0U) {
        return result;
    }
    heap->items[0] = heap->items[heap->size];
    size_t index = 0;
    for (;;) {
        size_t left = index * 2U + 1U;
        size_t right = left + 1U;
        size_t smallest = index;
        if (left < heap->size && heap->items[left] < heap->items[smallest]) {
            smallest = left;
        }
        if (right < heap->size && heap->items[right] < heap->items[smallest]) {
            smallest = right;
        }
        if (smallest == index) {
            break;
        }
        uint32_t temporary = heap->items[index];
        heap->items[index] = heap->items[smallest];
        heap->items[smallest] = temporary;
        index = smallest;
    }
    return result;
}

static uint8_t gate_value(const Gate *gate) {
    switch (gate->type) {
        case OP_CONST_0:
            return 0U;
        case OP_CONST_1:
            return 1U;
        case OP_COPY:
            return values[gate->source_1];
        case OP_NOT:
            return (uint8_t)(1U ^ values[gate->source_1]);
        case OP_AND:
            return (uint8_t)(values[gate->source_1] & values[gate->source_2]);
        case OP_OR:
            return (uint8_t)(values[gate->source_1] | values[gate->source_2]);
        case OP_XOR:
            return (uint8_t)(values[gate->source_1] ^ values[gate->source_2]);
    }
    return 0U;
}

static int build_dependencies(uint32_t signal_count, uint32_t **offsets_out, uint32_t **edges_out) {
    uint32_t *counts = calloc(signal_count, sizeof(*counts));
    uint32_t *offsets = calloc((size_t)signal_count + 1U, sizeof(*offsets));
    uint32_t *cursor = calloc(signal_count, sizeof(*cursor));
    if (counts == NULL || offsets == NULL || cursor == NULL) {
        free(counts);
        free(offsets);
        free(cursor);
        return -1;
    }

    for (uint32_t output = 0; output < signal_count; output += 1U) {
        Gate gate = gates[output];
        if (gate.type >= OP_COPY && gate.source_1 < signal_count) {
            counts[gate.source_1] += 1U;
        }
        if (gate.type >= OP_AND && gate.source_2 < signal_count) {
            counts[gate.source_2] += 1U;
        }
    }
    for (uint32_t index = 0; index < signal_count; index += 1U) {
        offsets[index + 1U] = offsets[index] + counts[index];
        cursor[index] = offsets[index];
    }
    uint32_t *edges = calloc(offsets[signal_count], sizeof(*edges));
    if (edges == NULL && offsets[signal_count] != 0U) {
        free(counts);
        free(offsets);
        free(cursor);
        return -1;
    }
    for (uint32_t output = 0; output < signal_count; output += 1U) {
        Gate gate = gates[output];
        if (gate.type >= OP_COPY && gate.source_1 < signal_count) {
            edges[cursor[gate.source_1]++] = output;
        }
        if (gate.type >= OP_AND && gate.source_2 < signal_count) {
            edges[cursor[gate.source_2]++] = output;
        }
    }
    free(counts);
    free(cursor);
    *offsets_out = offsets;
    *edges_out = edges;
    return 0;
}

static int simulate(uint32_t signal_count, uint32_t input, uint32_t *result) {
    int status = -1;
    uint32_t *offsets = NULL;
    uint32_t *edges = NULL;
    uint32_t *processed_epoch = calloc(signal_count, sizeof(*processed_epoch));
    uint32_t *scheduled_epoch = calloc(signal_count, sizeof(*scheduled_epoch));
    uint32_t *next_epoch = calloc(signal_count, sizeof(*next_epoch));
    MinHeap current = {0};
    MinHeap upcoming = {0};
    if (
        processed_epoch == NULL || scheduled_epoch == NULL || next_epoch == NULL ||
        heap_initialize(&current, signal_count) != 0 ||
        heap_initialize(&upcoming, signal_count) != 0 ||
        build_dependencies(signal_count, &offsets, &edges) != 0
    ) {
        goto cleanup;
    }

    for (uint32_t index = 0; index < 32U; index += 1U) {
        values[index] = (uint8_t)((input >> index) & 1U);
    }
    for (uint32_t index = 0; index < signal_count; index += 1U) {
        if (heap_push(&current, index) != 0) {
            goto cleanup;
        }
    }

    for (uint32_t step = 0; step < MAX_STEPS && current.size > 0U; step += 1U) {
        uint32_t epoch = step + 1U;
        for (size_t index = 0; index < current.size; index += 1U) {
            scheduled_epoch[current.items[index]] = epoch;
        }
        upcoming.size = 0;
        while (current.size > 0U) {
            uint32_t output = heap_pop(&current);
            if (processed_epoch[output] == epoch) {
                continue;
            }
            processed_epoch[output] = epoch;
            uint8_t new_value = gate_value(&gates[output]);
            if (new_value == values[output]) {
                continue;
            }
            values[output] = new_value;
            for (uint32_t edge = offsets[output]; edge < offsets[output + 1U]; edge += 1U) {
                uint32_t dependent = edges[edge];
                if (
                    dependent > output && processed_epoch[dependent] != epoch &&
                    scheduled_epoch[dependent] != epoch
                ) {
                    if (heap_push(&current, dependent) != 0) {
                        goto cleanup;
                    }
                    scheduled_epoch[dependent] = epoch;
                }
                if (next_epoch[dependent] != epoch) {
                    if (heap_push(&upcoming, dependent) != 0) {
                        goto cleanup;
                    }
                    next_epoch[dependent] = epoch;
                }
            }
        }
        MinHeap temporary = current;
        current = upcoming;
        upcoming = temporary;
    }

    uint32_t output_value = 0;
    for (uint32_t bit = 0; bit < 32U; bit += 1U) {
        if (values[signal_count - 32U + bit]) {
            output_value |= 1U << bit;
        }
    }
    *result = output_value;
    status = 0;

cleanup:
    free(processed_epoch);
    free(scheduled_epoch);
    free(next_epoch);
    free(current.items);
    free(upcoming.items);
    free(offsets);
    free(edges);
    return status;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        return candidate_error("invalid_invocation");
    }
    errno = 0;
    char *end = NULL;
    unsigned long long parsed = strtoull(argv[2], &end, 10);
    if (errno != 0 || end == argv[2] || *end != '\0' || parsed > UINT32_MAX) {
        return candidate_error("invalid_input");
    }

    uint32_t signal_count;
    int parse_status = parse_gates(argv[1], &signal_count);
    if (parse_status != 0) {
        return parse_status;
    }
    uint32_t result;
    if (simulate(signal_count, (uint32_t)parsed, &result) != 0) {
        return candidate_error("simulation_resource_error");
    }
    (void)printf("%u\n", result);
    return 0;
}
