PS5_HOST ?= ps5
PS5_PORT ?= 9021
HTTP_PORT ?= 2634

ifdef PS5_PAYLOAD_SDK
    include $(PS5_PAYLOAD_SDK)/toolchain/prospero.mk
else
    $(error PS5_PAYLOAD_SDK is not set. Install https://github.com/ps5-payload-dev/sdk and export PS5_PAYLOAD_SDK=/home/blurf/PS5/ps5-payload-sdk)
endif

ELF := ps5-downloader.elf
CFLAGS := -Wall -Wextra -Werror -O2 -g -pthread -DPS5_DOWNLOADER_PORT=$(HTTP_PORT)

all: $(ELF)

$(ELF): main.c
	$(CC) $(CFLAGS) -o $@ $^

clean:
	rm -f $(ELF)

test: $(ELF)
	$(PS5_DEPLOY) -h $(PS5_HOST) -p $(PS5_PORT) $^
