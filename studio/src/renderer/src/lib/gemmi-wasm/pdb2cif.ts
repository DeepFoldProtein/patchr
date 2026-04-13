/**
 * gemmi-wasm PDB→CIF converter
 *
 * Uses the gemmi WASM module (convert.js + convert.wasm) to convert
 * PDB format text to mmCIF format entirely in the browser.
 *
 * The .js and .wasm files live in public/gemmi-wasm/ so Vite serves
 * them as static assets at /gemmi-wasm/convert.{js,wasm}.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type GemmiModule = any;

let modulePromise: Promise<GemmiModule> | null = null;

/**
 * Lazily load and initialise the gemmi WASM module (singleton).
 */
function getModule(): Promise<GemmiModule> {
  if (modulePromise) return modulePromise;

  modulePromise = new Promise<GemmiModule>((resolve, reject) => {
    try {
      // Pre-configure the Emscripten Module object
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const ModuleConfig: any = {
        locateFile: (path: string) => {
          if (path.endsWith(".wasm")) return "/gemmi-wasm/convert.wasm";
          return path;
        },
        onRuntimeInitialized: () => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          resolve((globalThis as any).Module ?? ModuleConfig);
        },
        // Suppress Emscripten stdout/stderr noise
        print: () => {},
        printErr: () => {}
      };

      // Inject as global `Module` before the script runs
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (globalThis as any).Module = ModuleConfig;

      // Dynamically load the Emscripten glue script from public/
      const script = document.createElement("script");
      script.src = "/gemmi-wasm/convert.js";
      script.onerror = () => reject(new Error("Failed to load gemmi WASM"));
      document.head.appendChild(script);
    } catch (e) {
      reject(e);
    }
  });

  return modulePromise;
}

/**
 * Convert PDB format text to mmCIF using gemmi-wasm.
 *
 * @param pdbText  PDB file content as a string
 * @returns        mmCIF file content as a string
 * @throws         If the conversion fails (e.g. malformed PDB)
 */
export async function pdb2cif(pdbText: string): Promise<string> {
  const Module = await getModule();

  // Encode PDB text to bytes
  const encoder = new TextEncoder();
  const pdbBytes = encoder.encode(pdbText);

  // Allocate WASM memory and copy input
  const buffer = Module._malloc(pdbBytes.length);
  Module.writeArrayToMemory(pdbBytes, buffer);

  // Call the conversion function
  const ret = Module._pdb2cif(buffer, pdbBytes.length);

  // Read the result
  // ret is a pointer to the error string (if any), or 0 on success.
  // The output CIF is stored in an internal global string.
  if (ret !== 0) {
    const errorMsg = Module.UTF8ToString(ret);
    Module._clear_string();
    throw new Error(`gemmi pdb2cif failed: ${errorMsg}`);
  }

  // Read output: get pointer and size of the global output string
  const size = Module._get_global_str_size();
  const ptr = Module._get_str2();
  const cifText = Module.UTF8ToString(ptr, size);

  // Clean up
  Module._clear_string();

  return cifText;
}
