.PHONY: test serve gui lint clean ps5-elf desktop-linux appimage

PORT ?= 2634

test:
	PYTHONPATH=src python3 -m unittest discover -s tests

serve:
	PYTHONPATH=src python3 -m ps5_downloader serve --host 0.0.0.0 --port $(PORT)

gui:
	PYTHONPATH=src python3 -m ps5_downloader.desktop.app

lint:
	PYTHONPATH=src python3 -m compileall src tests

ps5-elf:
	$(MAKE) -C src/ps5_payload

desktop-linux:
	scripts/build-desktop-linux.sh

appimage:
	scripts/build-appimage.sh

clean:
	rm -rf build release *.egg-info .coverage
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
