BINARY   := tmux-nav
INSTALL  := $(HOME)/.local/bin/$(BINARY)
GOFLAGS  := -trimpath -ldflags="-s -w"

.PHONY: build install clean tidy

build: tidy
	go build $(GOFLAGS) -o $(BINARY) .

install: build
	mkdir -p $(dir $(INSTALL))
	cp $(BINARY) $(INSTALL)
	@echo "Installed → $(INSTALL)"
	@echo "Make sure $(HOME)/.local/bin is in your PATH"

clean:
	rm -f $(BINARY)

tidy:
	go mod tidy
