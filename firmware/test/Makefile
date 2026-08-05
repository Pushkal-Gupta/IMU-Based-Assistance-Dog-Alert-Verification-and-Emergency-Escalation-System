# Host build of the collar's algorithmic core.
#
# The feature extractor, the forest walker and the verification gate are
# deliberately free of Arduino/ESP-IDF headers, so they compile with any C99
# compiler and can be tested on a laptop against golden vectors from the real
# dataset.
#
#   make run      build and run the tests
#   make clean
#
# Regenerate the vectors after retraining:
#   python ../../ml/scripts/make_firmware_vectors.py

CC      ?= cc
CFLAGS  ?= -std=c99 -O2 -Wall -Wextra -Wpedantic -Wshadow -Wconversion \
           -Wno-sign-conversion -Wno-float-conversion
LDFLAGS ?= -lm

SRC_DIR := ../collar/src
SOURCES := test_native.c \
           $(SRC_DIR)/ca_features.c \
           $(SRC_DIR)/ca_forest.c \
           $(SRC_DIR)/ca_verify.c \
           $(SRC_DIR)/ca_ring.c
HEADERS := $(SRC_DIR)/ca_features.h \
           $(SRC_DIR)/ca_forest.h \
           $(SRC_DIR)/ca_verify.h \
           $(SRC_DIR)/ca_ring.h \
           $(SRC_DIR)/model.h

BINARY  := test_native
VECTORS := vectors.bin

.PHONY: all run clean

all: $(BINARY)

$(BINARY): $(SOURCES) $(HEADERS)
	$(CC) $(CFLAGS) -o $@ $(SOURCES) $(LDFLAGS)

run: $(BINARY) $(VECTORS)
	./$(BINARY) $(VECTORS)

$(VECTORS):
	@echo "vectors.bin is missing -- generate it with:"
	@echo "  python ../../ml/scripts/make_firmware_vectors.py"
	@false

clean:
	rm -f $(BINARY)
