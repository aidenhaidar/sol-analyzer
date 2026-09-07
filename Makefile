# One entry point for the four-language build.
#   make setup   install JS + Python deps, wasm target, wasm-bindgen CLI
#   make build   build C++ lib, Rust->wasm, and the web bundle
#   make test    run C++, Rust, Python and TypeScript tests
#   make train   refit the holder churn classifier
#   make dev     run API (8787) + Vite dev server (5173) together
#   make serve   run the API serving the built web bundle (production)

.PHONY: setup native wasm web build test train dev serve clean

setup:
	cd web && npm install
	pip install -r api/requirements.txt
	rustup target add wasm32-unknown-unknown
	cargo install wasm-bindgen-cli --version 0.2.100

native:
	cmake -S native -B native/build -DCMAKE_BUILD_TYPE=Release
	cmake --build native/build

wasm:
	./analytics/build.sh

web: wasm
	cd web && npm run build

build: native web

test: native
	./native/build/solagg_test
	./native/build/cascade_test
	cd analytics && cargo test --release
	python3 -m pytest api/tests -q
	cd web && npx tsc --noEmit -p tsconfig.json && npx vitest run

train:
	python3 -m api.ml.train

dev: native
	cd web && npm run dev

serve: build
	uvicorn api.main:app --host 0.0.0.0 --port $${PORT:-8787}

clean:
	rm -rf native/build analytics/target web/dist
